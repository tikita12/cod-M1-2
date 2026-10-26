"""Historical monthly price changes, reusable from CSV and future API routes.

Each year has equal weight. First take the median of matched series changes
within an item/year/month, then summarize those yearly observations.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import median


def previous_month(period):
    year, month = map(int, period.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def as_number(value):
    return round(float(value), 4)


def analyze_seasonality(records, categories, *, start_year, end_year,
                        min_years=5, min_drop_ratio=0.6, recent_years=2):
    if start_year > end_year or min_years < 1 or recent_years < 1 or not 0 <= min_drop_ratio <= 1:
        raise ValueError("잘못된 분석 설정")
    series = defaultdict(dict)
    selected_count = 0
    for row in records:
        if row["item_name"] not in categories:
            continue
        if row.get("quality_flags") or str(row.get("analysis_eligible", True)).lower() != "true":
            raise ValueError("확인 대상 기록을 분석에 사용할 수 없습니다")
        period = row["year_month"]
        date.fromisoformat(period + "-01")
        price = Decimal(str(row["average_price"]))
        qty = Decimal(str(row["comparison_quantity"]))
        if not price.is_finite() or price <= 0 or not qty.is_finite() or qty <= 0:
            raise ValueError("가격과 수량은 유한한 양수여야 합니다")
        key = (row["item_name"], row["variety_name"], row["grade_name"],
               qty, row["comparison_unit"])
        if period in series[key]:
            raise ValueError("같은 비교 조건과 연월의 중복 기록")
        series[key][period] = (price, row)
        selected_count += 1

    pairs = []
    yearly_groups = defaultdict(list)
    # January uses the immediately preceding December, including start_year-1.
    for key, months in sorted(series.items()):
        for period, (current_price, row) in sorted(months.items()):
            year, month = map(int, period.split("-"))
            if not start_year <= year <= end_year:
                continue
            prior_period = previous_month(period)
            if prior_period not in months:
                continue
            prior_price, prior_row = months[prior_period]
            change = (current_price / prior_price - 1) * 100
            pair = {
                "item_name": key[0], "category": categories[key[0]],
                "variety_name": key[1], "grade_name": key[2],
                "comparison_quantity": str(key[3]), "comparison_unit": key[4],
                "year": year, "month": month, "previous_year_month": prior_period,
                "year_month": period, "previous_price": as_number(prior_price),
                "current_price": as_number(current_price), "change_pct": as_number(change),
                "previous_observation_id": prior_row.get("observation_id", ""),
                "observation_id": row.get("observation_id", ""),
            }
            pairs.append(pair)
            yearly_groups[(key[0], year, month)].append(change)

    annual = []
    month_groups = defaultdict(list)
    for (item, year, month), changes in sorted(yearly_groups.items()):
        item_change = median(changes)
        annual.append({"item_name": item, "category": categories[item], "year": year,
                       "month": month, "matched_series_count": len(changes),
                       "median_change_pct": as_number(item_change)})
        month_groups[(item, month)].append((year, item_change, len(changes)))

    patterns = []
    rankings = {str(month): [] for month in range(1, 13)}
    for (item, month), observations in sorted(month_groups.items()):
        changes = [entry[1] for entry in observations]
        years = sorted(entry[0] for entry in observations)
        drop_count = sum(change < 0 for change in changes)
        ratio = Decimal(drop_count) / len(changes)
        central_change = median(changes)
        enough = len(years) >= min_years
        recent = max(years) >= end_year - recent_years + 1
        candidate = enough and recent and central_change < 0 and ratio >= Decimal(str(min_drop_ratio))
        row = {
            "item_name": item, "category": categories[item], "month": month,
            "previous_month": 12 if month == 1 else month - 1,
            "median_change_pct": as_number(central_change),
            "drop_year_count": drop_count, "sample_year_count": len(years),
            "drop_frequency_pct": as_number(ratio * 100),
            "first_sample_year": min(years), "last_sample_year": max(years),
            "sample_years": years,
            "matched_pair_count": sum(entry[2] for entry in observations),
            "enough_years": enough, "has_recent_observation": recent,
            "is_candidate": candidate,
        }
        patterns.append(row)
        if candidate:
            rankings[str(month)].append(dict(row))
    for rows in rankings.values():
        rows.sort(key=lambda r: (r["median_change_pct"], -r["sample_year_count"], r["item_name"]))
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank

    return {
        "metadata": {
            "start_year": start_year, "end_year": end_year, "min_years": min_years,
            "min_drop_frequency_pct": min_drop_ratio * 100, "recent_years": recent_years,
            "selected_record_count": selected_count, "paired_series_change_count": len(pairs),
            "paired_item_count": len({r['item_name'] for r in pairs}),
            "method": "동일 조건의 전월→대상 월 변화율 → 품목·연도별 중앙값 → 여러 해의 중앙값",
            "interpretation": "과거 계절적 하락 경향입니다. 미래 가격 또는 하락 확률의 예측값이 아닙니다.",
            "limitations": [
                "날씨·공급·수요·최신 가격·물가 상승률을 반영하지 않았습니다.",
                "전월과 대상 월의 같은 품종·등급·판매 수량·단위가 모두 있을 때만 비교합니다.",
                "수입 농산물도 포함합니다. 같은 품목에 비교 가능한 여러 품종·등급이 섞일 수 있습니다.",
                "연도별 비교 가능한 품종·등급 구성이 달라질 수 있습니다.",
                "가격의 절대적 저렴함이나 현재 구매 가격을 의미하지 않습니다.",
            ],
        },
        "series_changes": pairs, "item_year_changes": annual,
        "monthly_patterns": patterns, "rankings": rankings,
    }


def summary_for_month(analysis, month, limit=10):
    """Compact, JSON-safe payload for a future summary endpoint and chatbot."""
    if month not in range(1, 13) or not 1 <= limit <= 100:
        raise ValueError("month는 1~12, limit는 1~100이어야 합니다")
    return {"metadata": analysis["metadata"], "target_month": month,
            "previous_month": 12 if month == 1 else month - 1,
            "candidate_count": len(analysis["rankings"][str(month)]),
            "candidates": analysis["rankings"][str(month)][:limit]}
