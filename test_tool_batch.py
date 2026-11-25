import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from tool_batch import execute_batch


class BatchTests(unittest.TestCase):
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
                                cache_read_input_tokens=0, cache_creation_input_tokens=0)
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
        self.assertEqual(result["in"], 20)
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
            results, cost, trace = execute_batch(Tools(), [SimpleNamespace(id="x", name="extract", input={})], pool)
        self.assertTrue(results[0]["is_error"])
        self.assertEqual(cost, 0)
        self.assertIsNone(trace[0]["provider"])


if __name__ == "__main__":
    unittest.main()
