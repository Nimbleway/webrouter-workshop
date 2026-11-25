"""Shared helpers: config, companies, the answer key, result files and prices."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

CONFIG = json.loads((ROOT / "config.json").read_text())
FIELDS = ["company", "announcement", "event_date", "evidence", "source_url"]

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


def companies() -> list[dict]:
    with open(ROOT / "companies.csv") as source:
        return list(csv.DictReader(source))


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


def task_prompt(company: str) -> str:
    domain = next((row["domain"] for row in companies() if row["company"] == company), None)
    source_hint = (
        f"Start with the company's official site, {domain}: search site:{domain} for its product announcements "
        "in that date window. Broaden only if the official site leaves gaps. "
        if domain else ""
    )
    return (
        f"Find every product launch {company} announced between {CONFIG['window_start']} and "
        f"{CONFIG['window_end']} (inclusive). A launch is a new product, feature or release the "
        "company itself announced. "
        + source_hint
        + "Use your web tools, then reply with only a JSON array, no prose: "
        '[{"announcement": "...", "event_date": "YYYY-MM-DD", "evidence": "one short sentence from '
        'the source", "source_url": "https://..."}]. Use the date the company announced it, not the '
        "date you found it. Return [] if there were none."
    )


def parse_json_array(text: str, *, strict: bool = False) -> list[dict]:
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
    if strict and any(not isinstance(d, dict) or not all(isinstance(d.get(k), str) for k in FIELDS[1:]) for d in data):
        raise ValueError("Malformed result record")
    return [d for d in data if isinstance(d, dict)]


def llm_cost(model: str, usage_in: int, usage_out: int, *, cache_read: int = 0, cache_write: int = 0) -> float:
    price_in, price_out = MODEL_PRICES.get(model, MODEL_PRICES["claude-opus-5-5"])
    read_multiplier = 0.05 if model in {"claude-opus-5-5", "claude-sonnet-5-5"} else 0.1
    return ((usage_in + 1.25 * cache_write + read_multiplier * cache_read) * price_in
            + usage_out * price_out) / 1e6
