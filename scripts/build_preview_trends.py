"""Build explicit offline chart preview from the same cleaned CSV period."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.trends import build_trends

if __name__ == '__main__':
    with (ROOT / 'data/processed/agricultural_prices.csv').open(encoding='utf-8-sig', newline='') as stream:
        records = [r for r in csv.DictReader(stream) if '2014-12' <= r['year_month'] <= '2024-12']
    path = ROOT / 'frontend/sample/price_trends.json'
    path.write_text(json.dumps(build_trends(records), ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'Built chart preview from {len(records)} CSV records.')
