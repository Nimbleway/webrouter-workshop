"""Run the wishlist task through Claude with one web toolkit or the other, under the same limits.

  uv run organizers/harness.py --web native                              # Claude's built-in search and fetch
  uv run organizers/harness.py --web webrouter                           # WebRouter search and extract, `auto`
  uv run organizers/harness.py --web webrouter --extract-provider max    # optional hedged extraction

Same model, same prompt, same wishlist items, same allowance per item (15 searches and
5 fetched URLs by default, failed requests included); only the web toolkit changes.
Each run writes a new directory under results/ with the offers, a manifest, per-item
details, metrics and attempts.json (every provider attempt, including failed and
cancelled ones), then prints the score. Needs ANTHROPIC_API_KEY. For organizers: a check
of the estimates attendees get from their call logs. Costs are estimates, not invoices.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # repo root: common.py, score.py

import argparse
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
import subprocess
import time
import uuid

import anthropic

from common import CONFIG, NATIVE_SEARCH_USD, RESULTS, llm_cost, parse_json_array, task_prompt, wishlist, write_results
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
    # No server-side fallback on purpose: both arms must be served by the model that was
    # requested, or the comparison is invalid (usage_row checks this).
    global client
    if client is None:
        client = anthropic.Anthropic()
    return client.beta.messages.create(model=model, max_tokens=16000, tools=tools,
                                       messages=messages, cache_control={"type": "ephemeral"},
                                       **({"container": container} if container else {}))


def initial_messages(item, searches, fetches, run_id=""):
    return [{"role": "user", "content": (
        f"Experiment session: {run_id}\n" + task_prompt(item) +
        f"\nUse at most {searches} searches and fetch at most {fetches} URLs total. "
        "Failed requests consume the allowance too. Never include progress notes or placeholders "
        "as offers. If a source doesn't show the price, the stock or the date, leave that offer out."
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


def run_native(item, model, max_searches=15, max_fetches=5, run_id=""):
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_fetches,
              "max_content_tokens": 4000}]
    messages = initial_messages(item, max_searches, max_fetches, run_id)
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
                 web_cost=searches * NATIVE_SEARCH_USD, trace=trace, unknown_cost_calls=0,
                 budget_exhausted=searches >= max_searches or fetches >= max_fetches)
    if searches > max_searches or fetches > max_fetches:
        out["status"] = "limit_exceeded"
    return out


def run_webrouter(item, model, tools_obj, tool_pool, max_searches=15, max_fetches=5, run_id=""):
    tools = tools_obj.definitions()
    messages = initial_messages(item, max_searches, max_fetches, run_id)
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
                                  "content": f"Request exceeds remaining allowance: {max_searches - searches} searches, {max_fetches - fetches} URLs. Submit a smaller request or return the supported offers already read."}
            else:
                admitted.append(use)
                searches += not is_extract
                fetches += count if is_extract else 0
        results, batch_cost, batch_trace = execute_batch(tools_obj, admitted, tool_pool)
        calls += len(admitted)
        web_cost += batch_cost
        unknown += sum(t["cost_usd"] is None for t in batch_trace)
        trace.extend({"item_id": item["item_id"], **row} for row in batch_trace)
        trace.extend({"item_id": item["item_id"], "tool": u.name, "tool_use_id": u.id, "input": u.input,
                      "is_error": True, "outcome": "allowance_denied", "provider_attempts": [],
                      "content": denied[u.id]["content"]} for u in uses if u.id in denied)
        mapped = {row["tool_use_id"]: row for row in results} | denied
        messages.append({"role": "user", "content": [mapped[u.id] for u in uses]})
    return finish(r, usage, model, web_calls=calls, searches=searches, fetched_urls=fetches,
                  web_cost=web_cost, trace=trace, unknown_cost_calls=unknown,
                  budget_exhausted=searches >= max_searches or fetches >= max_fetches)


KEYLESS_CREDENTIALS = ("NIMBLE_API_KEY", "NIMBLE_API_TOKEN", "TAVILY_API_KEY", "JINA_API_KEY",
                       "KEENABLE_API_KEY", "FIRECRAWL_API_KEY", "EXA_API_KEY", "YOU_API_KEY", "PARALLEL_API_KEY")


def provider_settings(profile):
    settings = {"max": {"hedge": EXTRACT_HEDGE_SECONDS}}
    if profile == "keyless":
        if any(os.environ.get(name) for name in KEYLESS_CREDENTIALS):
            raise ValueError("The keyless profile requires provider credentials to be absent")
        chain = {"search": [("nimble", {"allow_keyless": True}), ("tavily", {"allow_keyless": True}),
                            "you-mcp", "exa-mcp", "parallel-mcp", ("keenable", {"allow_keyless": True})],
                 "extract": [("nimble", {"allow_keyless": True}), ("tavily", {"allow_keyless": True}),
                             "jina", ("firecrawl", {"allow_keyless": True}), ("keenable", {"allow_keyless": True})]}
        settings["auto"] = {"chain": chain}
        settings["max"]["chain"] = chain
    return settings


def webrouter_tools(search_provider=None, extract_provider="auto", provider_profile="environment", recency="week"):
    from web_router import AsyncWebRouter
    from web_router.integrations.anthropic import WebRouterTools
    # Constrain before you search: a recency window that matches the 7-day price window, and
    # page text capped near native fetch's 4,000 tokens so one extract can't flood the context.
    return WebRouterTools(
        AsyncWebRouter(provider_config=provider_settings(provider_profile)),
        methods=("search", "extract"), max_results=5, recency=recency,
        provider=search_provider, extract_provider=extract_provider,
        result_chars=600, document_chars=16000, timeout=TOOL_TIMEOUT_SECONDS)


def git(*args):
    try:
        return subprocess.check_output(["git", *args], text=True, cwd=ROOT).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main():
    global client
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", choices=["native", "webrouter"], required=True)
    ap.add_argument("--limit", type=int, default=CONFIG.get("live_items", 5), help="only the first N wishlist items")
    ap.add_argument("--model", choices=["claude-opus-5-5", "claude-sonnet-5-5"], default=CONFIG["model"])
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--tool-workers", type=int, default=6)
    ap.add_argument("--max-searches", type=int, default=15)
    ap.add_argument("--max-fetches", type=int, default=5)
    ap.add_argument("--search-provider", default=None)
    ap.add_argument("--extract-provider", default="auto")
    ap.add_argument("--provider-profile", choices=["environment", "keyless"], default="environment")
    ap.add_argument("--recency", choices=["week", "none"], default="week",
                    help="recency filter on WebRouter searches (native search has none)")
    ap.add_argument("--output-dir", type=Path, default=RESULTS)
    args = ap.parse_args()
    if min(args.workers, args.tool_workers, args.limit, args.max_searches, args.max_fetches) < 1:
        ap.error("counts must be positive")
    if args.provider_profile == "keyless" and (args.search_provider not in {None, "auto"}
                                               or args.extract_provider not in {"auto", "max"}):
        ap.error("the keyless profile requires auto search and auto or max extraction")
    settings = provider_settings(args.provider_profile)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    outdir = args.output_dir / run_id
    outdir.mkdir(parents=True, exist_ok=False)
    client = anthropic.Anthropic()
    rows_in = wishlist()[:args.limit]
    status = git("status", "--porcelain")
    manifest = {**vars(args), "output_dir": str(args.output_dir), "run_id": run_id,
                "items": [c["item_id"] for c in rows_in], "config": CONFIG,
                "versions": {p: importlib.metadata.version(p) for p in ("webrouter", "anthropic")},
                "fallbacks": "disabled", "cache": "5-minute; unique session prefix per run",
                "content_limits": {"native_tokens": 4000, "webrouter_chars": 16000},
                "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted([*ROOT.glob("*.py"), *Path(__file__).parent.glob("*.py")])},
                "git_dirty": None if status is None else bool(status),
                "git_commit": git("rev-parse", "HEAD")}
    from web_router.providers.auto import AutoProvider, AutoExtractProvider
    from web_router.registry import configured_providers, configured_extract_providers
    manifest["provider_environment"] = {"configured_search": list(configured_providers()),
                                        "configured_extract": list(configured_extract_providers()),
                                        "credential_present": {name: bool(os.environ.get(name)) for name in KEYLESS_CREDENTIALS},
                                        "explicit_settings": settings,
                                        "auto_search_chain": AutoProvider(**settings.get("auto", {})).members,
                                        "auto_extract_chain": AutoExtractProvider(**settings.get("auto", {})).members}
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    recency = None if args.recency == "none" else args.recency
    tools = (webrouter_tools(args.search_provider, args.extract_provider, args.provider_profile, recency)
             if args.web == "webrouter" else None)

    def one(c):
        started = time.perf_counter()
        partial_usage, partial_trace = [], []
        capture_token = usage_capture.set(partial_usage)
        trace_token = trace_capture.set(partial_trace)
        try:
            options = (args.max_searches, args.max_fetches, run_id)
            out = (run_native(c, args.model, *options) if tools is None else
                   run_webrouter(c, args.model, tools, pool, *options))
        except Exception as exc:
            out = {"rows": [], "status": "failed", "error_type": type(exc).__name__,
                   "model_usage": partial_usage, "trace": partial_trace, "cost_complete": False,
                   "in": sum(u["input"] + u["cache_read"] + u["cache_write"] for u in partial_usage),
                   "out": sum(u["output"] for u in partial_usage),
                   "web_calls": (sum(u["searches"] + u["fetches"] for u in partial_usage) if tools is None
                                 else sum(t.get("outcome") != "allowance_denied" for t in partial_trace))}
        finally:
            usage_capture.reset(capture_token)
            trace_capture.reset(trace_token)
        out.update(item_id=c["item_id"], item=c["item"], seconds=round(time.perf_counter() - started, 4))
        for row in out["rows"]:
            row["item_id"] = c["item_id"]
        print(f"  #{c['item_id']} {c['item']}: {out['status']}, {len(out['rows'])} offers", flush=True)
        return out

    print(f"Running {len(rows_in)} wishlist items with {args.web} web tools on {args.model} ...", flush=True)
    run_ledger = []
    started = time.perf_counter()
    with trace_providers(run_ledger=run_ledger):
        try:
            with ThreadPoolExecutor(args.tool_workers) as pool, ThreadPoolExecutor(args.workers) as workers:
                outputs = list(workers.map(one, rows_in))
            elapsed = round(time.perf_counter() - started, 2)
        finally:
            try:
                if tools is not None:
                    # Await race cleanup on the sync adapter's owning loop before freezing the ledger.
                    from web_router.routing._runner import _on_private_loop
                    _on_private_loop(tools.router.aclose()).result()
            finally:
                client.close()
                (outdir / "attempts.json").write_text(json.dumps(run_ledger, indent=2))
    model_cost = sum(o.get("model_cost_usd", 0) for o in outputs)
    web_cost = sum(o.get("web_cost", 0) for o in outputs)
    complete = all(o["status"] == "complete" for o in outputs)
    metrics = {"seconds": elapsed, "complete": complete,
               "model": args.model, "model_cost_usd": round(model_cost, 6) if complete else None,
               "provider_returned_estimate_usd": round(web_cost, 6) if complete else None,
               "cost_usd": round(model_cost + web_cost, 6) if tools is None and complete else None,
               "cost_note": ("WebRouter returned-provider estimates omit unpriced and losing attempts; total unknown."
                             if tools is not None else "Model and native search estimates; not an invoice."),
               "unknown_cost_calls": sum(o.get("unknown_cost_calls", 0) for o in outputs),
               "input_tokens": sum(o.get("in", 0) for o in outputs),
               "output_tokens": sum(o.get("out", 0) for o in outputs),
               "web_calls": sum(o.get("web_calls", 0) for o in outputs),
               "items": [o["item_id"] for o in outputs]}
    path = outdir / f"harness_{args.web}.csv"
    write_results(path, [r for o in outputs for r in o["rows"]])
    path.with_suffix(".metrics.json").write_text(json.dumps(metrics, indent=2))
    path.with_suffix(".details.json").write_text(json.dumps(outputs, indent=2))
    print(f"Artifacts: {outdir}", flush=True)
    show(score(path, len(rows_in)))
    if not complete:
        raise SystemExit("Incomplete comparison: inspect per-item status; do not use as a successful run")


if __name__ == "__main__":
    main()
