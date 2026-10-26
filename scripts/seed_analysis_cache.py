"""Seed persistent Firestore analysis cache from already imported canonical CSV."""
import argparse
import base64
import csv
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.catalog import agricultural_categories
from app.config import Settings
from app.repositories.firestore import FirestoreRepository
from app.schemas import PriceCreate
from app.services.prices import document_for_price
from app.services.seasonality import analyze_seasonality
from app.services.trends import build_trends


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='write two compact analysis docs to Firestore')
    parser.add_argument('--from-month', default='2014-12')
    parser.add_argument('--to-month', default='2024-12')
    args = parser.parse_args()
    settings = Settings.from_env()
    records = []
    with (ROOT/'data/processed/agricultural_prices.csv').open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            if not args.from_month <= row['year_month'] <= args.to_month:
                continue
            payload = PriceCreate.model_validate({k:row[k] for k in (
                'year_month','item_name','variety_name','grade_name','quantity','unit','average_price')})
            record_id, data = document_for_price(payload, source='csv')
            records.append({**data, 'id':record_id, 'observation_id':record_id,
                            'analysis_eligible':True, 'quality_flags':''})
    ids=[r['id'] for r in records]
    if len(ids)!=len(set(ids)):
        raise ValueError('CSV has duplicate Firestore identities; resolve before caching')
    analysis=analyze_seasonality(records, agricultural_categories(),
        start_year=settings.analysis_start_year, end_year=settings.analysis_end_year,
        min_years=settings.analysis_min_years)
    periods=[r['year_month'] for r in records]
    analysis['metadata'].update(source_start=min(periods,default=None),source_end=max(periods,default=None),
        generated_at=datetime.now(timezone.utc),storage='firestore-cache',
        freshness='Firestore 분석 캐시. 관리자 API 변경 시 버전 갱신')
    analysis['price_trends']=build_trends(records)
    summary=json.dumps({k:analysis[k] for k in ('metadata','rankings','monthly_patterns')},ensure_ascii=False,default=str).encode()
    trends=json.dumps(analysis['price_trends'],ensure_ascii=False,default=str).encode()
    sizes={'summary_cache_bytes':len(base64.b64encode(gzip.compress(summary))),
           'trends_cache_bytes':len(base64.b64encode(gzip.compress(trends)))}
    print(json.dumps({'mode':'write' if args.write else 'dry-run','records':len(records),
                      'period':[min(periods,default=None),max(periods,default=None)],**sizes}))
    if args.write:
        store=FirestoreRepository(settings)
        revision=store.analysis_revision()
        store.write_analysis_cache(revision,settings.analysis_start_year,settings.analysis_end_year,
                                   settings.analysis_min_years,analysis)
        print(f'Analysis cache seeded at revision {revision} from local canonical CSV. No price collection scan was performed.')
    else:
        print('Dry run only. No Firestore connection or writes were performed.')


if __name__=='__main__':
    main()
