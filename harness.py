"""Compare native search/fetch with WebRouter under explicit retrieval limits."""
from __future__ import annotations

import argparse
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time
import uuid

import anthropic

from common import CONFIG, RESULTS, companies, llm_cost, parse_json_array, task_prompt, write_results
from provider_trace import trace_providers
from score import score, show
from tool_batch import execute_batch

client = None
EXTRACT_HEDGE_SECONDS = 2.0
TOOL_TIMEOUT_SECONDS = 20.0
MAX_TURNS = 20
usage_capture = ContextVar("usage_capture", default=None)
trace_capture = ContextVar("trace_capture", default=None)


def ask(model, messages, tools, *, container=None):
    global client
    if client is None:
        client = anthropic.Anthropic()
    return client.beta.messages.create(model=model, max_tokens=16000, tools=tools,
                                       messages=messages, cache_control={"type": "ephemeral"},
                                       **({"container": container} if container else {}))


def initial_messages(company, searches, fetches, run_id=""):
    return [{"role": "user", "content": (
        f"Experiment session: {run_id}\n" + task_prompt(company) +
        f"\nUse at most {searches} searches and fetch at most {fetches} URLs total. "
        "Failed requests consume the allowance too. Never include progress notes or incomplete-list "
        "placeholders as records. If a date or quotation is not supported, omit that record."
    )}]


def usage_row(r, model):
    serving = getattr(r, "model", model)
    u = r.usage
    iterations = getattr(u, "iterations", None) or []
    row = {"model": serving, "stop": r.stop_reason, "input": u.input_tokens, "output": u.output_tokens,
           "cache_read": u.cache_read_input_tokens or 0, "cache_write": u.cache_creation_input_tokens or 0,
           "request_id": getattr(r, "_request_id", None),
           "iterations": [i.model_dump(mode="json") for i in iterations],
           "searches": getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0,
           "fetches": getattr(getattr(u, "server_tool_use", None), "web_fetch_requests", 0) or 0}
    sink = usage_capture.get()
    if sink is not None:
        sink.append(row)
    if serving != model or any(getattr(i, "type", None) == "fallback_message" for i in iterations):
        raise ValueError("Unexpected serving model or fallback attempts; comparison invalid")
    return row


def finish(r, usage, model, **extra):
    text = "".join(b.text for b in r.content if b.type == "text") if r else ""
    try:
        rows = parse_json_array(text, strict=True)
        status = "complete" if r.stop_reason == "end_turn" else "incomplete"
    except ValueError:
        rows, status = [], "invalid_json"
    uncached = sum(u["input"] for u in usage)
    reads, writes = (sum(u[key] for u in usage) for key in ("cache_read", "cache_write"))
    output = sum(u["output"] for u in usage)
    return {"rows": rows, "status": status, "in": uncached + reads + writes, "out": output,
            "cache_read": reads, "cache_write": writes, "model_usage": usage,
            "model_cost_usd": llm_cost(model, uncached, output, cache_read=reads, cache_write=writes), **extra}


def run_native(company, model, max_searches=15, max_fetches=5, run_id=""):
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_fetches,
              "max_content_tokens": 4000}]
    messages = initial_messages(company, max_searches, max_fetches, run_id)
    usage = []
    trace = trace_capture.get()
    if trace is None:
        trace = []
    searches = fetches = 0
    r = None
    container = None
    for _ in range(MAX_TURNS):
        r = ask(model, messages, tools, **({"container": container} if container else {}))
        container = getattr(getattr(r, "container", None), "id", None)
        usage.append(usage_row(r, model))
        server = getattr(r.usage, "server_tool_use", None)
        searches += getattr(server, "web_search_requests", 0) or 0
        fetches += getattr(server, "web_fetch_requests", 0) or 0
        trace.extend(b.model_dump(mode="json") for b in r.content if hasattr(b, "model_dump"))
        if r.stop_reason != "pause_turn" or searches > max_searches or fetches > max_fetches:
            break
        messages.append({"role": "assistant", "content": r.content})
    out = finish(r, usage, model, web_calls=searches + fetches, searches=searches, fetched_urls=fetches,
                 web_cost=searches * 0.01, trace=trace, unknown_cost_calls=0,
                 budget_exhausted=searches >= max_searches or fetches >= max_fetches)
    if searches > max_searches or fetches > max_fetches:
        out["status"] = "limit_exceeded"
    return out


def run_webrouter(company, model, tools_obj, tool_pool, max_searches=15, max_fetches=5, run_id=""):
    tools = tools_obj.definitions()
    messages = initial_messages(company, max_searches, max_fetches, run_id)
    usage = []
    trace = trace_capture.get()
    if trace is None:
        trace = []
    calls = searches = fetches = unknown = 0
    web_cost = 0.0
    r = None
    for _ in range(MAX_TURNS):
        r = ask(model, messages, tools)
        usage.append(usage_row(r, model))
        uses = [b for b in r.content if b.type == "tool_use"]
        if r.stop_reason != "tool_use" or not uses:
            break
        messages.append({"role": "assistant", "content": r.content})
        admitted, denied = [], {}
        for use in uses:
            is_extract = use.name.endswith("extract")
            urls = use.input.get("urls", []) if isinstance(use.input, dict) else []
            count = len(urls) if isinstance(urls, list) else 1
            if (is_extract and fetches + count > max_fetches) or (not is_extract and searches >= max_searches):
                denied[use.id] = {"type": "tool_result", "tool_use_id": use.id, "is_error": True,
                                  "content": f"Request exceeds remaining allowance: {max_searches - searches} searches, {max_fetches - fetches} URLs. Submit a smaller request or return supported records already read."}
            else:
                admitted.append(use)
                searches += not is_extract
                fetches += count if is_extract else 0
        results, batch_cost, batch_trace = execute_batch(tools_obj, admitted, tool_pool)
        calls += len(admitted)
        web_cost += batch_cost
        unknown += sum(t["cost_usd"] is None for t in batch_trace)
        trace.extend({"company": company, **row} for row in batch_trace)
        trace.extend({"company": company, "tool": u.name, "tool_use_id": u.id, "input": u.input,
                      "is_error": True, "outcome": "allowance_denied", "provider_attempts": [],
                      "content": denied[u.id]["content"]} for u in uses if u.id in denied)
        mapped = {row["tool_use_id"]: row for row in results} | denied
        messages.append({"role": "user", "content": [mapped[u.id] for u in uses]})
    return finish(r, usage, model, web_calls=calls, searches=searches, fetched_urls=fetches,
                  web_cost=web_cost, trace=trace, unknown_cost_calls=unknown,
                  budget_exhausted=searches >= max_searches or fetches >= max_fetches)


def webrouter_tools(search_provider=None, extract_provider="auto"):
    from web_router import AsyncWebRouter
    from web_router.integrations.anthropic import WebRouterTools
    return WebRouterTools(
        AsyncWebRouter(provider_config={"max": {"hedge": EXTRACT_HEDGE_SECONDS}}),
        methods=("search", "extract"), max_results=5,
        provider=search_provider, extract_provider=extract_provider,
        result_chars=600, document_chars=16000, timeout=TOOL_TIMEOUT_SECONDS)


def main():
    global client
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", choices=["native", "webrouter"], required=True)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--model", choices=["claude-opus-5-5", "claude-sonnet-5-5"], default=CONFIG["model"])
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--tool-workers", type=int, default=6)
    ap.add_argument("--max-searches", type=int, default=15)
    ap.add_argument("--max-fetches", type=int, default=5)
    ap.add_argument("--search-provider", default=None)
    ap.add_argument("--extract-provider", default="auto")
    ap.add_argument("--output-dir", type=Path, default=RESULTS)
    args = ap.parse_args()
    if min(args.workers, args.tool_workers, args.limit, args.max_searches, args.max_fetches) < 1:
        ap.error("counts must be positive")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    outdir = args.output_dir / run_id
    outdir.mkdir(parents=True, exist_ok=False)
    client = anthropic.Anthropic()
    rows_in = companies()[:args.limit]
    manifest = {**vars(args), "output_dir": str(args.output_dir), "run_id": run_id,
                "companies": [c['company'] for c in rows_in], "config": CONFIG,
                "versions": {p: importlib.metadata.version(p) for p in ('webrouter', 'anthropic')},
                "fallbacks": "disabled", "cache": "5-minute; unique session prefix per run",
                "content_limits": {"native_tokens": 4000, "webrouter_chars": 16000},
                "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in Path(__file__).parent.glob('*.py')},
                "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
                "git_commit": subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()}
    from web_router.providers.auto import AutoProvider, AutoExtractProvider
    from web_router.registry import configured_providers, configured_extract_providers
    manifest['provider_environment'] = {'configured_search': list(configured_providers()),
                                        'configured_extract': list(configured_extract_providers()),
                                        'auto_search_chain': AutoProvider().members,
                                        'auto_extract_chain': AutoExtractProvider().members}
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    tools = webrouter_tools(args.search_provider, args.extract_provider) if args.web == "webrouter" else None

    def one(c):
        started = time.perf_counter()
        partial_usage, partial_trace = [], []
        capture_token = usage_capture.set(partial_usage)
        trace_token = trace_capture.set(partial_trace)
        try:
            options = (args.max_searches, args.max_fetches, run_id)
            out = (run_native(c['company'], args.model, *options) if tools is None else
                   run_webrouter(c['company'], args.model, tools, pool, *options))
        except Exception as exc:
            out = {"rows": [], "status": "failed", "error_type": type(exc).__name__,
                   "model_usage": partial_usage, "trace": partial_trace, "cost_complete": False,
                   "in": sum(u['input'] + u['cache_read'] + u['cache_write'] for u in partial_usage),
                   "out": sum(u['output'] for u in partial_usage),
                   "web_calls": (sum(u['searches'] + u['fetches'] for u in partial_usage) if tools is None
                                 else sum(t.get('outcome') != 'allowance_denied' for t in partial_trace))}
        finally:
            usage_capture.reset(capture_token)
            trace_capture.reset(trace_token)
        out.update(company=c['company'], seconds=round(time.perf_counter() - started, 4))
        for row in out['rows']:
            row['company'] = c['company']
        print(f"  {c['company']}: {out['status']}, {len(out['rows'])} records", flush=True)
        return out

    started = time.perf_counter()
    with trace_providers(), ThreadPoolExecutor(args.tool_workers) as pool, ThreadPoolExecutor(args.workers) as workers:
        outputs = list(workers.map(one, rows_in))
    elapsed = round(time.perf_counter() - started, 2)
    if tools is not None:
        # The sync adapter owns an event loop; close its router on that same loop.
        from web_router.routing._runner import _on_private_loop
        _on_private_loop(tools.router.aclose()).result()
    client.close()
    model_cost = sum(o.get('model_cost_usd', 0) for o in outputs)
    web_cost = sum(o.get('web_cost', 0) for o in outputs)
    complete = all(o['status'] == 'complete' for o in outputs)
    metrics = {"seconds": elapsed, "complete": complete,
               "model": args.model, "model_cost_usd": round(model_cost, 6) if complete else None,
               "provider_returned_estimate_usd": round(web_cost, 6) if complete else None,
               "cost_usd": round(model_cost + web_cost, 6) if tools is None and complete else None,
               "cost_note": ("WebRouter returned-provider estimates omit unpriced and losing attempts; total unknown."
                             if tools is not None else "Model and native search estimates; not an invoice."),
               "unknown_cost_calls": sum(o.get('unknown_cost_calls', 0) for o in outputs),
               "input_tokens": sum(o.get('in', 0) for o in outputs),
               "output_tokens": sum(o.get('out', 0) for o in outputs),
               "web_calls": sum(o.get('web_calls', 0) for o in outputs),
               "companies": [o['company'] for o in outputs]}
    path = outdir / f"harness_{args.web}.csv"
    write_results(path, [r for o in outputs for r in o['rows']])
    path.with_suffix('.metrics.json').write_text(json.dumps(metrics, indent=2))
    path.with_suffix('.details.json').write_text(json.dumps(outputs, indent=2))
    print(f"Artifacts: {outdir}", flush=True)
    show(score(path))
    if not complete:
        raise SystemExit("Incomplete comparison: inspect per-company status; do not use as a successful run")


if __name__ == '__main__':
    main()
