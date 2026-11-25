"""Score a results CSV against the answer key.

Usage: uv run score.py results/baseline.csv [--line]

Columns expected: company, announcement, event_date, evidence, source_url.
If results/<name>.metrics.json exists (written by harness.py or rule_run.py),
its time, tokens and cost are shown too.
"""

from __future__ import annotations

import argparse
import json
import re
import hashlib
from pathlib import Path

from common import CONFIG, answer_key, read_results


def norm_url(url: str) -> str:
    url = (url or "").strip().lower()
    url = re.sub(r"^https?://(www\.)?", "", url).split("#")[0].split("?")[0]
    return url.rstrip("/")


def record_id(row: dict) -> str:
    from common import FIELDS
    payload = [str(row.get(k, "")).strip() for k in FIELDS]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:20]


def same_event(a, b):
    """Conservative draft-key overlap, not source verification."""
    return (a.get("company", "").casefold() == b.get("company", "").casefold()
            and a.get("event_date") == b.get("event_date")
            and a.get("announcement", "").strip().casefold() == b.get("announcement", "").strip().casefold())


def score(path: str | Path) -> dict:
    rows = read_results(path)
    scope = {r.get("company", "").casefold() for r in rows}
    metrics_path = Path(path).with_suffix(".metrics.json")
    if metrics_path.exists():
        scope.update(c.casefold() for c in json.loads(metrics_path.read_text()).get("companies", []))
    key = [r for r in answer_key() if r["company"].casefold() in scope]
    start, end = CONFIG["window_start"], CONFIG["window_end"]
    matched_keys, stale, unsupported, unverified = set(), 0, 0, 0
    for r in rows:
        date = (r.get("event_date") or "").strip()[:10]
        if not date or not (start <= date <= end):
            stale += 1
        if not (r.get("evidence") or "").strip() or not (r.get("source_url") or "").strip():
            unsupported += 1
        hit = None
        for i, k in enumerate(key):
            if k["company"].lower() != (r.get("company") or "").lower():
                continue
            if i not in matched_keys and same_event(k, r):
                hit = i
                break
        if hit is None:
            unverified += 1
        else:
            matched_keys.add(hit)
    out = {
        "file": str(path),
        "rows": len(rows),
        "found": len(matched_keys),
        "key_total": len(key),
        "stale_or_undated": stale,
        "unsupported": unsupported,
        "not_in_key": unverified,
    }
    review_path = Path(path).with_suffix(".review.json")
    if review_path.exists():
        review = json.loads(review_path.read_text())
        labels = {r["record_id"]: r for r in review["records"]}
        counts = dict.fromkeys(("valid", "invalid", "duplicate", "unresolved"), 0)
        seen = set()
        for row in rows:
            label = labels.get(record_id(row), {})
            status = label.get("status", "unresolved")
            event = label.get("event_id")
            if status == "valid" and (not event or not label.get("verified_source")):
                status = "unresolved"
            if status == "valid" and event in seen:
                status = "duplicate"
            if status == "valid":
                seen.add(event)
            counts[status] += 1
        out.update(counts)
        out["precision"] = counts["valid"] / len(rows) if rows and not counts["unresolved"] else None
        out["reviewed_reference_coverage"] = len(seen & set(review.get("reference_event_ids", [])))
        out["reviewed_reference_total"] = len(set(review.get("reference_event_ids", [])))
        out["recall"] = (out["reviewed_reference_coverage"] / out["reviewed_reference_total"]
                         if review.get("reference_complete") and out["reviewed_reference_total"] else None)
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

    n = chars = unknown = 0
    web_cost = 0.0
    for raw in calls_path.read_text().splitlines():
        if not raw.strip():
            continue
        c = json.loads(raw)
        n += 1
        chars += int(c.get("result_chars") or 0) + len(str(c.get("input") or ""))
        reported = c.get("cost_usd")
        price = float(reported) if reported is not None else WEB_TOOL_PRICES.get(str(c.get("tool", "")).lower())
        if price is None:
            unknown += 1
        else:
            web_cost += price
    tokens = chars // 4
    return {
        "tool_calls": n,
        "est_tool_tokens": tokens,
        "est_web_cost_usd": round(web_cost, 4),
        "est_cost_usd": None if unknown else round(web_cost + llm_cost(CONFIG["model"], tokens, 0), 4),
        "unknown_cost_calls": unknown,
    }


def show(s: dict) -> None:
    print(f"\n{s['file']}")
    print(f"  exact draft overlap {s['found']} / {s['key_total']} in the scoped draft key (not accuracy)")
    print(f"  rows returned      {s['rows']}")
    print(f"  stale or undated   {s['stale_or_undated']}")
    print(f"  no evidence / URL  {s['unsupported']}")
    print(f"  not in answer key  {s['not_in_key']}  (check these by hand: the key is a draft)")
    for k, label in [("valid", "validated records"), ("invalid", "invalid records"), ("duplicate", "duplicates"), ("unresolved", "unresolved"), ("precision", "reviewed precision"), ("recall", "reviewed recall"), ("model_cost_usd", "model estimate $"), ("provider_returned_estimate_usd", "provider subtotal $"), ("tool_calls", "web tool calls"), ("est_tool_tokens", "est. tool tokens"),
                     ("est_cost_usd", "est. cost (US$)"), ("seconds", "time (s)"), ("input_tokens", "input tokens"), ("output_tokens", "output tokens"),
                     ("web_calls", "web calls"), ("cost_usd", "cost (US$)")]:
        if k in s:
            value = "unknown" if s[k] is None else s[k]
            print(f"  {label:<18} {value}")


def line(s: dict) -> str:
    if "valid" in s:
        return f"{Path(s['file']).stem}: {s['valid']}/{s['rows']} validated, {s['unresolved']} unresolved"
    return f"{Path(s['file']).stem}: {s['rows']} records, {s['found']}/{s['key_total']} exact draft overlap; quality unreviewed"



if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--line", action="store_true", help="one diagnostic line per file")
    args = ap.parse_args()
    for f in args.files:
        s = score(f)
        print(line(s)) if args.line else show(s)
