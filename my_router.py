"""Your routing rule. Edit my_router(), then: uv run rule_run.py --router mine

A router sees each prompt and decides, before anything runs:
  - tools:     which method to use ("search", "extract", "research", ...)
  - providers: which backends to try, best first
  - params:    a few safe options per method (search: max_results, search_depth)
It can't change options like the date filter: those stay in the caller's hands,
so a call never runs looser than you asked.

The default rules only look for a URL or the word "report". Teach yours about
freshness: a price from last month's roundup is a wrong price. When a prompt
asks for "the last N days" or "this week", send the search to providers that
handle dates well, first. Results from providers.py are a good
hint for which ones.
"""

from __future__ import annotations

import re

from web_router.routing.contract import RouteDecision, RouteRequest
from web_router.routing.rules import rules

FRESH = re.compile(r"last \d+ days|this (week|month)|today|latest|right now", re.I)


def my_router(req: RouteRequest) -> RouteDecision:
    # TODO: if FRESH matches the prompt and there's no URL in it, return a
    # RouteDecision with tools=["search"], your providers in order, and a reason.
    return rules(req)  # everything else: the default rules
