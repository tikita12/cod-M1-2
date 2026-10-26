"""Prepare monthly retail price CSVs without changing their source values.

Run: python scripts/prepare_prices.py --source-dir <folder> --as-of YYYY-MM-DD
Uses only the Python standard library. Output CSVs use UTF-8 with BOM.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "observation_id", "series_id", "year_month", "item_name", "variety_name",
    "grade_name", "quantity", "unit", "average_price", "comparison_quantity",
    "comparison_unit", "source_codes", "source_refs", "source_row_count",
    "quality_flags", "analysis_eligible",
]
FLAG_LABELS = {
    "conflicting_prices": "같은 연월·품목·품종·등급·수량·단위에 서로 다른 가격",
    "missing_grade": "등급이 데이터 미집계 등 결측 표시",
    "future_month": "실행 기준일보다 미래인 월",
    "current_month": "실행 기준일의 월: 월간 집계 완료 여부 미확인",
    "source_period_review": "원본 내 미래 월과 동일 조건의 복수 가격이 함께 있어 연월 확인 필요",
}


def clean(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value or "")).strip()


def number(value):
    try:
        result = Decimal(clean(value).replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("숫자 해석 실패: " + str(value)) from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("양수여야 하는 가격/수량: " + str(value))
    return format(result.normalize(), "f")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()[:24]


def read_source(path):
    content = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("지원하지 않는 인코딩: " + str(path))
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    return content, encoding, list(reader)


def normalize(raw):
    raw = {clean(k): clean(v) for k, v in raw.items()}
    period = raw.get("가격등록연월") or raw.get("연도", "")
    if re.fullmatch(r"\d{4}", period):
        period = f"{int(period):04d}-{int(raw['월']):02d}"
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise ValueError("잘못된 연월: " + period)
    date.fromisoformat(period + "-01")
    names = [raw.get(key, "") for key in ("품목명", "품종명", "등급명")]
    if not all(names):
        raise ValueError("품목/품종/등급 누락")
    quantity = number(raw.get("유통단계별무게", ""))
    unit = raw.get("유통단계별단위") or raw.get("유통단계별단위명", "")
    unit = {"KG": "kg", "Kg": "kg", "G": "g", "리터": "L", "l": "L"}.get(unit, unit)
    if unit not in {"kg", "g", "L", "ml", "포기", "개", "마리", "속", "장", "묶음", "봉", "손"}:
        raise ValueError("확인되지 않은 단위: " + unit)
    comp_quantity, comp_unit = quantity, unit
    if unit in {"g", "ml"}:
        comp_quantity = number(str(Decimal(quantity) / 1000))
        comp_unit = "kg" if unit == "g" else "L"
    price = number(raw.get("평균가격", ""))
    series_key = (*names, comp_quantity, comp_unit)
    key = (period, *series_key)
    row = dict(zip(("item_name", "variety_name", "grade_name"), names))
    row.update(year_month=period, quantity=quantity, unit=unit, average_price=price,
               comparison_quantity=comp_quantity, comparison_unit=comp_unit,
               series_id=digest(series_key), observation_id=digest((*key, price)))
    return key, row, raw.get("품목코드", "")


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    as_of_month = args.as_of.strftime("%Y-%m")
    raw_dir, out_dir, reports = [ROOT / p for p in ("data/raw", "data/processed", "reports")]
    for directory in (raw_dir, out_dir, reports):
        directory.mkdir(parents=True, exist_ok=True)
    paths = sorted(args.source_dir.glob("*소매가격*.csv"))
    if not paths:
        raise SystemExit("입력 CSV가 없습니다: " + str(args.source_dir))
    grouped = {}
    prices_by_key = defaultdict(set)
    source_manifest, invalid = [], []
    source_keys = defaultdict(lambda: defaultdict(set))
    source_periods = defaultdict(Counter)
    total = 0
    for path in paths:
        content, encoding, rows = read_source(path)
        destination = raw_dir / path.name
        if destination.exists() and destination.read_bytes() != content:
            raise ValueError("기존 원본 사본과 내용이 다릅니다: " + path.name)
        if not destination.exists():
            destination.write_bytes(content)
        source_manifest.append({"file": path.name, "sha256": hashlib.sha256(content).hexdigest(),
                                "encoding": encoding, "rows": len(rows)})
        total += len(rows)
        for line, raw in enumerate(rows, start=2):
            try:
                key, row, code = normalize(raw)
            except (ValueError, KeyError, TypeError) as exc:
                invalid.append({"source_file": path.name, "source_line": line,
                                "reason": str(exc), "raw_json": json.dumps(raw, ensure_ascii=False)})
                continue
            price = row["average_price"]
            source_periods[path.name][row["year_month"]] += 1
            source_keys[path.name][key].add(price)
            prices_by_key[key].add(price)
            exact_key = (*key, price)
            if exact_key not in grouped:
                grouped[exact_key] = {"row": row, "key": key, "refs": [], "codes": set()}
            group = grouped[exact_key]
            group["refs"].append({"file": path.name, "line": line})
            if code:
                group["codes"].add(code)

    suspect_sources = set()
    for entry in source_manifest:
        name = entry["file"]
        periods = source_periods[name]
        future_count = sum(n for month, n in periods.items() if month > as_of_month)
        conflict_count = sum(len(p) > 1 for p in source_keys[name].values())
        entry.update(month_counts=dict(sorted(periods.items())),
                     future_rows=future_count, within_source_conflicting_keys=conflict_count)
        if future_count and conflict_count:
            suspect_sources.add(name)
            entry["review_reason"] = FLAG_LABELS["source_period_review"]

    merged = []
    for group in grouped.values():
        row, key = group["row"], group["key"]
        flags = []
        if len(prices_by_key[key]) > 1:
            flags.append("conflicting_prices")
        if row["grade_name"] in {"데이터 미집계", "-", "미집계"}:
            flags.append("missing_grade")
        if row["year_month"] > as_of_month:
            flags.append("future_month")
        elif row["year_month"] == as_of_month:
            flags.append("current_month")
        if all(ref["file"] in suspect_sources for ref in group["refs"]):
            flags.append("source_period_review")
        row.update(source_codes="|".join(sorted(group["codes"])),
                   source_refs=json.dumps(group["refs"], ensure_ascii=False, separators=(",", ":")),
                   source_row_count=len(group["refs"]), quality_flags="|".join(flags),
                   analysis_eligible=not flags)
        merged.append(row)
    merged.sort(key=lambda r: (r["year_month"], r["item_name"], r["variety_name"],
                               r["grade_name"], r["comparison_unit"],
                               Decimal(r["comparison_quantity"]), Decimal(r["average_price"])))
    ready = [r for r in merged if r["analysis_eligible"]]
    review = [r for r in merged if not r["analysis_eligible"]]
    for name, rows in (("prices_merged.csv", merged), ("prices_clean.csv", ready), ("prices_review.csv", review)):
        write_csv(out_dir / name, rows, FIELDS)
    write_csv(reports / "invalid_rows.csv", invalid, ["source_file", "source_line", "reason", "raw_json"])

    all_months = sorted({r["year_month"] for r in merged})
    merged_counts = Counter(r["year_month"] for r in merged)
    ready_counts = Counter(r["year_month"] for r in ready)
    coverage = []
    for year in range(int(all_months[0][:4]), int(all_months[-1][:4]) + 1):
        for month in range(1, 13):
            period = f"{year:04d}-{month:02d}"
            if all_months[0] <= period <= all_months[-1]:
                coverage.append({"year_month": period, "merged_rows": merged_counts[period],
                                 "clean_rows": ready_counts[period],
                                 "review_rows": merged_counts[period] - ready_counts[period]})
    write_csv(reports / "monthly_coverage.csv", coverage, ["year_month", "merged_rows", "clean_rows", "review_rows"])
    flag_counts = Counter(flag for r in review for flag in r["quality_flags"].split("|"))
    summary = {
        "as_of": args.as_of.isoformat(), "source_files": len(paths), "input_rows": total,
        "invalid_rows": len(invalid), "duplicate_rows_removed": total - len(invalid) - len(merged),
        "merged_rows": len(merged), "clean_rows": len(ready), "review_rows": len(review),
        "conflicting_keys": sum(len(p) > 1 for p in prices_by_key.values()),
        "merged_item_count": len({r['item_name'] for r in merged}),
        "clean_item_count": len({r['item_name'] for r in ready}),
        "clean_series_count": len({r['series_id'] for r in ready}),
        "clean_start": min((r['year_month'] for r in ready), default=None),
        "clean_end": max((r['year_month'] for r in ready), default=None),
        "missing_months": [r['year_month'] for r in coverage if not r['merged_rows']],
        "review_month_counts": dict(sorted(Counter(r['year_month'] for r in review).items())),
        "flag_counts": dict(flag_counts), "flag_definitions": FLAG_LABELS,
        "source_manifest": source_manifest,
    }
    (reports / "data_quality.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 월별 소매가격 데이터 정리 결과", "", f"검토 기준일: {args.as_of.isoformat()}", "",
             f"- 입력: {len(paths)}개 파일, {total:,}행",
             f"- 같은 조건과 같은 가격의 중복 제거: {summary['duplicate_rows_removed']:,}행",
             f"- 통합: {len(merged):,}행",
             f"- 분석용: {len(ready):,}행 ({summary['clean_start']} ~ {summary['clean_end']})",
             f"- 확인 필요: {len(review):,}행 / 해석 실패: {len(invalid):,}행",
             f"- 가격이 충돌하는 비교 조건: {summary['conflicting_keys']:,}개",
             "", "## 정리 방법", "",
             "연월을 YYYY-MM으로 통일하고, 문자열 양끝 및 연속 공백을 정리했습니다.",
             "비교 조건은 연월 + 품목명 + 품종명 + 등급명 + 환산 수량 + 환산 단위입니다.",
             "g는 kg, ml는 L로 비교 수량을 환산하되 표시용 원래 수량·단위와 가격을 보존했습니다.",
             "100g와 1kg, 1개와 10개처럼 판매 수량이 다른 기록은 별도로 유지합니다.",
             "품목명·품종명·등급명이 다른 기록은 의미가 같아 보여도 임의로 합치지 않았습니다.",
             "같은 비교 조건과 가격은 하나로 합치고, 원본 파일명·행 번호를 모두 기록했습니다.",
             "가격이 다르면 평균을 내거나 최신 파일 값을 선택하지 않고 확인 대상으로 분리했습니다.",
             "품목코드는 일부 파일에만 있어 보조 정보로 보존하고 비교 키에서는 제외했습니다.",
             "", "## 확인 사항", "",
             "- 자료가 전혀 없는 월: " + (", ".join(summary['missing_months']) or "없음"),
             "- 한 월에 자료가 있다는 것은 모든 품목의 자료가 있다는 뜻은 아닙니다.",
             "- 농산물·축산물·수산물·가공식품이 섞여 있습니다. 농산물 필터는 다음 분석 단계에서 적용해야 합니다.",
             "- 20250101 파일의 관측 연도는 2024년입니다. 파일명으로 연도를 바꾸지 않았습니다.",
             "- 현재 월과 미래 월은 완료된 월별 가격 분석에서 제외했습니다.",
             "- 미래 월과 동일 조건 복수 가격이 함께 발견된 원본은 연월 확인 전까지 전체를 분석에서 보류했습니다.",
             "- 2026년 값을 2025년으로 추정해서 바꾸지 않았습니다.", ""]
    lines += [f"- {FLAG_LABELS[flag]}: {count:,}행" for flag, count in sorted(flag_counts.items())]
    lines += ["", "### 과거 월 중 일부 기록이 보류된 기간", ""]
    lines += [f"- {r['year_month']}: 분석용 {r['clean_rows']:,}행, 확인 대상 {r['review_rows']:,}행"
              for r in coverage if r['review_rows'] and r['clean_rows']]
    lines += ["", "한 행에 확인 사유가 여러 개 있을 수 있어 사유별 행 수는 합산하지 않습니다.",
              "", "## 파일별 범위", ""]
    for entry in source_manifest:
        months = list(entry["month_counts"])
        lines.append(f"- {entry['file']}: {entry['rows']:,}행, {months[0]} ~ {months[-1]} (중간 누락은 JSON 월 목록 참조)")
    lines += ["", "## 결과 파일", "",
              "- data/processed/prices_clean.csv: 확인 대상 기록을 제외한 분석용 데이터",
              "- data/processed/prices_merged.csv: 중복을 합친 모든 기록과 확인 사유",
              "- data/processed/prices_review.csv: 확인이 필요한 기록",
              "- data/raw/: 원본 사본",
              "- reports/monthly_coverage.csv: 월별 자료 유무와 분석용 행 수",
              "- reports/data_quality.json: 전체 집계, 파일 SHA-256, 인코딩 및 월별 행 수",
              "- reports/invalid_rows.csv: 해석하지 못한 행 (없어도 헤더 유지)", ""]
    (reports / "data_quality.md").write_text("\n".join(lines), encoding="utf-8")
    # Check the data contracts and conservation of rows before reporting success.
    assert total == len(invalid) + sum(r["source_row_count"] for r in merged)
    assert len(merged) == len(ready) + len(review)
    assert len({r["observation_id"] for r in merged}) == len(merged)
    assert len({(r["year_month"], r["series_id"]) for r in ready}) == len(ready)
    assert all(not r["quality_flags"] for r in ready)
    print(json.dumps({k: v for k, v in summary.items() if k not in {"source_manifest", "flag_definitions"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
