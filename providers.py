"""Same search, different providers: how much does the backend alone change the answer?

Usage: uv run providers.py Figma

Runs one search through the open source WebRouter against several backends that offer keyless access
(subject to availability and quotas), with the fixed exercise dates in the query, and shows what comes back.
"""

from __future__ import annotations

import sys
import time

from web_router import WebRouter
from web_router.exceptions import UnsupportedParameterError

from common import CONFIG

BACKENDS = ["auto", "exa-mcp", "you-mcp", "parallel-mcp"]


def main() -> None:
    company = " ".join(sys.argv[1:]) or "Figma"
    query = f"{company} product launches {CONFIG['window_start']} to {CONFIG['window_end']}"
    print(f'"{query}", window {CONFIG["window_start"]} to {CONFIG["window_end"]}\n')
    with WebRouter() as router:
        for backend in BACKENDS:
            kwargs = {} if backend == "auto" else {"provider": backend}
            t0 = time.time()
            try:
                res = router.search(query, max_results=5, timeout=30, **kwargs)
            except UnsupportedParameterError:
                print(f"{backend:<13} refused an unsupported search option")
                continue
            except Exception as e:  # a backend can be down or rate limited; show it and move on
                print(f"{backend:<13} failed: {e.__class__.__name__}\n")
                continue
            dated = [r for r in res.results if r.published_date and CONFIG["window_start"] <= str(r.published_date)[:10] <= CONFIG["window_end"]]
            cost = "unknown" if res.cost_usd is None else f"${res.cost_usd:.3f}"
            print(f"{backend:<13} served by {res.provider}, {time.time() - t0:.1f}s, {cost}, "
                  f"{len(dated)}/{len(res.results)} page dates inside the window (not verified event dates)")
            for r in res.results:
                print(f"    {str(r.published_date or '-')[:10]:<10}  {r.title[:80]}")
            print()


if __name__ == "__main__":
    main()
