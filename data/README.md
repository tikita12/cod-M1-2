# 월별 소매가격 데이터

이 폴더는 공공 CSV를 과제의 가격 분석과 향후 Firestore 적재에 사용할 수 있도록 정리한 결과입니다.
원본에 있는 농축수산물과 가공식품을 모두 보존합니다.
농산물 선별과 과거의 월별 가격 하락 경향 계산을 추가했으며, 미래 가격 예측 모델은 아직 적용하지 않았습니다.

## 다시 실행하기

프로젝트 루트에서 Python으로 실행합니다. 추가 패키지는 필요 없습니다.

```powershell
python scripts/prepare_prices.py --as-of 2026-10-25
```

처음 가져올 때는 `--source-dir`에 CSV 폴더를 지정합니다. 이후에는 `data/raw` 사본을 사용합니다.
같은 이름의 원본 내용이 바뀌면 기존 사본을 덮어쓰지 않고 오류로 알려줍니다.
실행 결과는 `data/processed`와 `reports`에 다시 생성됩니다.

## 가격 한 건의 의미

같은 연월, 품목, 품종, 등급, 판매 수량, 단위의 월평균 소매가격입니다.
`average_price`는 원래 판매 수량에 대한 원화 가격입니다.
`quantity`와 `unit`은 표시용이며, `comparison_quantity`와 `comparison_unit`은 단위 환산 후 비교용입니다.
예를 들어 100g 1,000원은 표시상 100g 1,000원, 비교상 0.1kg 1,000원입니다.
가격을 kg당 가격으로 바꾸지는 않았습니다.

`series_id`는 연월을 제외한 비교 조건의 식별자입니다.
`observation_id`는 비교 조건, 연월, 가격을 조합한 원본 관측 식별자입니다.
가격이 바뀌면 관측 식별자도 바뀌므로 향후 CRUD의 고정 문서 ID는 별도로 설계해야 합니다.
`source_refs`는 원본 파일과 헤더를 포함해 센 행 번호를 담은 JSON입니다.
`source_row_count`는 해당 관측에 합쳐진 원본 행 수입니다.

## 사용 기준

분석에는 `processed/prices_clean.csv`를 사용합니다.
`prices_merged.csv`는 확인 대상까지 포함하므로 그대로 순위를 계산하면 안 됩니다.
날짜·가격 충돌 및 등급 미집계 기록은 `prices_review.csv`에 보존했습니다.
빈 월을 0원이나 보간 가격으로 채우지 않았습니다.
단위별 판매 수량이 다르면 같은 시계열로 합치지 않습니다.

CSV는 Excel에서 한글을 읽을 수 있도록 UTF-8 BOM으로 저장합니다.
앱에서 읽을 때는 `encoding="utf-8-sig"`를 사용하면 됩니다.
자세한 확인 결과는 `../reports/data_quality.md`에 있습니다.

## 농산물 선별과 월별 경향

```powershell
python scripts/analyze_seasonality.py --start-year 2015 --end-year 2024 --target-month 11
```

분류 기준은 `config/item_categories.json`에 있습니다. 미분류 품목이 들어오면 중단해 알립니다.
선별된 자료는 `processed/agricultural_prices.csv`, 분석 근거와 웹 연동용 JSON은 `analysis/`에 저장됩니다.
계산 방식과 한계는 `../reports/seasonality.md`에 있습니다.
