"""Put every scored run side by side.

Usage: uv run compare.py            # every results/*.csv
       uv run compare.py a.csv b.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

from common import RESULTS
from score import score

COLUMNS = [
    ("found", "found"),
    ("stale_or_undated", "stale"),
    ("unsupported", "no source"),
    ("seconds", "time s"),
    ("tool_calls", "web calls"),
    ("est_tool_tokens", "tokens"),
    ("est_cost_usd", "cost $"),
]
# Runs measured through the API (harness.py, rule_run.py) report exact numbers instead.
MEASURED = {"tool_calls": "web_calls", "est_tool_tokens": "input_tokens", "est_cost_usd": "cost_usd"}


def main() -> None:
    files = [Path(f) for f in sys.argv[1:]] or sorted(RESULTS.glob("*.csv"))
    if not files:
        print("No results yet: run the kickoff first.")
        return
    rows = [score(f) for f in files]
    name_w = max(len(f.stem) for f in files) + 2
    print("run".ljust(name_w) + "".join(label.rjust(11) for _, label in COLUMNS))
    for f, s in zip(files, rows):
        cells = []
        for key, _ in COLUMNS:
            v = s.get(key, s.get(MEASURED.get(key, ""), "-"))
            if key == "found":
                v = f"{s['found']}/{s['key_total']}"
            cells.append(str(v).rjust(11))
        print(f.stem.ljust(name_w) + "".join(cells))
    print("\nFor your agent's runs, tokens and cost are estimates from its log of web tool calls")
    print("(results/<run>.calls.jsonl): ~4 characters per token, list prices per call.")
    print("Runs from harness.py and rule_run.py are measured. '-' means not measured.")


if __name__ == "__main__":
    main()
