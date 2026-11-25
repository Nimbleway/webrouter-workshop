"""Record provider attempts, including cancelled race members, without logging credentials."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import time
from unittest.mock import patch

attempt_sink = ContextVar("workshop_attempt_sink", default=None)


@contextmanager
def trace_providers():
    from web_router.providers.base import ExtractProvider, SearchProvider

    def instrument(original, method):
        async def call(self, request):
            sink = attempt_sink.get()
            if sink is None or self.name in {"auto", "max"}:
                return await original(self, request)
            row = {"provider": self.name, "method": method, "outcome": "started",
                   "requested_urls": len(getattr(request, "urls", [])),
                   "cost_usd": None, "cost_source": None}
            sink.append(row)
            started = time.perf_counter()
            try:
                response = await original(self, request)
                row.update(outcome="returned", cost_usd=response.cost_usd,
                           cost_source=getattr(response, "cost_source", None))
                return response
            except asyncio.CancelledError:
                row["outcome"] = "cancelled"
                raise
            except Exception as exc:
                row.update(outcome="error", error_type=type(exc).__name__)
                raise
            finally:
                row["seconds"] = round(time.perf_counter() - started, 4)
        return call

    with patch.object(SearchProvider, "asearch", instrument(SearchProvider.asearch, "search")), \
         patch.object(ExtractProvider, "aextract", instrument(ExtractProvider.aextract, "extract")):
        yield
