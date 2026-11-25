"""One working answer to the routing-rule exercise. Try your own first.

To run it: cp solutions/my_router.py my_router.py && uv run rule_run.py --router mine
"""

from __future__ import annotations

import re

from web_router.routing.contract import RouteDecision, RouteRequest
from web_router.routing.rules import rules

FRESH = re.compile(r"last \d+ days|this (week|month)|today|latest|right now", re.I)


def my_router(req: RouteRequest) -> RouteDecision:
    if FRESH.search(req.prompt) and not req.urls:
        return RouteDecision(
            tools=["search"],
            providers={"search": ["exa-mcp", "you-mcp"]},  # date-aware backends first
            reason="fresh ask: date-aware providers first",
        )
    return rules(req)
