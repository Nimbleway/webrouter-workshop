"""Same search, different providers: how much does the backend alone change the answer?

Usage: uv run providers.py 1                 # wishlist item 1
       uv run providers.py "air fryer deals"   # or any query

Runs one search through the open source WebRouter against each free backend
(no API keys needed), with a one-week recency filter, and shows what comes back.
"""

from __future__ import annotations

import sys
import time

from web_router import WebRouter
from web_router.exceptions import UnsupportedParameterError

from common import CONFIG, wishlist

FREE_BACKENDS = ["auto", "exa-mcp", "you-mcp", "parallel-mcp"]


def query_for(arg: str) -> str:
    items = {w["item_id"]: w for w in wishlist()}
    if arg in items:
        w = items[arg]
        return f"{w['item']} deals under ${w['max_price_usd']}"
    return arg or query_for("1")


def main() -> None:
    query = query_for(" ".join(sys.argv[1:]).strip())
    print(f'"{query}", recency = week, window {CONFIG["window_start"]} to {CONFIG["window_end"]}\n')
    with WebRouter() as router:
        for backend in FREE_BACKENDS:
            kwargs = {} if backend == "auto" else {"provider": backend}
            t0 = time.time()
            try:
                res = router.search(query, max_results=5, recency="week", timeout=30, **kwargs)
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
                host = r.url.split("/")[2] if "//" in r.url else r.url
                print(f"    {str(r.published_date or '-')[:10]:<10}  {host[:28]:<28}  {r.title[:60]}")
            print()


if __name__ == "__main__":
    main()
