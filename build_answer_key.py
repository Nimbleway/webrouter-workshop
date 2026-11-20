"""Build a draft answer key: launches each company announced on its own site inside the window.

For organizers, not attendees. Run it the day before the workshop after updating
window_start / window_end in config.json, then review answer_key.csv by hand:
it is a starting point, not ground truth.

Needs EXA_API_KEY. Usage: uv run build_answer_key.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "config.json").read_text())

LAUNCH = re.compile(
    r"\b(introduc\w*|launch\w*|announc\w*|now available|generally available|general availability|"
    r"public beta|open beta|in beta|unveil\w*|releas\w*|new\b|meet\b|ships?\b|available)\b",
    re.I,
)
NOT_A_LAUNCH = re.compile(
    r"\b(earnings|financial results|quarter|q[1-4]\b|webinar|event recap|hiring|careers|"
    r"customer story|case study|how to|tutorial|guide to|tips)\b",
    re.I,
)


def exa(body: dict) -> list[dict]:
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps(body).encode(),
        headers={"x-api-key": os.environ["EXA_API_KEY"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("results", [])


def launches(row: dict) -> list[dict]:
    results = exa(
        {
            "query": f"{row['company']} announces new product feature launch",
            "numResults": 15,
            "includeDomains": [row["domain"]],
            "startPublishedDate": CONFIG["window_start"] + "T00:00:00.000Z",
            "endPublishedDate": CONFIG["window_end"] + "T23:59:59.000Z",
        }
    )
    out, seen = [], set()
    for r in results:
        title = (r.get("title") or "").split(" | ")[0].strip()
        date = (r.get("publishedDate") or "")[:10]
        if not title or not date or title.lower() in seen:
            continue
        if not LAUNCH.search(title) or NOT_A_LAUNCH.search(title):
            continue
        seen.add(title.lower())
        out.append({"company": row["company"], "announcement": title, "event_date": date, "source_url": r["url"]})
    return out


def main() -> None:
    rows = list(csv.DictReader(open(ROOT / "companies.csv")))
    with ThreadPoolExecutor(8) as pool:
        found = [x for batch in pool.map(launches, rows) for x in batch]
    with open(ROOT / "answer_key.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["company", "announcement", "event_date", "source_url"])
        w.writeheader()
        w.writerows(sorted(found, key=lambda x: (x["company"], x["event_date"])))
    per = {r["company"]: sum(1 for x in found if x["company"] == r["company"]) for r in rows}
    print(f"{len(found)} launches across {sum(1 for v in per.values() if v)} of {len(rows)} companies")
    print(", ".join(f"{k} {v}" for k, v in per.items()))


if __name__ == "__main__":
    main()
