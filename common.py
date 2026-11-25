"""Shared helpers: config, the shopper, her wishlist, the answer key, result files and prices."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

CONFIG = json.loads((ROOT / "config.json").read_text())
PERSONA = json.loads((ROOT / "persona.json").read_text())
FIELDS = ["item_id", "product", "retailer", "price_usd", "in_stock", "evidence", "source_url", "seen_date"]

# List prices, US$ per million tokens, for the models this repo is set up to use.
MODEL_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
NATIVE_SEARCH_USD = 10.00 / 1000  # Claude's built-in web search, per search

# List price per call for coding agents' built-in web tools, used when a call
# doesn't report its own cost. Claude's web search is $10 per 1,000 searches;
# fetching a page is billed only as the tokens it adds. Edit for other agents.
WEB_TOOL_PRICES = {
    "websearch": NATIVE_SEARCH_USD,
    "web_search": NATIVE_SEARCH_USD,
    "webfetch": 0.0,
    "web_fetch": 0.0,
}


def wishlist() -> list[dict]:
    return read_results(ROOT / "wishlist.csv")


def answer_key() -> list[dict]:
    return read_results(ROOT / "answer_key.csv")


def read_results(path: str | Path) -> list[dict]:
    with open(path) as source:
        return list(csv.DictReader(source))


def write_results(path: str | Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def persona_text() -> str:
    p = PERSONA
    sizes = ", ".join(f"{k} {v}" for k, v in p["sizes"].items())
    return (
        f"Shopper: {p['name']}, ships to {p['ships_to']}. Sizes: {sizes}. "
        f"Must: {'; '.join(p['must'])}. Prefers: {'; '.join(p['prefers'])}. Avoids: {'; '.join(p['avoids'])}."
    )


def task_prompt(item: dict) -> str:
    return (
        f"You are a personal shopping agent. {persona_text()} "
        f"Wishlist item {item['item_id']}: {item['item']}, at most ${item['max_price_usd']}, must have: "
        f"{item['must_have']}. Find the best offer for her: a specific product that meets every constraint, "
        f"with a price shown between {CONFIG['window_start']} and {CONFIG['window_end']} (inclusive). "
        "Use your web tools, then reply with only a JSON array of at most one offer, no prose: "
        '[{"product": "brand and model", "retailer": "store name", "price_usd": 123.45, "in_stock": true, '
        '"evidence": "one short sentence from the source showing the price and stock", '
        '"source_url": "https://... the product page", "seen_date": "YYYY-MM-DD"}]. '
        "seen_date is the date the source showed that price (today, for a live product page you opened). "
        "Return [] if nothing meets every constraint."
    )


def _is_offer(d) -> bool:
    """An offer in the shape task_prompt asks for (item_id is added by the caller)."""
    if not isinstance(d, dict) or not all(k in d for k in FIELDS[1:]):
        return False
    number = isinstance(d["price_usd"], (int, float)) and not isinstance(d["price_usd"], bool)
    return (number and isinstance(d["in_stock"], bool)
            and all(isinstance(d[k], str) for k in ("product", "retailer", "evidence", "source_url", "seen_date")))


def parse_json_array(text: str, *, strict: bool = False) -> list[dict]:
    """The JSON array in a model reply. strict: raise ValueError instead of treating a missing,
    invalid or malformed array as "no offers", so a broken reply isn't scored as an empty one."""
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        if strict:
            raise ValueError("No result array")
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        if strict:
            raise ValueError("Invalid result array") from None
        return []
    if strict and not all(_is_offer(d) for d in data):
        raise ValueError("Malformed offer")
    return [d for d in data if isinstance(d, dict)]


def llm_cost(model: str, usage_in: int, usage_out: int, *, cache_read: int = 0, cache_write: int = 0) -> float:
    """List-price estimate. usage_in is uncached input; cache writes (5-minute) cost 1.25x input,
    cache reads 0.05x input on Opus 5.5 and Sonnet 5.5 (0.1x assumed for other models)."""
    price_in, price_out = MODEL_PRICES.get(model, MODEL_PRICES["claude-opus-5-5"])
    read_multiplier = 0.05 if model in {"claude-opus-5-5", "claude-sonnet-5-5"} else 0.1
    return ((usage_in + 1.25 * cache_write + read_multiplier * cache_read) * price_in
            + usage_out * price_out) / 1e6
