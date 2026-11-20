"""Same search, different providers: how much does the backend alone change the answer?

Usage: uv run providers.py Figma

Runs one search through the open source WebRouter against each free backend
(no API keys needed), with a one-month recency filter, and shows what comes back.
"""

from __future__ import annotations

import sys
import time

from web_router import WebRouter
from web_router.exceptions import UnsupportedParameterError

from common import CONFIG

FREE_BACKENDS = ["auto", "exa-mcp", "you-mcp", "parallel-mcp"]


def main() -> None:
    company = " ".join(sys.argv[1:]) or "Figma"
    query = f"{company} product launches"
    print(f'"{query}", recency = month, window {CONFIG["window_start"]} to {CONFIG["window_end"]}\n')
    with WebRouter() as router:
        for backend in FREE_BACKENDS:
            kwargs = {} if backend == "auto" else {"provider": backend}
            t0 = time.time()
            try:
                res = router.search(query, max_results=5, recency="month", timeout=30, **kwargs)
            except UnsupportedParameterError:
                print(f"{backend:<13} refused: it can't honour the recency filter, so WebRouter raises")
                print("              instead of quietly running the search without it\n")
                continue
            except Exception as e:  # a backend can be down or rate limited; show it and move on
                print(f"{backend:<13} failed: {e.__class__.__name__}\n")
                continue
            dated = [r for r in res.results if r.published_date and str(r.published_date)[:10] >= CONFIG["window_start"]]
            print(f"{backend:<13} served by {res.provider}, {time.time() - t0:.1f}s, ${res.cost_usd or 0:.3f}, "
                  f"{len(dated)}/{len(res.results)} dated inside the window")
            for r in res.results:
                print(f"    {str(r.published_date or '-')[:10]:<10}  {r.title[:80]}")
            print()


if __name__ == "__main__":
    main()
