import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
from web_router.providers.base import SearchProvider
from web_router.types import SearchRequest, SearchResponse

from provider_trace import attempt_sink, attempt_tool_id, trace_providers


class ProviderCostTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_charge_cancellation_and_predispatch_failure(self):
        pending = asyncio.Event()
        hold = asyncio.Event()

        async def handle(request):
            if request.url.path.endswith("pending"):
                pending.set()
                await hold.wait()
            if request.url.path == "/redirect":
                return httpx.Response(307, headers={"location": "/success?api_key=secret-query"})
            return httpx.Response(200, headers={"x-request-id": "http-id", "secret": "secret-header"},
                                  json={"usage": {"credits": 3, "private": "secret-body"}})

        class Leaf(SearchProvider):
            name = "tavily"

            def _search(self, request):
                raise AssertionError("Sync call")

            async def _asearch(self, request):
                if request.query == "invalid":
                    raise ValueError("secret-error")
                await client.post("https://api.tavily.com/" + request.query, follow_redirects=True,
                                  json={"api_key": "secret-body-auth"})
                return SearchResponse(provider=self.name, query=request.query,
                                      request_id="provider-id", cost_usd=0.003, cost_source="reported",
                                      raw={"usage": {"credits": 3, "private": "secret-body"}})

        ledger, tool = [], []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle),
                                     headers={"X-Tavily-Access-Mode": "keyless"}) as client:
            with patch("web_router.routing.metered.estimated_cost", return_value=0.01), trace_providers(ledger):
                token = attempt_sink.set(tool)
                tool_token = attempt_tool_id.set("use-1")
                try:
                    stalled = asyncio.create_task(Leaf().asearch(SearchRequest(query="pending")))
                    await asyncio.wait_for(pending.wait(), 2)
                    await Leaf().asearch(SearchRequest(query="redirect"))
                    stalled.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await stalled
                finally:
                    attempt_tool_id.reset(tool_token)
                    attempt_sink.reset(token)
                with self.assertRaises(Exception):
                    await Leaf().asearch(SearchRequest(query="invalid"))

        self.assertEqual(len(ledger), 3)
        self.assertEqual(len(tool), 2)
        completed, cancelled, failed = ledger
        self.assertEqual([row["outcome"] for row in ledger], ["returned", "cancelled", "error"])
        self.assertTrue(all(row["estimated_cost_usd"] == 0.01 for row in ledger))
        self.assertEqual([row["http_dispatch_count"] for row in ledger], [2, 1, 0])
        self.assertEqual([row["reported_cost_usd"] for row in ledger], [0.003, None, None])
        self.assertEqual(completed["request_id"], "provider-id")
        self.assertEqual(completed["usage"], [{"usage.credits": 3}])
        self.assertFalse(completed["authenticated"])
        self.assertEqual([w["status_code"] for w in completed["http_sends"]], [307, 200])
        self.assertTrue(completed["http_sends"][1]["auth_query_present"])
        self.assertTrue(completed["http_sends"][0]["auth_body_present"])
        self.assertTrue(completed["http_sends"][0]["tavily_keyless"])
        self.assertEqual(completed["http_sends"][1]["usage"], {"usage.credits": 3})
        self.assertEqual(completed["http_sends"][1]["request_id"], "http-id")
        self.assertEqual(cancelled["http_sends"][0]["outcome"], "cancelled")
        self.assertIsNone(cancelled["http_sends"][0]["status_code"])
        self.assertEqual(failed["http_sends"], [])
        self.assertEqual(cancelled["tool_use_id"], "use-1")
        self.assertNotIn("secret", json.dumps(ledger))
        tool[0]["http_sends"][0]["status_code"] = 999
        self.assertEqual(completed["http_sends"][0]["status_code"], 307)
