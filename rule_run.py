"""Run the launch search through a router's plan, and save what came back.

  uv run rule_run.py --router default   # WebRouter's built-in rules
  uv run rule_run.py --router mine      # your rule in my_router.py

For each company: plan + run one search with the router. No API key needed.
Writes, for your coding agent to turn into results/rule_<name>.csv:
  results/rule_<name>.results.json   per company: the plan's reason, who served it, every result
  results/rule_<name>.calls.jsonl    one line per search: tool, input, result_chars, cost_usd
  results/rule_<name>.meta.json      seconds
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from web_router import WebRouter

from common import RESULTS, companies


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--router", choices=["default", "mine"], required=True)
    ap.add_argument("--limit", type=int, default=None, help="only the first N companies")
    args = ap.parse_args()

    if args.router == "mine":
        from my_router import my_router as router_fn
    else:
        router_fn = "rules"

    rows_in = companies()[: args.limit]
    with WebRouter(router=router_fn) as router:

        def one(c: dict) -> dict:
            prompt = f"{c['company']} product launches in the last 30 days"
            plan = router.plan(prompt)
            res = router.run(plan)
            results = [
                {
                    "title": r.title,
                    "url": r.url,
                    "published_date": str(r.published_date)[:10] if r.published_date else None,
                    "text": (r.content or r.description or "")[:1500],
                }
                for r in res.results
            ]
            reason = plan.decision.reason if plan.decision else None
            print(f"  {c['company']}: {res.provider}, {len(results)} results  ({reason})")
            return {
                "company": c["company"],
                "prompt": prompt,
                "reason": reason,
                "provider": res.provider,
                "cost_usd": res.cost_usd,
                "results": results,
            }

        print(f"Searching {len(rows_in)} companies with the {args.router} router ...")
        t0 = time.time()
        with ThreadPoolExecutor(6) as pool:
            out = list(pool.map(one, rows_in))
        seconds = round(time.time() - t0, 1)

    base = RESULTS / f"rule_{args.router}"
    base.with_suffix(".results.json").write_text(json.dumps(out, indent=2))
    with open(base.with_suffix(".calls.jsonl"), "w") as f:
        for o in out:
            f.write(json.dumps({"tool": "search", "input": o["prompt"],
                                "result_chars": len(json.dumps(o["results"])), "cost_usd": o["cost_usd"]}) + "\n")
    base.with_suffix(".meta.json").write_text(json.dumps({"seconds": seconds, "router": args.router}))
    dated = sum(1 for o in out for r in o["results"] if r["published_date"])
    total = sum(len(o["results"]) for o in out)
    print(f"\nSaved {total} results ({dated} with a publish date) to results/{base.name}.results.json")
    print(f"Next: turn them into results/{base.name}.csv (launches only), then: uv run score.py results/{base.name}.csv")


if __name__ == "__main__":
    main()
