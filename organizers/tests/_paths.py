"""Put the repo root (common.py, score.py) and organizers/ (harness.py, ...) on sys.path for the tests."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE.parent.parent, HERE.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

ITEM = {"item_id": "1", "item": "carry-on suitcase", "max_price_usd": "300",
        "must_have": "fits 22 x 14 x 9 in, spinner wheels"}
OFFER = {"product": "Brand Carry-On", "retailer": "Brand", "price_usd": 245.0, "in_stock": True,
         "evidence": "$245, in stock", "source_url": "https://example.com/carry-on", "seen_date": "2026-11-20"}
