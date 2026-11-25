import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from _paths import ITEM, OFFER
import harness
from common import parse_json_array, write_results
from score import estimate, record_id, score


class ValidationTests(unittest.TestCase):
    def test_review_counts_duplicates_and_keeps_unresolved_out_of_precision(self):
        row = {"item_id": "1", **{k: str(v) for k, v in OFFER.items()}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.csv"
            other = {**row, "product": "Unreviewed"}
            write_results(path, [row, row, other])
            self.assertNotIn("valid", score(path))
            path.with_suffix(".review.json").write_text(json.dumps({"records": [
                {"record_id": record_id(row), "status": "valid", "event_id": "item-1-brand-carry-on",
                 "verified_source": row["source_url"]}
            ]}))
            result = score(path)
            self.assertEqual((result["valid"], result["duplicate"], result["unresolved"]), (1, 1, 1))
            self.assertIsNone(result["precision"])

    def test_a_valid_label_needs_an_event_and_a_verified_source(self):
        row = {"item_id": "1", **{k: str(v) for k, v in OFFER.items()}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.csv"
            write_results(path, [row])
            path.with_suffix(".review.json").write_text(json.dumps({"records": [
                {"record_id": record_id(row), "status": "valid"}]}))
            self.assertEqual(score(path)["unresolved"], 1)

    def test_invalid_output_is_not_a_successful_empty_result(self):
        for text in ["not JSON", "[1]", '[{"product":"missing fields"}]',
                     json.dumps([{**OFFER, "price_usd": "about $245"}])]:
            with self.assertRaises(ValueError):
                parse_json_array(text, strict=True)
        self.assertEqual(parse_json_array("[]", strict=True), [])
        self.assertEqual(parse_json_array(json.dumps([OFFER]), strict=True), [OFFER])
        self.assertEqual(parse_json_array("not JSON"), [])

    def test_serving_model_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            harness.usage_row(SimpleNamespace(model="different", stop_reason="end_turn", usage=SimpleNamespace(
                input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)),
                "claude-opus-5-5")

    def test_failed_run_keeps_completed_usage_and_provider_trace(self):
        from web_router import AsyncWebRouter
        usage = SimpleNamespace(input_tokens=11, output_tokens=7, cache_read_input_tokens=3,
                                cache_creation_input_tokens=5)
        first = SimpleNamespace(usage=usage, content=[SimpleNamespace(type="tool_use", name="web_router_search",
                                id="search-1", input={"query": "carry-on"})], stop_reason="tool_use")
        tools = SimpleNamespace(router=AsyncWebRouter(), definitions=lambda: [], call=lambda *a: SimpleNamespace(
            content="source evidence", is_error=False, response=SimpleNamespace(cost_usd=0.008, provider="tavily")))
        with tempfile.TemporaryDirectory() as tmp, \
             patch("sys.argv", ["harness.py", "--web", "webrouter", "--limit", "1", "--output-dir", tmp]), \
             patch.object(harness.anthropic, "Anthropic", return_value=MagicMock()), \
             patch.object(harness, "webrouter_tools", return_value=tools), \
             patch.object(harness, "ask", side_effect=[first, RuntimeError("simulated interruption")]):
            with self.assertRaises(SystemExit):
                harness.main()
            details = json.loads(next(Path(tmp).glob("*/*.details.json")).read_text())[0]
            metrics = json.loads(next(Path(tmp).glob("*/*.metrics.json")).read_text())
            manifest = json.loads(next(Path(tmp).glob("*/manifest.json")).read_text())
            self.assertTrue(next(Path(tmp).glob("*/attempts.json")).exists())
            self.assertEqual((details["in"], details["out"], details["web_calls"]), (19, 7, 1))
            self.assertEqual(details["trace"][0]["provider"], "tavily")
            self.assertEqual(details["item_id"], "1")
            self.assertEqual(manifest["items"], ["1"])
            self.assertFalse(metrics["complete"])
            self.assertIsNone(metrics["cost_usd"])
            self.assertIsNone(metrics["model_cost_usd"])

    def test_routed_allowances_count_urls_and_preserve_denials(self):
        from concurrent.futures import ThreadPoolExecutor
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0)
        uses = [SimpleNamespace(type="tool_use", name="web_router_search", id="s1", input={"query": "a"}),
                SimpleNamespace(type="tool_use", name="web_router_search", id="s2", input={"query": "b"}),
                SimpleNamespace(type="tool_use", name="web_router_extract", id="e1",
                                input={"urls": ["https://example.com/a", "https://example.com/b"]}),
                SimpleNamespace(type="tool_use", name="web_router_extract", id="e2",
                                input={"urls": ["https://example.com/c"]})]
        first = SimpleNamespace(usage=usage, content=uses, stop_reason="tool_use")
        final = SimpleNamespace(usage=usage, content=[SimpleNamespace(type="text", text="[]")], stop_reason="end_turn")
        tools = SimpleNamespace(definitions=lambda: [], call=lambda *a: SimpleNamespace(
            content="evidence", is_error=False, response=SimpleNamespace(cost_usd=None)))
        with patch.object(harness, "ask", side_effect=[first, final]), ThreadPoolExecutor(2) as pool:
            result = harness.run_webrouter(ITEM, "claude-opus-5-5", tools, pool, 1, 2)
        self.assertEqual((result["searches"], result["fetched_urls"], result["unknown_cost_calls"]), (1, 2, 2))
        self.assertEqual(sum(t.get("outcome") == "allowance_denied" for t in result["trace"]), 2)

    def test_unpriced_logged_call_is_flagged_and_the_estimate_stays_a_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calls.jsonl"
            path.write_text("\n".join(json.dumps(c) for c in [
                {"tool": "extract", "cost_usd": None, "result_chars": 100},
                {"tool": "search", "cost_usd": 0.005, "result_chars": 100},
                {"tool": "WebFetch", "result_chars": 100}]))
            result = estimate(path)
            self.assertEqual(result["unknown_cost_calls"], 1)
            self.assertIsInstance(result["est_cost_usd"], float)
            self.assertEqual(result["est_web_cost_usd"], 0.005)

    def test_budgeted_mcp_auto_extract_reaches_priced_provider(self):
        try:
            from web_router.mcp.tools import WebRouterTools
        except ImportError:
            self.skipTest("needs the organizers dependency group: uv run --group organizers ...")
        from web_router import AsyncWebRouter
        from web_router.providers.tavily import TavilyExtractProvider
        from web_router.types import ExtractResponse, ExtractedDocument

        async def run():
            router = AsyncWebRouter(provider_config={"auto": {"chain": {"extract": [("tavily", {"allow_keyless": True})]}}})
            tools = WebRouterTools(router)
            response = ExtractResponse(provider="tavily", documents=[ExtractedDocument(
                url="https://example.com", content="Dated source evidence", format="markdown")])
            try:
                await tools.call("budget_start", {"max_cost_usd": 0.5, "time_limit_s": 600})
                with patch.object(TavilyExtractProvider, "_aextract", new=AsyncMock(return_value=response)) as fetch:
                    result = await tools.call("extract", {"urls": ["https://example.com"]})
                    self.assertEqual(fetch.await_count, 1)
                    self.assertIn("Dated source evidence", json.dumps(result))
                status = await tools.call("budget_status", {})
                self.assertIsNotNone(status)
            finally:
                await tools.aclose()
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
