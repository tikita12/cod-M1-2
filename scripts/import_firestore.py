"""Validate CSV import; writes only when --write is explicitly provided."""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.errors import RecordConflict
from app.repositories.firestore import FirestoreRepository
from app.schemas import PriceCreate
from app.services.prices import document_for_price


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-month", default="2014-12")
    parser.add_argument("--to-month", default="2024-12")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--refresh-analysis-cache", action="store_true",
                        help="after import, rebuild and persist the analysis cache (one full collection read)")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.from_month > args.to_month:
        parser.error("invalid month range")
    documents = []
    with (ROOT / "data/processed/agricultural_prices.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if not args.from_month <= row['year_month'] <= args.to_month:
                continue
            payload = PriceCreate.model_validate({key: row[key] for key in (
                "year_month", "item_name", "variety_name", "grade_name", "quantity", "unit", "average_price")})
            documents.append(document_for_price(payload, source="csv"))
            if args.limit and len(documents) >= args.limit:
                break
    if len({key for key, value in documents}) != len(documents):
        raise ValueError("CSV에 비교 조건 중복이 있습니다")
    print(json.dumps({"mode": "write" if args.write else "dry-run", "validated_records": len(documents),
                      "years": dict(sorted(Counter(data['year_month'][:4] for key, data in documents).items()))}))
    if not args.write:
        print("Validation only. No Firestore connection or writes were performed.")
        return
    store = FirestoreRepository(Settings.from_env())
    created = existing = 0
    for key, data in documents:
        try:
            store.create(key, data)
            created += 1
        except RecordConflict:
            existing += 1
        if (created + existing) % 100 == 0:
            print(json.dumps({"created": created, "existing_skipped": existing}), flush=True)
    print(json.dumps({"created": created, "existing_skipped": existing}))
    if created:
        # One revision write per import job, never one write per CSV row.
        store.mark_analysis_stale()
    if args.refresh_analysis_cache:
        from app.services.prices import PriceService
        service = PriceService(store, Settings.from_env())
        service.invalidate_analysis()
        service.summary(11, 1)
        print("Persistent analysis cache refreshed.")


if __name__ == "__main__":
    main()
