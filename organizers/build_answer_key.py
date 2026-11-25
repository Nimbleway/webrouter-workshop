"""Build the answer key: offers that meet each wishlist item's constraints, priced in the window.

For organizers, not attendees. One Nimble Web Search Agent run per wishlist item
at x-high effort, checking retailers' and brands' own product pages for current
price and stock. Prices move daily (and the session lands on Cyber Monday), so
rerun it the day before the workshop, then spot-check answer_key.csv.

  uv run organizers/build_answer_key.py              # window = the 7 days ending today
  uv run organizers/build_answer_key.py --end 2026-11-29
  uv run organizers/build_answer_key.py --only 3,12   # rerun a few items

Writes config.json (window_start / window_end), answer_key.csv and
organizers/answer_key_raw.json (every row the agents returned, kept or not).
Needs NIMBLE_API_KEY.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import persona_text  # noqa: E402

API = "https://sdk.nimbleway.com"
AGENT_NAME = "webrouter-workshop-wishlist-shopper"
EFFORT = "x-high"

SKILL = (
    "You are a personal shopping agent. For one wishlist item, you list specific products that meet every "
    "constraint, each with a current offer from a US retailer or the brand's own store: price, stock and a "
    "product-page URL. Open product pages to read the live price and stock; use deal roundups and reviews only "
    "to discover candidates. Skip third-party marketplace sellers, refurbished or used items, and prices that "
    "need a membership or coupon code. Never guess a price, a date or a URL."
)

ROW = {
    "type": "object",
    "properties": {
        "product": {"type": "string"},
        "retailer": {"type": "string"},
        "price_usd": {"type": "number"},
        "in_stock": {"type": "boolean"},
        "evidence": {"type": "string"},
        "source_url": {"type": "string"},
        "seen_date": {"type": "string"},
    },
    "required": ["product", "retailer", "price_usd", "in_stock", "evidence", "source_url", "seen_date"],
}
OUTPUT_SCHEMA = {"type": "array", "items": ROW}

FIELDS = ["item_id", "item", "product", "retailer", "price_usd", "evidence", "source_url", "seen_date"]


def call(method: str, path: str, body: dict | None = None, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['NIMBLE_API_KEY']}", "Content-Type": "application/json"},
    )
    for attempt in range(60):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            if e.code == 429 and "task_run_limit_exceeded" in detail:
                # The account's concurrent-run limit is shared with other jobs: wait for a slot.
                time.sleep(30)
                continue
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"{method} {path}: HTTP {e.code} {detail}") from e
        except (urllib.error.URLError, TimeoutError):
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def task(item: dict, start: str, end: str) -> str:
    return (
        f"{persona_text()} Wishlist item: {item['item']}, at most ${item['max_price_usd']} before tax and "
        f"shipping, must have: {item['must_have']}. List up to 8 different products (brand and model) that meet "
        "every constraint, each with its best offer: retailer, price_usd, in_stock, evidence (one sentence from "
        "the product page showing price and stock), source_url (the product page) and seen_date (YYYY-MM-DD, the "
        f"date the page showed that price, between {start} and {end}). Cover the obvious best sellers and "
        "this week's deals. Return [] if nothing meets every constraint."
    )


def run_item(item: dict, start: str, end: str) -> list[dict]:
    label = f"#{item['item_id']} {item['item']}"
    started = call("POST", "/v2/agents/runs", {
        "agent_name": AGENT_NAME,
        "use_case": "dataset_building",
        "effort": EFFORT,
        "skill": SKILL,
        "output_schema": OUTPUT_SCHEMA,
        "input": task(item, start, end),
    })
    agent_id, run_id = started["web_search_agent_id"], started["id"]
    t0 = time.time()
    while True:
        status = call("GET", f"/v2/agents/{agent_id}/runs/{run_id}")["status"]
        if status in ("completed", "failed", "cancelled", "canceled"):
            break
        if time.time() - t0 > 3600:
            print(f"  {label}: still {status} after an hour, skipped", flush=True)
            return []
        time.sleep(20)
    if status != "completed":
        print(f"  {label}: run {status}", flush=True)
        return []
    content = call("GET", f"/v2/agents/{agent_id}/runs/{run_id}/result")["output"]["content"]
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = []
    if isinstance(content, dict):  # some runs wrap the list in an object
        content = next((v for v in content.values() if isinstance(v, list)), [])
    rows = [dict(r, item_id=item["item_id"], item=item["item"]) for r in content if isinstance(r, dict)]
    print(f"  {label}: {len(rows)} rows in {round((time.time() - t0) / 60, 1)} min", flush=True)
    return rows


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def clean(rows: list[dict], start: str, end: str, caps: dict[str, float]) -> list[dict]:
    kept, seen = [], set()
    for r in rows:
        date = str(r.get("seen_date") or "")[:10]
        url = str(r.get("source_url") or "").strip()
        try:
            cost = float(r.get("price_usd"))
        except (TypeError, ValueError):
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not (start <= date <= end) or not url.startswith("http"):
            continue
        if r.get("in_stock") is not True or cost > caps.get(r["item_id"], 0):
            continue
        key = (r["item_id"], norm(r.get("product", "")))  # one row per product: its best offer
        if key in seen:
            continue
        seen.add(key)
        kept.append({
            "item_id": r["item_id"],
            "item": r["item"],
            "product": str(r.get("product", "")).strip(),
            "retailer": str(r.get("retailer") or "").strip(),
            "price_usd": round(cost, 2),
            "evidence": str(r.get("evidence") or "").strip().replace("\n", " "),
            "source_url": url,
            "seen_date": date,
        })
    return sorted(kept, key=lambda x: (int(x["item_id"]), x["price_usd"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default=dt.date.today().isoformat(), help="last day of the window (default: today)")
    ap.add_argument("--days", type=int, default=7, help="window length in days (default: 7)")
    ap.add_argument("--only", default="", help="comma-separated item_ids to rerun; others keep their rows")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    if "NIMBLE_API_KEY" not in os.environ:
        sys.exit("Set NIMBLE_API_KEY first.")

    end = dt.date.fromisoformat(args.end)
    start = (end - dt.timedelta(days=args.days - 1)).isoformat()
    end = end.isoformat()
    items = list(csv.DictReader(open(ROOT / "wishlist.csv")))
    caps = {i["item_id"]: float(i["max_price_usd"]) for i in items}
    only = {c.strip() for c in args.only.split(",") if c.strip()}
    todo = [i for i in items if not only or i["item_id"] in only]

    print(f"Window {start} to {end}: {len(todo)} items, {EFFORT} effort ...", flush=True)
    # The first run creates the agent by name; the rest reuse it.
    first = run_item(todo[0], start, end)
    with ThreadPoolExecutor(args.workers) as pool:
        rest = [r for batch in pool.map(lambda i: run_item(i, start, end), todo[1:]) for r in batch]
    raw = first + rest

    raw_path = ROOT / "organizers" / "answer_key_raw.json"
    if only and raw_path.exists():  # keep the other items' raw rows
        old = json.loads(raw_path.read_text()).get("rows", [])
        raw = [r for r in old if r.get("item_id") not in only] + raw
    raw_path.write_text(json.dumps({"window_start": start, "window_end": end, "effort": EFFORT, "rows": raw}, indent=2))

    key = clean(raw, start, end, caps)
    with open(ROOT / "answer_key.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(key)

    cfg_path = ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg.update({"window_start": start, "window_end": end})
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")

    per = {i["item_id"]: sum(1 for k in key if k["item_id"] == i["item_id"]) for i in items}
    print(f"\n{len(key)} offers kept of {len(raw)} rows, for {sum(1 for v in per.values() if v)} of {len(items)} items")
    print(", ".join(f"#{k} {v}" for k, v in per.items()))


if __name__ == "__main__":
    main()
