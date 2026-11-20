"""Ask the router for plans without running anything.

Usage: uv run plan_demo.py ["your own prompt"]

plan() decides the method, the providers in order and the reason, and calls
nothing. Then the same prompts get a tight budget, to show what gets dropped.
"""

from __future__ import annotations

import sys

from web_router import Budget, WebRouter

PROMPTS = [
    "read https://www.figma.com/release-notes/",
    "Figma product launches in the last 30 days",
    "Write an in-depth report comparing Figma's product launches from the last 30 days",
]


def show(router: WebRouter, prompt: str, budget: Budget | None = None) -> None:
    plan = router.plan(prompt, budget=budget)
    d = plan.decision
    print(f'"{prompt}"' + (f"  [budget ${budget.max_cost_usd}]" if budget else ""))
    print(f"   method     {plan.tool}")
    print(f"   providers  {', '.join(next(iter(plan.providers.values()), ()))}")
    if d is not None:
        print(f"   reason     {d.reason}")
        for name, why in (d.dropped or {}).items():
            if name.startswith(plan.tool + ":"):
                print(f"   dropped    {name.split(':', 1)[1]}: {why}")
    print()


def main() -> None:
    prompts = sys.argv[1:] or PROMPTS
    with WebRouter() as router:
        print("== Plans, nothing runs ==\n")
        for p in prompts:
            show(router, p)
        print("== Same prompts, $0.001 budget ==\n")
        for p in prompts:
            show(router, p, Budget(max_cost_usd=0.001))


if __name__ == "__main__":
    main()
