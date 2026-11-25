"""Run the launch task through Claude with one web tool or the other, and measure it.

  uv run harness.py --web native      # Claude's built-in web search
  uv run harness.py --web webrouter   # the open source WebRouter's search and extract

Same model, same prompt, same companies; only the web tool changes. Writes
results/harness_<web>.csv and .metrics.json (time, tokens, web calls, cost),
then prints the score. Needs ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic

from common import CONFIG, NATIVE_SEARCH_USD, RESULTS, companies, llm_cost, parse_json_array, task_prompt, write_results
from score import score, show
from tool_batch import execute_batch

client = anthropic.Anthropic()
BETAS = ["server-side-fallback-2026-07-01"]
EXTRACT_HEDGE_SECONDS = 2.0
TOOL_TIMEOUT_SECONDS = 20.0


def ask(model: str, messages: list, tools: list) -> anthropic.types.beta.BetaMessage:
    return client.beta.messages.create(
        model=model,
        max_tokens=16000,
        tools=tools,
        messages=messages,
        betas=BETAS,
        fallbacks="default",
        cache_control={"type": "ephemeral"},
    )


def run_native(company: str, model: str) -> dict:
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 15}]
    messages = [{"role": "user", "content": task_prompt(company)}]
    tok_in = tok_out = searches = 0
    cache_read = cache_write = 0
    while True:
        r = ask(model, messages, tools)
        tok_in += r.usage.input_tokens
        cache_read += r.usage.cache_read_input_tokens or 0
        cache_write += r.usage.cache_creation_input_tokens or 0
        tok_out += r.usage.output_tokens
        if r.usage.server_tool_use:
            searches += r.usage.server_tool_use.web_search_requests or 0
        if r.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": r.content})
            continue
        break
    text = "".join(b.text for b in r.content if b.type == "text")
    return {"rows": parse_json_array(text), "in": tok_in + cache_read + cache_write, "out": tok_out,
            "cache_read": cache_read, "cache_write": cache_write, "web_calls": searches,
            "web_cost": searches * NATIVE_SEARCH_USD, "stop": r.stop_reason}


def run_webrouter(company: str, model: str, tools_obj, tool_pool) -> dict:
    tools = tools_obj.definitions()
    messages = [{"role": "user", "content": task_prompt(company)}]
    tok_in = tok_out = calls = 0
    cache_read = cache_write = 0
    web_cost = 0.0
    trace = []
    while True:
        r = ask(model, messages, tools)
        tok_in += r.usage.input_tokens
        cache_read += r.usage.cache_read_input_tokens or 0
        cache_write += r.usage.cache_creation_input_tokens or 0
        tok_out += r.usage.output_tokens
        uses = [b for b in r.content if b.type == "tool_use"]
        if r.stop_reason != "tool_use" or not uses:
            break
        messages.append({"role": "assistant", "content": r.content})
        results, batch_cost, batch_trace = execute_batch(tools_obj, uses, tool_pool)
        calls += len(uses)
        web_cost += batch_cost
        trace.extend({"company": company, **row} for row in batch_trace)
        messages.append({"role": "user", "content": results})
    text = "".join(b.text for b in r.content if b.type == "text")
    return {"rows": parse_json_array(text), "in": tok_in + cache_read + cache_write, "out": tok_out,
            "cache_read": cache_read, "cache_write": cache_write, "web_calls": calls,
            "web_cost": web_cost, "stop": r.stop_reason, "trace": trace}


def webrouter_tools(search_provider=None, extract_provider="max"):
    from web_router import AsyncWebRouter
    from web_router.integrations.anthropic import WebRouterTools

    # The adapter accepts sync calls, while the async router fetches URLs
    # within each extract batch concurrently rather than one at a time.
    return WebRouterTools(
        AsyncWebRouter(provider_config={"max": {"hedge": EXTRACT_HEDGE_SECONDS}}),
        methods=("search", "extract"), max_results=5,
        provider=search_provider, extract_provider=extract_provider,
        result_chars=600, document_chars=4000, timeout=TOOL_TIMEOUT_SECONDS,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", choices=["native", "webrouter"], required=True)
    ap.add_argument("--limit", type=int, default=None, help="only the first N companies")
    ap.add_argument("--model", default=CONFIG["model"])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--tool-workers", type=int, default=6, help="maximum concurrent WebRouter calls across companies")
    ap.add_argument("--search-provider", default=None, help="explicit search backend, e.g. exa-mcp; default: auto")
    ap.add_argument("--extract-provider", default="max", help="extract backend; default: max with a two-second hedge")
    args = ap.parse_args()
    if args.workers < 1 or args.tool_workers < 1:
        ap.error("worker counts must be positive")

    rows_in = companies()[: args.limit]
    tools_obj = None
    if args.web == "webrouter":
        tools_obj = webrouter_tools(args.search_provider, args.extract_provider)

    def one(c: dict) -> dict:
        try:
            if args.web == "native":
                out = run_native(c["company"], args.model)
            else:
                out = run_webrouter(c["company"], args.model, tools_obj, tool_pool)
        except anthropic.APIError as e:
            print(f"  {c['company']}: API error, skipped ({e.__class__.__name__})")
            return {"rows": [], "in": 0, "out": 0, "web_calls": 0, "web_cost": 0.0}
        for r in out["rows"]:
            r["company"] = c["company"]
        print(f"  {c['company']}: {len(out['rows'])} launches, {out['web_calls']} web calls")
        return out

    print(f"Running {len(rows_in)} companies with {args.web} web tools on {args.model} ...")
    t0 = time.time()
    with ThreadPoolExecutor(args.tool_workers) as tool_pool, ThreadPoolExecutor(args.workers) as pool:
        outs = list(pool.map(one, rows_in))
    seconds = round(time.time() - t0, 1)

    tok_in = sum(o["in"] for o in outs)
    tok_out = sum(o["out"] for o in outs)
    cache_read = sum(o.get("cache_read", 0) for o in outs)
    cache_write = sum(o.get("cache_write", 0) for o in outs)
    web_cost = sum(o["web_cost"] for o in outs)
    metrics = {
        "seconds": seconds,
        "input_tokens": tok_in,
        "output_tokens": tok_out,
        "uncached_input_tokens": tok_in - cache_read - cache_write,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write,
        "web_calls": sum(o["web_calls"] for o in outs),
        "cost_usd": round(llm_cost(args.model, tok_in - cache_read - cache_write, tok_out,
                                   cache_read=cache_read, cache_write=cache_write) + web_cost, 4),
        "web_cost_usd": round(web_cost, 4),
        "model": args.model,
        "search_provider": args.search_provider or "auto",
        "tool_workers": args.tool_workers,
        "extract_provider": (args.extract_provider or "auto") if args.web == "webrouter" else None,
        "extraction_mode": "async" if args.web == "webrouter" else None,
        "tool_timeout_s": TOOL_TIMEOUT_SECONDS if args.web == "webrouter" else None,
        "extract_hedge_s": EXTRACT_HEDGE_SECONDS if args.web == "webrouter" and args.extract_provider == "max" else None,
    }
    path = RESULTS / f"harness_{args.web}.csv"
    write_results(path, [r for o in outs for r in o["rows"]])
    path.with_suffix(".metrics.json").write_text(json.dumps(metrics, indent=2))
    if args.web == "webrouter":
        path.with_suffix(".trace.jsonl").write_text("".join(
            json.dumps(row) + "\n" for out in outs for row in out.get("trace", [])
        ))
    show(score(path))


if __name__ == "__main__":
    main()
