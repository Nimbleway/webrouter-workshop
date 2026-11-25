"""Score a results CSV against the shopper's wishlist and the answer key.

Usage: uv run score.py results/baseline.csv [--line]

Columns expected: item_id, product, retailer, price_usd, in_stock, evidence, source_url, seen_date.
If results/<name>.metrics.json exists (written by harness.py or rule_run.py),
its time, tokens and cost are shown too.

An offer counts when it is in budget, in stock, priced inside the window in
config.json and backed by evidence and a URL. An item is "found" when it has a
counted offer for a product the answer key also lists for that item.
"""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from common import CONFIG, answer_key, read_results, wishlist

STOP = {"the", "a", "and", "for", "with", "in", "of", "women", "womens", "s", "new", "by", "x"}


def norm_url(url: str) -> str:
    url = (url or "").strip().lower()
    url = re.sub(r"^https?://(www\.)?", "", url).split("#")[0].split("?")[0]
    return url.rstrip("/")


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower())) - STOP


def same_product(a: str, b: str) -> bool:
    """Loose product match: "Sony WH-1000XM6" matches "Sony WH-1000XM6 Wireless Headphones, Black"."""
    if SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.7:
        return True
    wa, wb = words(a), words(b)
    small = min(len(wa), len(wb))
    return small >= 2 and len(wa & wb) / small >= 0.75


def price(value) -> float | None:
    m = re.search(r"\d[\d,]*(\.\d+)?", str(value or ""))
    return float(m.group(0).replace(",", "")) if m else None


def truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "yes", "1", "in stock", "y"}


def score(path: str | Path, n_items: int | None = None) -> dict:
    """Score a run. n_items: how many wishlist items it was asked to shop (default: config live_items)."""
    rows = read_results(path)
    all_items = wishlist()
    n_items = n_items or CONFIG.get("live_items") or len(all_items)
    items = {w["item_id"]: w for w in all_items}
    key = answer_key()
    start, end = CONFIG["window_start"], CONFIG["window_end"]
    covered, found = set(), set()
    stale = over_budget = out_of_stock = unsupported = not_in_key = 0
    for r in rows:
        item = items.get(str(r.get("item_id", "")).strip())
        cost = price(r.get("price_usd"))
        date = (r.get("seen_date") or "").strip()[:10]
        ok = item is not None
        if not date or not (start <= date <= end):
            stale += 1
            ok = False
        if item is None or cost is None or cost > float(item["max_price_usd"]):
            over_budget += 1
            ok = False
        if not truthy(r.get("in_stock")):
            out_of_stock += 1
            ok = False
        if not (r.get("evidence") or "").strip() or not (r.get("source_url") or "").strip():
            unsupported += 1
            ok = False
        in_key = item is not None and any(
            k["item_id"] == item["item_id"]
            and (norm_url(k["source_url"]) == norm_url(r.get("source_url", "")) or same_product(k["product"], r.get("product", "")))
            for k in key
        )
        if not in_key:
            not_in_key += 1
        if ok:
            covered.add(item["item_id"])
            if in_key:
                found.add(item["item_id"])
    out = {
        "file": str(path),
        "rows": len(rows),
        "found": len(found),
        "covered": len(covered),
        "key_total": min(n_items, len(all_items)),
        "stale_or_undated": stale,
        "over_budget": over_budget,
        "out_of_stock": out_of_stock,
        "unsupported": unsupported,
        "not_in_key": not_in_key,
    }
    metrics = Path(path).with_suffix(".metrics.json")
    meta = Path(path).with_suffix(".meta.json")
    calls = Path(path).with_suffix(".calls.jsonl")
    if metrics.exists():
        out.update(json.loads(metrics.read_text()))
    elif meta.exists():
        out.update(json.loads(meta.read_text()))
    if calls.exists():
        out.update(estimate(calls))
    return out


def estimate(calls_path: Path) -> dict:
    """Estimate web cost and tokens from the agent's own log of its web tool calls.

    Each line: {"tool": "...", "input": "...", "result_chars": 1234, "cost_usd": 0.005 (optional)}.
    Tokens are estimated at ~4 characters per token for what the tools sent back
    (that is what lands in the model's context). Cost = each call's reported cost
    where the tool reports one (WebRouter does), else the tool's list price,
    plus those tokens at the model's input price. Estimates, not a bill.
    """
    from common import CONFIG, WEB_TOOL_PRICES, llm_cost

    n = chars = 0
    web_cost = 0.0
    for raw in calls_path.read_text().splitlines():
        if not raw.strip():
            continue
        c = json.loads(raw)
        n += 1
        chars += int(c.get("result_chars") or 0) + len(str(c.get("input") or ""))
        reported = c.get("cost_usd")
        web_cost += float(reported) if reported is not None else WEB_TOOL_PRICES.get(str(c.get("tool", "")).lower(), 0.0)
    tokens = chars // 4
    return {
        "tool_calls": n,
        "est_tool_tokens": tokens,
        "est_web_cost_usd": round(web_cost, 4),
        "est_cost_usd": round(web_cost + llm_cost(CONFIG["model"], tokens, 0), 4),
    }


def show(s: dict) -> None:
    print(f"\n{s['file']}")
    print(f"  items found        {s['found']} / {s['key_total']}  (a valid offer for a product the answer key lists)")
    print(f"  items covered      {s['covered']} / {s['key_total']}  (any valid offer: in budget, in stock, fresh, sourced)")
    print(f"  offers returned    {s['rows']}")
    print(f"  stale or undated   {s['stale_or_undated']}  (price not seen {CONFIG['window_start']} to {CONFIG['window_end']})")
    print(f"  over budget        {s['over_budget']}")
    print(f"  not in stock       {s['out_of_stock']}")
    print(f"  no evidence / URL  {s['unsupported']}")
    print(f"  not in answer key  {s['not_in_key']}  (check these by hand: the key is a reference, not the only answer)")
    for k, label in [("tool_calls", "web tool calls"), ("est_tool_tokens", "est. tool tokens"),
                     ("est_cost_usd", "est. cost (US$)"), ("seconds", "time (s)"), ("input_tokens", "input tokens"), ("output_tokens", "output tokens"),
                     ("web_calls", "web calls"), ("cost_usd", "cost (US$)")]:
        if k in s:
            print(f"  {label:<18} {s[k]}")


def line(s: dict) -> str:
    cost = s.get("cost_usd", s.get("est_cost_usd"))
    if cost is None:
        per_cent = "cost not measured"
    elif cost == 0:
        per_cent = "free (keyless backends)"
    else:
        per_cent = f"{s['found'] / (cost * 100):.1f} found per cent"
    return (f"{Path(s['file']).stem}: {s['found']}/{s['key_total']} found, {s['covered']} covered, "
            f"{s['stale_or_undated']} stale, {s['over_budget']} over budget, {per_cent}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--line", action="store_true", help="one line per file")
    ap.add_argument("--items", type=int, default=None, help="wishlist items the run shopped (default: config live_items, 5)")
    args = ap.parse_args()
    for f in args.files:
        s = score(f, args.items)
        print(line(s)) if args.line else show(s)
