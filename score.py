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
from difflib import SequenceMatcher
from pathlib import Path

from common import CONFIG, answer_key, read_results


def norm_url(url: str) -> str:
    url = (url or "").strip().lower()
    url = re.sub(r"^https?://(www\.)?", "", url).split("#")[0].split("?")[0]
    return url.rstrip("/")


def similar(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    if SequenceMatcher(None, a, b).ratio() >= 0.6:
        return True
    wa, wb = set(re.findall(r"[a-z0-9]+", a)), set(re.findall(r"[a-z0-9]+", b))
    wa, wb = wa - {"the", "a", "and", "for", "is", "now", "new", "of", "to", "with", "in"}, wb
    return bool(wa) and len(wa & wb) / len(wa) >= 0.6


def score(path: str | Path) -> dict:
    rows = read_results(path)
    key = answer_key()
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
            if norm_url(k["source_url"]) == norm_url(r.get("source_url", "")) or similar(
                k["announcement"], r.get("announcement", "")
            ):
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
    print(f"  launches found     {s['found']} / {s['key_total']} in the answer key")
    print(f"  rows returned      {s['rows']}")
    print(f"  stale or undated   {s['stale_or_undated']}")
    print(f"  no evidence / URL  {s['unsupported']}")
    print(f"  not in answer key  {s['not_in_key']}  (check these by hand: the key is a draft)")
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
    return f"{Path(s['file']).stem}: {s['found']}/{s['key_total']} found, {s['stale_or_undated']} stale, {per_cent}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--line", action="store_true", help="one line per file, for the leaderboard")
    args = ap.parse_args()
    for f in args.files:
        s = score(f)
        print(line(s)) if args.line else show(s)
