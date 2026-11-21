"""Run the launch task through Claude with one web tool or the other, and measure it.

  uv run organizers/harness.py --web native      # Claude's built-in web search
  uv run organizers/harness.py --web webrouter   # the open source WebRouter's search and extract

Same model, same prompt, same companies; only the web tool changes. Writes
results/harness_<web>.csv and .metrics.json (time, tokens, web calls, cost),
then prints the score. Needs ANTHROPIC_API_KEY. Optional, for organizers: a
check of the estimates attendees get from their call logs, with exact API usage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root: common.py, score.py

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic

from common import CONFIG, NATIVE_SEARCH_USD, RESULTS, companies, llm_cost, parse_json_array, task_prompt, write_results
from score import score, show

client = anthropic.Anthropic()
BETAS = ["server-side-fallback-2026-07-01"]


def ask(model: str, messages: list, tools: list) -> anthropic.types.beta.BetaMessage:
    return client.beta.messages.create(
        model=model,
        max_tokens=16000,
        tools=tools,
        messages=messages,
        betas=BETAS,
        fallbacks="default",
    )


def run_native(company: str, model: str) -> dict:
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 15}]
    messages = [{"role": "user", "content": task_prompt(company)}]
    tok_in = tok_out = searches = 0
    while True:
        r = ask(model, messages, tools)
        tok_in += r.usage.input_tokens + (r.usage.cache_read_input_tokens or 0) + (r.usage.cache_creation_input_tokens or 0)
        tok_out += r.usage.output_tokens
        if r.usage.server_tool_use:
            searches += r.usage.server_tool_use.web_search_requests or 0
        if r.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": r.content})
            continue
        break
    text = "".join(b.text for b in r.content if b.type == "text")
    return {"rows": parse_json_array(text), "in": tok_in, "out": tok_out, "web_calls": searches,
            "web_cost": searches * NATIVE_SEARCH_USD, "stop": r.stop_reason}


def run_webrouter(company: str, model: str, tools_obj) -> dict:
    tools = tools_obj.definitions()
    messages = [{"role": "user", "content": task_prompt(company)}]
    tok_in = tok_out = calls = 0
    web_cost = 0.0
    while True:
        r = ask(model, messages, tools)
        tok_in += r.usage.input_tokens + (r.usage.cache_read_input_tokens or 0) + (r.usage.cache_creation_input_tokens or 0)
        tok_out += r.usage.output_tokens
        uses = [b for b in r.content if b.type == "tool_use"]
        if r.stop_reason != "tool_use" or not uses:
            break
        messages.append({"role": "assistant", "content": r.content})
        results = []
        for u in uses:
            res = tools_obj.call(u.name, u.input)
            calls += 1
            if res.response is not None and getattr(res.response, "cost_usd", None):
                web_cost += res.response.cost_usd
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": res.content, "is_error": res.is_error})
        messages.append({"role": "user", "content": results})
    text = "".join(b.text for b in r.content if b.type == "text")
    return {"rows": parse_json_array(text), "in": tok_in, "out": tok_out, "web_calls": calls,
            "web_cost": web_cost, "stop": r.stop_reason}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", choices=["native", "webrouter"], required=True)
    ap.add_argument("--limit", type=int, default=None, help="only the first N companies")
    ap.add_argument("--model", default=CONFIG["model"])
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    rows_in = companies()[: args.limit]
    tools_obj = None
    if args.web == "webrouter":
        from web_router import WebRouter
        from web_router.integrations.anthropic import WebRouterTools

        # Constrain before you search: a recency window, and capped page text so a
        # single extract can't flood the model's context.
        tools_obj = WebRouterTools(
            WebRouter(),
            methods=("search", "extract"),
            max_results=5,
            recency="month",
            result_chars=600,
            document_chars=4000,
        )

    def one(c: dict) -> dict:
        try:
            if args.web == "native":
                out = run_native(c["company"], args.model)
            else:
                out = run_webrouter(c["company"], args.model, tools_obj)
        except anthropic.APIError as e:
            print(f"  {c['company']}: API error, skipped ({e.__class__.__name__})")
            return {"rows": [], "in": 0, "out": 0, "web_calls": 0, "web_cost": 0.0}
        for r in out["rows"]:
            r["company"] = c["company"]
        print(f"  {c['company']}: {len(out['rows'])} launches, {out['web_calls']} web calls")
        return out

    print(f"Running {len(rows_in)} companies with {args.web} web tools on {args.model} ...")
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as pool:
        outs = list(pool.map(one, rows_in))
    seconds = round(time.time() - t0, 1)

    tok_in = sum(o["in"] for o in outs)
    tok_out = sum(o["out"] for o in outs)
    web_cost = sum(o["web_cost"] for o in outs)
    metrics = {
        "seconds": seconds,
        "input_tokens": tok_in,
        "output_tokens": tok_out,
        "web_calls": sum(o["web_calls"] for o in outs),
        "cost_usd": round(llm_cost(args.model, tok_in, tok_out) + web_cost, 4),
        "web_cost_usd": round(web_cost, 4),
        "model": args.model,
    }
    path = RESULTS / f"harness_{args.web}.csv"
    write_results(path, [r for o in outs for r in o["rows"]])
    path.with_suffix(".metrics.json").write_text(json.dumps(metrics, indent=2))
    show(score(path))


if __name__ == "__main__":
    main()
