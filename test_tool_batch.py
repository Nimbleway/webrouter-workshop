import asyncio
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from tool_batch import execute_batch
from provider_trace import trace_providers


class BatchTests(unittest.TestCase):
    def test_native_continuations_enable_caching_and_keep_usage_categories(self):
        with patch("anthropic.Anthropic"):
            import harness

        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=20,
                                cache_creation_input_tokens=30,
                                server_tool_use=SimpleNamespace(web_search_requests=2))
        first = SimpleNamespace(usage=usage, content=[], stop_reason="pause_turn")
        final = SimpleNamespace(usage=usage, content=[SimpleNamespace(type="text", text="[]")], stop_reason="end_turn")
        with patch.object(harness, "client") as client:
            client.beta.messages.create.side_effect = [first, final]
            result = harness.run_native("Figma", "claude-opus-5-5")
            for call in client.beta.messages.create.call_args_list:
                self.assertEqual(call.kwargs["cache_control"], {"type": "ephemeral"})
        self.assertEqual((result["in"], result["out"], result["cache_read"], result["cache_write"]), (120, 10, 40, 60))
        self.assertEqual(result["web_calls"], 4)
        self.assertAlmostEqual(result["web_cost"], 0.04)

    def test_cache_reads_writes_and_uncached_input_have_distinct_costs(self):
        from common import llm_cost

        self.assertAlmostEqual(llm_cost("claude-opus-5-5", 1_000_000, 1_000_000,
                                        cache_read=1_000_000, cache_write=1_000_000), 29.2)
        self.assertAlmostEqual(llm_cost("claude-haiku-5-5", 1_000_000, 1_000_000,
                                        cache_read=1_000_000, cache_write=1_000_000), 0.735)

    def test_opt_in_profile_hedges_a_stalled_primary_and_returns_every_page(self):
        from web_router import AsyncWebRouter
        from web_router.providers.base import ExtractProvider
        from web_router.registry import register_extract_provider, unregister_extract_provider
        from web_router.types import ExtractedDocument, ExtractResponse

        with patch("anthropic.Anthropic"):
            import harness

        started, cancelled = threading.Event(), threading.Event()

        class Primary(ExtractProvider):
            name = "workshop-slow"
            supported_parameters = frozenset({"format"})
            supported_formats = frozenset({"markdown"})
            default_format = "markdown"

            def _extract(self, request, urls):
                raise AssertionError("Synchronous extraction must not run")

            async def _aextract(self, request, urls):
                started.set()
                try:
                    await asyncio.sleep(60)
                    raise AssertionError("A stalled primary should have been cancelled")
                finally:
                    cancelled.set()

        class Backup(Primary):
            name = "workshop-backup"

            async def _aextract(self, request, urls):
                self_test.assertTrue(started.is_set())
                return ExtractResponse(provider=self.name, documents=[
                    ExtractedDocument(url=urls[0], content="Source evidence", format="markdown")
                ])

        self_test = self

        def isolated_router(*args, **kwargs):
            config = kwargs["provider_config"]
            config["max"]["chain"] = [Primary.name, Backup.name]
            return AsyncWebRouter(*args, **kwargs)

        for provider in (Primary, Backup):
            register_extract_provider(provider.name, provider)
        try:
            with patch("web_router.AsyncWebRouter", side_effect=isolated_router):
                tools = harness.webrouter_tools(extract_provider="max")
            uses = [SimpleNamespace(id="hedged", name="web_router_extract", input={"urls": [
                "https://example.com/one", "https://example.com/two"
            ]})]
            with trace_providers(), ThreadPoolExecutor(1) as pool:
                results, cost, trace = execute_batch(tools, uses, pool)
            payload = json.loads(results[0]["content"])
            self.assertFalse(results[0]["is_error"])
            self.assertEqual([d["url"] for d in payload["documents"]], uses[0].input["urls"])
            self.assertEqual(trace[0]["documents"], 2)
            self.assertTrue(cancelled.is_set())
            self.assertIn("cancelled", [a["outcome"] for a in trace[0]["provider_attempts"]])
            self.assertTrue(all(a["cost_usd"] is None for a in trace[0]["provider_attempts"]))
        finally:
            for provider in (Primary, Backup):
                unregister_extract_provider(provider.name)

    def test_extract_urls_overlap_and_keep_partial_failures(self):
        from web_router.providers.base import ExtractProvider
        from web_router.registry import register_extract_provider, unregister_extract_provider
        from web_router.types import ExtractedDocument, ExtractFailure, ExtractResponse

        with patch("anthropic.Anthropic"):
            import harness

        class Extractor(ExtractProvider):
            name = "workshop-test"
            supported_parameters = frozenset({"format"})
            supported_formats = frozenset({"markdown"})
            default_format = "markdown"

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.arrived = 0
                self.ready = asyncio.Event()

            def _extract(self, request, urls):
                raise AssertionError("The synchronous batch path must not run")

            async def _aextract(self, request, urls):
                self.arrived += 1
                if self.arrived == 3:
                    self.ready.set()
                await asyncio.wait_for(self.ready.wait(), timeout=2)
                if urls[0].endswith('/missing'):
                    return ExtractResponse(provider=self.name, failures=[ExtractFailure(url=urls[0], error="not found")])
                return ExtractResponse(provider=self.name, documents=[
                    ExtractedDocument(url=urls[0], title="Source", content="Original source text", format="markdown")
                ])

        register_extract_provider(Extractor.name, Extractor)
        try:
            tools = harness.webrouter_tools(extract_provider=Extractor.name)
            uses = [SimpleNamespace(id="batch", name="web_router_extract", input={"urls": [
                "https://example.com/first", "https://example.com/missing", "https://example.com/last"
            ]})]
            with ThreadPoolExecutor(1) as pool:
                results, cost, trace = execute_batch(tools, uses, pool)
            payload = json.loads(results[0]["content"])
            self.assertFalse(results[0]["is_error"])
            self.assertEqual([d["url"] for d in payload["documents"]],
                             ["https://example.com/first", "https://example.com/last"])
            self.assertEqual([d["content"] for d in payload["documents"]], ["Original source text"] * 2)
            self.assertEqual(payload["failures"][0]["url"], "https://example.com/missing")
            self.assertEqual((trace[0]["requested_urls"], trace[0]["documents"], trace[0]["failed_urls"]), (3, 2, 1))
        finally:
            unregister_extract_provider(Extractor.name)

    def test_agent_receives_parallel_results_and_keeps_cost_and_trace(self):
        with patch("anthropic.Anthropic"):
            import harness

        barrier = threading.Barrier(2)

        class Tools:
            def definitions(self):
                return []

            def call(self, name, arguments):
                barrier.wait(timeout=2)
                return SimpleNamespace(content=arguments["value"], is_error=False,
                                       response=SimpleNamespace(cost_usd=0.02, provider="fake"))

        usage = SimpleNamespace(input_tokens=10, output_tokens=5,
                                cache_read_input_tokens=20, cache_creation_input_tokens=30)
        uses = [SimpleNamespace(type="tool_use", id=str(i), name="search", input={"value": str(i)})
                for i in range(2)]
        first = SimpleNamespace(usage=usage, content=uses, stop_reason="tool_use")
        second = SimpleNamespace(usage=usage, content=[SimpleNamespace(type="text", text="[]")], stop_reason="end_turn")
        captured = []

        def ask(model, messages, tools):
            if len(messages) == 1:
                captured.append(messages[0]["content"])
                return first
            self.assertEqual([r["tool_use_id"] for r in messages[-1]["content"]], ["0", "1"])
            return second

        with patch.object(harness, "ask", ask), ThreadPoolExecutor(2) as pool:
            result = harness.run_webrouter("Figma", "fake-model", Tools(), pool)
        self.assertEqual(result["web_calls"], 2)
        self.assertAlmostEqual(result["web_cost"], 0.04)
        self.assertEqual(result["in"], 120)
        self.assertEqual(result["cache_read"], 40)
        self.assertEqual(result["cache_write"], 60)
        self.assertEqual(result["out"], 10)
        self.assertEqual([r["company"] for r in result["trace"]], ["Figma", "Figma"])
        self.assertIn("site:figma.com", captured[0])
        self.assertIn("2026-10-21", captured[0])
        self.assertIn("2026-11-20", captured[0])

    def test_parallel_results_remain_attached_to_the_correct_calls(self):
        barrier = threading.Barrier(3)

        class Tools:
            def call(self, name, arguments):
                barrier.wait(timeout=2)
                time.sleep(arguments["delay"])
                return SimpleNamespace(
                    content=arguments["value"], is_error=arguments.get("error", False),
                    response=SimpleNamespace(cost_usd=0.01, provider="fake"),
                )

        uses = [SimpleNamespace(id=str(i), name="search", input={"delay": (2-i)*0.02, "value": str(i), "error": i == 1})
                for i in range(3)]
        with ThreadPoolExecutor(3) as pool:
            results, cost, trace = execute_batch(Tools(), uses, pool)
        self.assertEqual([r["tool_use_id"] for r in results], ["0", "1", "2"])
        self.assertEqual([r["content"] for r in results], ["0", "1", "2"])
        self.assertEqual([r["is_error"] for r in results], [False, True, False])
        self.assertAlmostEqual(cost, 0.03)
        self.assertEqual([r["provider"] for r in trace], ["fake"] * 3)

    def test_single_worker_preserves_unknown_cost_and_tool_errors(self):
        class Tools:
            def call(self, name, arguments):
                return SimpleNamespace(content="failed", is_error=True, response=None)

        with ThreadPoolExecutor(1) as pool:
            results, cost, trace = execute_batch(Tools(), [SimpleNamespace(id="x", name="extract", input="invalid")], pool)
        self.assertTrue(results[0]["is_error"])
        self.assertEqual(cost, 0)
        self.assertIsNone(trace[0]["provider"])
        self.assertEqual(trace[0]["requested_urls"], 0)
        with ThreadPoolExecutor(1) as pool:
            _, _, trace = execute_batch(Tools(), [SimpleNamespace(id="failed", name="extract", input={
                "urls": ["https://example.com/one", "https://example.com/two"]
            })], pool)
        self.assertEqual(trace[0]["failed_urls"], 2)


if __name__ == "__main__":
    unittest.main()
