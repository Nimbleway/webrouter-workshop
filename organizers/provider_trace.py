"""Observe leaf calls and HTTPX transport attempts without collecting requests or response bodies."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import math
import re
import time
from unittest.mock import patch

import httpx

attempt_sink = ContextVar("workshop_attempt_sink", default=None)
attempt_tool_id = ContextVar("workshop_attempt_tool_id", default=None)
_active_http = ContextVar("workshop_active_http", default=None)
_send_responses = ContextVar("workshop_send_responses", default=None)

# Fixed public service hosts prevent a private endpoint or customer subdomain entering the trace.
_PUBLIC_HOSTS = frozenset({
    "api.tavily.com", "sdk.nimbleway.com", "api.keenable.ai", "api.firecrawl.dev",
    "r.jina.ai", "s.jina.ai", "api.you.com", "ydc-index.io", "mcp.exa.ai",
    "api.exa.ai", "api.parallel.ai", "search.parallel.ai",
})
_REQUEST_ID_HEADERS = ("x-request-id", "request-id", "x-correlation-id")
_AUTH_HEADERS = ("authorization", "x-api-key", "api-key", "x-subscription-token")
_USAGE_PATHS = (
    ("credits",), ("creditsUsed",), ("credits_used",), ("billed_units",),
    ("usage", "credits"), ("usage", "credits_used"), ("usage", "tokens"),
    ("usage", "total_tokens"), ("usage", "input_tokens"), ("usage", "output_tokens"),
    ("usage", "billed_units"), ("billed_units", "search_units"),
    ("data", "usage", "tokens"), ("data", "metadata", "creditsUsed"),
    ("metadata", "proxy_total_bytes_usage"),
)
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


def _request_id(value):
    return value if isinstance(value, str) and _ID_PATTERN.fullmatch(value) else None


def _has_auth_field(keys):
    auth_names = {"key", "apikey", "exaapikey", "accesskey", "token", "accesstoken", "authorization"}
    return any(key.lower().replace("_", "").replace("-", "") in auth_names for key in keys)


def _body_auth(request):
    # The keyless Tavily SDK historically also accepted api_key in JSON. Inspect names only.
    if "json" not in request.headers.get("content-type", "").lower():
        return False if request.method in {"GET", "HEAD"} else None
    try:
        if len(request.content) > 1_048_576:
            return None
        data = json.loads(request.content)
    except (httpx.RequestNotRead, ValueError, RecursionError):
        return None
    return _has_auth_field(data) if isinstance(data, dict) else None


def _usage(payload):
    result = {}
    for path in _USAGE_PATHS:
        value = payload
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        valid_integer = type(value) is int and 0 <= value <= 2**63 - 1
        valid_float = type(value) is float and math.isfinite(value) and value >= 0
        if valid_integer or valid_float:
            result[".".join(path)] = value
    return result


def _read_usage(response):
    # HTTPX may stream the body. Never read it for the observer or parse arbitrarily large documents.
    if "json" not in response.headers.get("content-type", "").lower():
        return {}
    try:
        if len(response.content) <= 1_048_576:
            return _usage(response.json())
    except (httpx.ResponseNotRead, ValueError, RecursionError):
        pass
    return {}


@contextmanager
def trace_providers(run_ledger=None):
    """Publish detached final leaf rows. Consume the run ledger after router teardown."""
    from web_router.providers.base import ExtractProvider, SearchProvider
    from web_router.routing.metered import estimated_cost

    send = httpx.AsyncClient.send
    single_request = httpx.AsyncClient._send_single_request

    async def observe_send(client, request, **kwargs):
        if _active_http.get() is None:
            return await send(client, request, **kwargs)
        responses = {}
        token = _send_responses.set(responses)
        try:
            response = await send(client, request, **kwargs)
            if response in responses:
                responses[response]["usage"] = _read_usage(response)
            return response
        finally:
            _send_responses.reset(token)

    async def observe_exchange(client, request):
        exchanges = _active_http.get()
        if exchanges is None:
            return await single_request(client, request)
        host = request.url.host
        wire = {
            "host": host if host in _PUBLIC_HOSTS else None,
            "auth_header_present": any(key in request.headers for key in _AUTH_HEADERS),
            "auth_query_present": _has_auth_field(request.url.params.keys()),
            "auth_body_present": _body_auth(request),
            "tavily_keyless": (request.headers.get("x-tavily-access-mode") == "keyless"
                               if host == "api.tavily.com" else None),
            "keenable_public": (request.url.path in {"/v1/search/public", "/v1/fetch/public"}
                                if host == "api.keenable.ai" else None),
            "status_code": None, "request_id": None, "usage": {}, "outcome": "started",
        }
        exchanges.append(wire)
        try:
            response = await single_request(client, request)
            wire.update(status_code=response.status_code, outcome="response_headers")
            for name in _REQUEST_ID_HEADERS:
                request_id = _request_id(response.headers.get(name))
                if request_id:
                    wire["request_id"] = request_id
                    break
            responses = _send_responses.get()
            if responses is not None:
                responses[response] = wire
            return response
        except asyncio.CancelledError:
            wire["outcome"] = "cancelled"
            raise
        except Exception as exc:
            wire.update(outcome="error", error_type=type(exc).__name__)
            raise

    def instrument(original, method):
        async def call(self, request):
            sink = attempt_sink.get()
            if (sink is None and run_ledger is None) or self.name in {"auto", "max"}:
                return await original(self, request)
            started = time.perf_counter()
            http_sends = []
            token = _active_http.set(http_sends)
            row = {
                "provider": self.name, "method": method, "tool_use_id": attempt_tool_id.get(),
                "requested_urls": len(getattr(request, "urls", [])),
                "authenticated": bool(getattr(self, "holds_credential", self.api_key is not None)),
                "estimated_cost_usd": None, "reported_cost_usd": None, "request_id": None,
                "usage": [], "cost_usd": None, "cost_source": None, "http_sends": http_sends,
            }
            try:
                try:
                    row["estimated_cost_usd"] = estimated_cost(method, self.name, request)
                except Exception as exc:
                    # Observability must not prevent dispatch if the catalogue cannot price a request.
                    row["estimate_error_type"] = type(exc).__name__
                response = await original(self, request)
                row.update(outcome="returned", cost_usd=response.cost_usd,
                           cost_source=getattr(response, "cost_source", None),
                           request_id=_request_id(getattr(response, "request_id", None)))
                if row["cost_source"] == "reported":
                    row["reported_cost_usd"] = response.cost_usd
                raw = getattr(response, "raw", None)
                for item in raw if isinstance(raw, list) else [raw]:
                    usage = _usage(item)
                    if usage:
                        row["usage"].append(usage)
                return response
            except asyncio.CancelledError:
                row["outcome"] = "cancelled"
                raise
            except Exception as exc:
                row.update(outcome="error", error_type=type(exc).__name__)
                raise
            finally:
                _active_http.reset(token)
                row["seconds"] = round(time.perf_counter() - started, 4)
                row["http_dispatch_count"] = len(http_sends)
                # A task inheriting this context cannot subsequently mutate the published snapshots.
                if sink is not None:
                    sink.append(deepcopy(row))
                if run_ledger is not None and run_ledger is not sink:
                    run_ledger.append(deepcopy(row))
        return call

    with patch.object(httpx.AsyncClient, "send", observe_send), \
         patch.object(httpx.AsyncClient, "_send_single_request", observe_exchange), \
         patch.object(SearchProvider, "asearch", instrument(SearchProvider.asearch, "search")), \
         patch.object(ExtractProvider, "aextract", instrument(ExtractProvider.aextract, "extract")):
        yield
