"""Run independent tool requests concurrently and preserve their result order."""
from __future__ import annotations

import time
from concurrent.futures import Executor


def execute_batch(tools, uses: list, pool: Executor) -> tuple[list, float, list]:
    def execute(use):
        started = time.perf_counter()
        result = tools.call(use.name, use.input)
        response = result.response
        urls = use.input.get("urls") if isinstance(use.input, dict) else None
        trace = {
            "tool": use.name,
            "tool_use_id": use.id,
            "seconds": round(time.perf_counter() - started, 4),
            "provider": getattr(response, "provider", None),
            "result_chars": len(result.content),
            "is_error": result.is_error,
            "requested_urls": len(urls) if isinstance(urls, list) else 0,
            "documents": len(getattr(response, "documents", [])),
            "failed_urls": (len(getattr(response, "failures", [])) if response is not None
                            else len(urls) if result.is_error and isinstance(urls, list) else 0),
        }
        return use, result, trace

    results, traces = [], []
    cost = 0.0
    for use, result, trace in pool.map(execute, uses):
        cost += getattr(result.response, "cost_usd", None) or 0.0
        results.append({"type": "tool_result", "tool_use_id": use.id,
                        "content": result.content, "is_error": result.is_error})
        traces.append(trace)
    return results, cost, traces
