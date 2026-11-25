"""Compare named runs without confusing draft overlap with validated quality."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from common import RESULTS
from score import score


def run_name(path):
    manifest = path.parent / 'manifest.json'
    if not manifest.exists():
        return path.stem
    m = json.loads(manifest.read_text())
    arm = 'native' if m['web'] == 'native' else f"webrouter-{m['extract_provider']}"
    return f"{arm}/{m['run_id']}"


def main():
    files = [Path(f) for f in sys.argv[1:]] or sorted(RESULTS.rglob('*.csv'))
    if not files:
        print('No results yet: run the kickoff first.')
        return
    columns = [('rows', 'rows'), ('valid', 'valid'), ('unresolved', 'unresolved'),
               ('seconds', 'seconds'), ('model_cost_usd', 'model est $'),
               ('provider_returned_estimate_usd', 'provider $'), ('cost_usd', 'total est $')]
    names = [run_name(f) for f in files]
    width = max(map(len, names)) + 2
    print('run'.ljust(width) + ''.join(label.rjust(13) for _, label in columns))
    for name, path in zip(names, files):
        result = score(path)
        print(name.ljust(width) + ''.join(str(result.get(k) if result.get(k) is not None else '-').rjust(13)
                                          for k, _ in columns))
    print('\nValid/unresolved require source-reviewed .review.json labels. Draft-key overlap is not accuracy.')
    print('Prices are estimates. Provider subtotals omit unknown and losing attempts; - means unknown or unreviewed.')
    print('Attendee tool-log estimates exclude some model work and are shown separately by score.py.')


if __name__ == '__main__':
    main()
