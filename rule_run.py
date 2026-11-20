"""Run the launch task through a router's plan, then score it.

  uv run rule_run.py --router default   # WebRouter's built-in rules
  uv run rule_run.py --router mine      # your rule in my_router.py

For each company: plan + run one search with the router, then turn the results
into launch records. With ANTHROPIC_API_KEY set, one Claude call (no tools) does
that; without it, every search result becomes a record (undated or old ones
score as stale), so the exercise needs no key. Writes results/rule_<name>.csv and .metrics.json and
prints the score and a leaderboard line.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic
from web_router import WebRouter

from common import CONFIG, RESULTS, companies, llm_cost, parse_json_array, task_prompt, write_results
from score import line, score, show

client = anthropic.Anthropic() if os.environ.get("ANTHROPIC_API_KEY") else None


def from_results(results) -> list[dict]:
    """No-key mode: each search result is one record; undated or old ones score as stale."""
    return [{"announcement": r.title, "event_date": str(r.published_date or "")[:10],
             "evidence": (r.description or r.content or "")[:200].replace("\n", " "),
             "source_url": r.url} for r in results]


def structure(company: str, results_text: str, model: str) -> tuple[list[dict], int, int]:
    r = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": task_prompt(company) +
                   "\n\nDon't search: use only these search results.\n\n" + results_text}],
    )
    text = "".join(b.text for b in r.content if b.type == "text")
    return parse_json_array(text), r.usage.input_tokens, r.usage.output_tokens


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--router", choices=["default", "mine"], required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default=CONFIG["model"])
    args = ap.parse_args()

    if args.router == "mine":
        from my_router import my_router as router_fn
    else:
        router_fn = "rules"

    rows_in = companies()[: args.limit]
    web_cost = 0.0
    tok = [0, 0]

    with WebRouter(router=router_fn) as router:
        def one(c: dict) -> list[dict]:
            nonlocal web_cost
            prompt = f"{c['company']} product launches in the last 30 days"
            plan = router.plan(prompt)
            res = router.run(plan)
            web_cost += res.cost_usd or 0
            text = "\n\n".join(
                f"{r.title}\n{r.url}\npublished: {r.published_date or 'unknown'}\n{(r.content or r.description or '')[:1500]}"
                for r in res.results
            )
            if client is None:
                rows, i, o = from_results(res.results), 0, 0
            else:
                rows, i, o = structure(c["company"], text, args.model)
            tok[0] += i
            tok[1] += o
            for r in rows:
                r["company"] = c["company"]
            reason = plan.decision.reason if plan.decision else ""
            print(f"  {c['company']}: {res.provider}, {len(rows)} launches  ({reason})")
            return rows

        print(f"Running {len(rows_in)} companies with the {args.router} router ...")
        t0 = time.time()
        with ThreadPoolExecutor(6) as pool:
            out = [r for rows in pool.map(one, rows_in) for r in rows]
        seconds = round(time.time() - t0, 1)

    path = RESULTS / f"rule_{args.router}.csv"
    write_results(path, out)
    path.with_suffix(".metrics.json").write_text(json.dumps({
        "seconds": seconds,
        "input_tokens": tok[0],
        "output_tokens": tok[1],
        "web_calls": len(rows_in),
        "cost_usd": round(llm_cost(args.model, *tok) + web_cost, 4),
        "web_cost_usd": round(web_cost, 4),
        "model": args.model,
    }, indent=2))
    s = score(path)
    show(s)
    print("\nLeaderboard line:\n  " + line(s))


if __name__ == "__main__":
    main()
