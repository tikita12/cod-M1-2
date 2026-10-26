"""Filter agricultural ingredients and calculate historical seasonal patterns."""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.seasonality import analyze_seasonality, summary_for_month


def write_csv(path, rows, fields=None):
    if fields is None:
        fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--target-month", type=int, default=11)
    args = parser.parse_args()
    config_path = ROOT / "data/config/item_categories.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    included = {item: category for category, items in config["included_categories"].items() for item in items}
    excluded = {item: category for category, items in config["excluded_categories"].items() for item in items}
    all_names = [item for group in (config['included_categories'], config['excluded_categories'])
                 for items in group.values() for item in items]
    if len(all_names) != len(set(all_names)):
        raise ValueError("품목 분류가 중복됩니다")
    with (ROOT / "data/processed/prices_clean.csv").open(encoding="utf-8-sig", newline="") as f:
        records = list(csv.DictReader(f))
    unknown = {r['item_name'] for r in records} - included.keys() - excluded.keys()
    if unknown:
        raise ValueError("분류가 필요한 신규 품목: " + ", ".join(sorted(unknown)))
    selected = [{**r, "category": included[r['item_name']]} for r in records if r['item_name'] in included]
    if not selected:
        raise ValueError("선별된 농산물이 없습니다")
    latest = max(r['year_month'] for r in selected)
    if args.end_year > int(latest[:4]):
        raise ValueError("마지막 관측 연도 이후를 분석 종료 연도로 지정할 수 없습니다")
    analysis = analyze_seasonality(selected, included, start_year=args.start_year, end_year=args.end_year)
    analysis['metadata'].update(
        source_start=min(r['year_month'] for r in selected), source_end=latest,
        selected_item_count=len({r['item_name'] for r in selected}),
        category_definition=config['description'],
        data_note="2025년 자료 누락, 2026년 연월 확인 필요로 제외. 2021년 8월 일부 가격 충돌 기록 제외.",
    )
    summary = summary_for_month(analysis, args.target_month)
    out = ROOT / "data/analysis"
    out.mkdir(parents=True, exist_ok=True)
    write_csv(ROOT / "data/processed/agricultural_prices.csv", selected)
    write_csv(out / "series_monthly_changes.csv", analysis['series_changes'])
    write_csv(out / "item_yearly_changes.csv", analysis['item_year_changes'])
    write_csv(out / "monthly_patterns.csv", analysis['monthly_patterns'])
    payload = {"metadata": analysis['metadata'], "monthly_patterns": analysis['monthly_patterns'],
               "rankings": analysis['rankings']}
    (out / "seasonal_rankings.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = Counter(r['item_name'] for r in records)
    write_csv(out / "item_selection.csv", [
        {"item_name": item, "category": included.get(item) or excluded[item],
         "included": item in included, "row_count": count} for item, count in sorted(counts.items())])
    lines = ["# 농산물의 월별 가격 하락 경향", "",
             f"분석 대상 월의 연도: {args.start_year}~{args.end_year}. 1월 비교에는 직전 연도 12월도 사용합니다.",
             f"농산물 선별: {len({r['item_name'] for r in selected})}품목, {len(selected):,}행.",
             f"같은 조건으로 연결한 전월→대상 월 비교: {len(analysis['series_changes']):,}쌍.",
             "", "## 계산 기준", "",
             "1. 품목·품종·등급·판매 수량·단위가 모두 같은 두 달을 연결합니다. 월이 건너뛰면 연결하지 않습니다.",
             "2. (대상 월 가격 ÷ 전월 가격 − 1) × 100으로 변화율을 계산합니다.",
             "3. 같은 품목·연도·대상 월에 여러 품종/등급이 있으면 변화율 중앙값을 구합니다.",
             "4. 각 연도를 동일하게 취급하여 연도별 변화율의 중앙값과 하락한 해의 비율을 구합니다.",
             "5. 비교 연도 5개 이상, 마지막 2개 연도 중 관측 존재, 중앙값 음수, 과거 하락 비율 60% 이상을 후보로 선정합니다.",
             "6. 중앙값이 낮은 순서로 정렬합니다. 이는 관측된 하락 폭을 기준으로 한 순위입니다.",
             "", "과거 하락 비율은 여러 해 중 품목별 중앙값이 음수인 해의 비율입니다. 미래 하락 확률은 아닙니다.",
             "품종·등급을 바꿔 두 가격을 직접 비교하지는 않지만, 연도마다 비교에 참여하는 품종·등급은 달라질 수 있습니다.",
             "", "## 데이터 범위와 제한", "",
             "1996~2024년 선별 자료를 보존하고, 분석에는 최근 확보된 10년(2015~2024년)을 기본으로 사용합니다.",
             "2025년 자료는 없고 2026년 자료는 날짜 확인이 필요해 현재 예측의 정확도를 검증할 수 없습니다.",
             "2021년 8월 일부 품목이 빠져 8월 및 9월 비교 표본이 줄어듭니다. 비수기 결측도 0원으로 채우지 않습니다.",
             "시즌에만 거래되어 전월 기록이 없는 품목은 이 방식에서 제외될 수 있습니다.",
             "분류는 프로젝트용 수동 분류이며 수입 농산물, 콩나물, 버섯, 건조·분쇄 농산물도 포함합니다.",
             "축산물·수산물·소금·가공식품은 제외했습니다. 분류표는 data/config/item_categories.json입니다.",
             "날씨·생산량·수요·최근 가격을 반영한 예측 모델은 아직 구축하지 않았습니다.",
             "", f"## {summary['previous_month']}월 → {args.target_month}월 예시", ""]
    for row in summary['candidates']:
        lines.append(f"- {row['rank']}위 {row['item_name']}: 과거 변화율 중앙값 {row['median_change_pct']:.1f}%, "
                     f"{row['sample_year_count']}년 중 {row['drop_year_count']}년 하락")
    if not summary['candidates']:
        lines.append("선정 기준을 만족하는 품목이 없습니다.")
    lines += ["", "## 웹 서비스 연결", "",
              "분석 함수는 app/services/seasonality.py에 있어 FastAPI 서비스에서 재사용할 수 있습니다.",
              "data/analysis/seasonal_rankings.json에는 1~12월별 후보와 근거가 있습니다.",
              "summary.json은 선택한 월의 챗봇 컨텍스트 및 /api/data/summary 응답 형식의 초안입니다.",
              "이 파일들은 정적 분석 결과입니다. 실제 API는 Firestore에서 데이터를 조회하여 같은 분석 서비스를 호출합니다.",
              "API 설정 및 실제 연결 확인 방법은 docs/backend.md를 참조하세요. 채팅·화면·배포는 후속 단계입니다.",
              "웹에서는 '계절별 하락 경향'과 분석 기간·표본 수를 함께 표시해야 합니다.",
              "데이터 추가·수정·삭제 시 같은 서비스를 다시 실행해 요약을 갱신하도록 연결할 예정입니다.", ""]
    (ROOT / "reports/seasonality.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"selected_rows": len(selected), "selected_items": len({r['item_name'] for r in selected}),
                      "paired_changes": len(analysis['series_changes']),
                      "monthly_candidate_counts": {m: len(rows) for m, rows in analysis['rankings'].items()},
                      "example": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
