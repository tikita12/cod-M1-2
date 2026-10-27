import hashlib
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal

from app.catalog import agricultural_categories
from app.schemas import PriceRecord
from app.services.seasonality import analyze_seasonality, summary_for_month
from app.services.trends import build_trends


def document_for_price(payload, source="manual"):
    """Stable ID from natural identity; price corrections keep the same ID."""
    data = payload.model_dump(mode="json")
    quantity = payload.quantity
    unit = payload.unit
    if unit in {"g", "ml"}:
        quantity /= 1000
        unit = "kg" if unit == "g" else "L"
    comparison_quantity = format(quantity.normalize(), "f")
    key = [payload.year_month, payload.item_name, payload.variety_name, payload.grade_name,
           comparison_quantity, unit]
    record_id = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()
    now = datetime.now(timezone.utc)
    # Decimal prices are stored as exact decimal strings, validated at API boundaries.
    data.update(category=agricultural_categories()[payload.item_name], source=source,
                comparison_quantity=comparison_quantity, comparison_unit=unit,
                created_at=now, updated_at=now)
    return record_id, data


class PriceService:
    def __init__(self, repository, settings):
        self.repository = repository
        self.settings = settings
        self._analysis = None
        self._analysis_revision = None
        self._analysis_lock = threading.Lock()

    def invalidate_analysis(self):
        with self._analysis_lock:
            self._analysis = None
            self._analysis_revision = None

    def create(self, payload):
        record_id, data = document_for_price(payload)
        created = self.repository.create(record_id, data)
        self.invalidate_analysis()
        return created

    def update(self, record_id, payload):
        updated = self.repository.update(record_id, {
            "average_price": str(payload.average_price), "note": payload.note,
            "updated_at": datetime.now(timezone.utc),
        })
        self.invalidate_analysis()
        return updated

    def delete(self, record_id):
        self.repository.delete(record_id)
        self.invalidate_analysis()

    def _get_analysis(self):
        # Read the collection once per process, regardless of how often users
        # switch months. Mutations through this API invalidate the derived index.
        with self._analysis_lock:
            if self._analysis is None:
                config = self.settings
                revision = self.repository.analysis_revision()
                cached = self.repository.read_analysis_cache(
                    revision, config.analysis_start_year, config.analysis_end_year, config.analysis_min_years)
                if cached is not None:
                    self._analysis = cached
                    self._analysis_revision = revision
                    return cached
                records = self.repository.analysis_records(
                    f"{config.analysis_start_year - 1}-12", f"{config.analysis_end_year}-12",
                    config.summary_max_records)
                normalized = []
                for record in records:
                    validated = PriceRecord.model_validate(record)
                    normalized.append({**validated.model_dump(mode="json"),
                                       "observation_id": validated.id, "analysis_eligible": True,
                                       "quality_flags": ""})
                analysis = analyze_seasonality(normalized, agricultural_categories(),
                                              start_year=config.analysis_start_year,
                                              end_year=config.analysis_end_year,
                                              min_years=config.analysis_min_years)
                periods = [r["year_month"] for r in normalized]
                analysis["metadata"].update(
                    source_start=min(periods, default=None), source_end=max(periods, default=None),
                    generated_at=datetime.now(timezone.utc), storage="firestore",
                    freshness="영구 Firestore 요약 캐시. 가격 API 변경은 버전으로 감지")
                analysis['price_trends'] = build_trends(normalized)
                self._analysis_revision = revision
                try:
                    self.repository.write_analysis_cache(
                        revision, config.analysis_start_year, config.analysis_end_year,
                        config.analysis_min_years, analysis)
                except Exception:
                    # The current request still succeeds. This process keeps its cache;
                    # next restart may need the source query again.
                    import logging
                    logging.getLogger(__name__).exception("Could not persist Firestore analysis cache")
                self._analysis = analysis
            analysis = self._analysis
        return analysis

    def summary(self, month, limit):
        return summary_for_month(self._get_analysis(), month, limit)

    def trend(self, item_name):
        analysis = self._get_analysis()
        return {'item_name': item_name, 'series': analysis['price_trends'].get(item_name, []),
                'storage': 'firestore', 'generated_at': analysis['metadata']['generated_at']}
