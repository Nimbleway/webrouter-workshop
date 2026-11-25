import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import harness
from common import parse_json_array, write_results
from score import record_id, same_event, score


class ValidationTests(unittest.TestCase):
    def test_unrelated_titles_shared_url_and_wrong_dates_do_not_match(self):
        event = dict(company='Vercel', announcement='Introducing Geist Serif', event_date='2026-10-30', source_url='https://example.com/news')
        self.assertFalse(same_event(event, {**event, 'announcement': 'Introducing eve 1.0'}))
        self.assertFalse(same_event(event, {**event, 'event_date': '2026-11-01'}))
        self.assertFalse(same_event(event, {**event, 'announcement': 'INCOMPLETE LIST'}))

    def test_review_counts_duplicates_and_keeps_unresolved_out_of_precision(self):
        row = dict(company='Figma', announcement='A launch', event_date='2026-11-01', evidence='Evidence', source_url='https://example.com')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'run.csv'
            other = {**row, 'announcement': 'Unreviewed'}
            write_results(path, [row, row, other])
            path.with_suffix('.review.json').write_text(json.dumps({'records': [
                {'record_id': record_id(row), 'status': 'valid', 'event_id': 'event-1', 'verified_source': row['source_url']}
            ], 'reference_event_ids': ['event-1'], 'reference_complete': False}))
            result = score(path)
            self.assertEqual((result['valid'], result['duplicate'], result['unresolved']), (1, 1, 1))
            self.assertIsNone(result['precision'])
            self.assertIsNone(result['recall'])

    def test_invalid_output_is_not_a_successful_empty_result(self):
        for text in ['not JSON', '[1]', '[{"announcement":"missing fields"}]']:
            with self.assertRaises(ValueError):
                parse_json_array(text, strict=True)
        self.assertEqual(parse_json_array('[]', strict=True), [])

    def test_serving_model_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            harness.usage_row(SimpleNamespace(model='different', stop_reason='end_turn', usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)), 'claude-opus-5-5')

    def test_failed_run_keeps_completed_usage_and_provider_trace(self):
        from unittest.mock import MagicMock
        from web_router import AsyncWebRouter
        usage = SimpleNamespace(input_tokens=11, output_tokens=7, cache_read_input_tokens=3,
                                cache_creation_input_tokens=5)
        first = SimpleNamespace(usage=usage, content=[SimpleNamespace(type="tool_use", name="web_router_search",
                                id="search-1", input={"query": "release"})], stop_reason="tool_use")
        tools = SimpleNamespace(router=AsyncWebRouter(), definitions=lambda: [], call=lambda *a: SimpleNamespace(
            content="source evidence", is_error=False, response=SimpleNamespace(cost_usd=0.008, provider="tavily")))
        with tempfile.TemporaryDirectory() as tmp, patch('sys.argv', ['harness.py', '--web', 'webrouter', '--limit', '1', '--output-dir', tmp]), \
             patch.object(harness.anthropic, 'Anthropic', return_value=MagicMock()), \
             patch.object(harness, 'webrouter_tools', return_value=tools), \
             patch.object(harness, 'ask', side_effect=[first, RuntimeError('simulated interruption')]):
            with self.assertRaises(SystemExit):
                harness.main()
            details = json.loads(next(Path(tmp).glob('*/*.details.json')).read_text())[0]
            metrics = json.loads(next(Path(tmp).glob('*/*.metrics.json')).read_text())
            self.assertEqual((details['in'], details['out'], details['web_calls']), (19, 7, 1))
            self.assertEqual(details['trace'][0]['provider'], 'tavily')
            self.assertFalse(metrics['complete'])
            self.assertIsNone(metrics['cost_usd'])
            self.assertIsNone(metrics['model_cost_usd'])

    def test_routed_allowances_count_urls_and_preserve_denials(self):
        from concurrent.futures import ThreadPoolExecutor
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0)
        uses = [SimpleNamespace(type="tool_use", name="web_router_search", id="s1", input={"query": "a"}),
                SimpleNamespace(type="tool_use", name="web_router_search", id="s2", input={"query": "b"}),
                SimpleNamespace(type="tool_use", name="web_router_extract", id="e1", input={"urls": ["https://example.com/a", "https://example.com/b"]}),
                SimpleNamespace(type="tool_use", name="web_router_extract", id="e2", input={"urls": ["https://example.com/c"]})]
        first = SimpleNamespace(usage=usage, content=uses, stop_reason="tool_use")
        final = SimpleNamespace(usage=usage, content=[SimpleNamespace(type="text", text="[]")], stop_reason="end_turn")
        tools = SimpleNamespace(definitions=lambda: [], call=lambda *a: SimpleNamespace(
            content="evidence", is_error=False, response=SimpleNamespace(cost_usd=None)))
        with patch.object(harness, "ask", side_effect=[first, final]), ThreadPoolExecutor(2) as pool:
            result = harness.run_webrouter("Figma", "claude-opus-5-5", tools, pool, 1, 2)
        self.assertEqual((result["searches"], result["fetched_urls"], result["unknown_cost_calls"]), (1, 2, 2))
        self.assertEqual(sum(t.get("outcome") == "allowance_denied" for t in result["trace"]), 2)

    def test_unknown_logged_tool_price_is_not_free(self):
        from score import estimate
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calls.jsonl"
            path.write_text(json.dumps({"tool": "extract", "cost_usd": None, "result_chars": 100}))
            self.assertIsNone(estimate(path)["est_cost_usd"])
            self.assertEqual(estimate(path)["unknown_cost_calls"], 1)

    def test_budgeted_mcp_auto_extract_reaches_priced_provider(self):
        from web_router import AsyncWebRouter
        from web_router.mcp.tools import WebRouterTools
        from web_router.providers.tavily import TavilyExtractProvider
        from web_router.types import ExtractResponse, ExtractedDocument

        async def run():
            router = AsyncWebRouter(provider_config={'auto': {'chain': {'extract': [('tavily', {'allow_keyless': True})]}}})
            tools = WebRouterTools(router)
            response = ExtractResponse(provider='tavily', documents=[ExtractedDocument(
                url='https://example.com', content='Dated source evidence', format='markdown')])
            try:
                await tools.call('budget_start', {'max_cost_usd': 0.5, 'time_limit_s': 600})
                with patch.object(TavilyExtractProvider, '_aextract', new=AsyncMock(return_value=response)) as fetch:
                    result = await tools.call('extract', {'urls': ['https://example.com']})
                    self.assertEqual(fetch.await_count, 1)
                    self.assertIn('Dated source evidence', json.dumps(result))
                status = await tools.call('budget_status', {})
                self.assertIsNotNone(status)
            finally:
                await tools.aclose()
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
