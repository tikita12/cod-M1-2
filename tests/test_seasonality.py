"""Check calendar alignment, weighting and exclusion of invalid observations."""

import unittest
from app.services.seasonality import analyze_seasonality, summary_for_month


def row(period, price, variety="A", quantity="1", grade="상품"):
    return {"year_month": period, "average_price": str(price), "item_name": "감자",
            "variety_name": variety, "grade_name": grade, "comparison_quantity": quantity,
            "comparison_unit": "kg", "analysis_eligible": True, "quality_flags": ""}


class SeasonalAnalysisTests(unittest.TestCase):
    def analyze(self, rows, **kwargs):
        return analyze_seasonality(rows, {"감자": "채소"}, start_year=2020, end_year=2024, **kwargs)

    def test_january_uses_december_and_does_not_bridge_missing_month(self):
        result = self.analyze([row("2019-12", 100), row("2020-01", 80), row("2020-03", 60)])
        self.assertEqual(len(result['series_changes']), 1)
        self.assertEqual(result['series_changes'][0]['previous_year_month'], "2019-12")
        self.assertEqual(result['series_changes'][0]['change_pct'], -20)

    def test_variety_grade_and_quantity_must_match(self):
        result = self.analyze([row("2024-10", 100), row("2024-11", 80, variety="B"),
                               row("2024-11", 80, quantity="0.1"), row("2024-11", 80, grade="중품")])
        self.assertEqual(result['series_changes'], [])

    def test_each_year_has_equal_weight(self):
        rows = [row("2020-10", 100), row("2020-11", 80)]
        for variety in ["A", "B", "C"]:
            rows += [row("2021-10", 100, variety), row("2021-11", 110, variety)]
        pattern = self.analyze(rows)['monthly_patterns'][0]
        self.assertEqual(pattern['median_change_pct'], -5)
        self.assertEqual(pattern['drop_frequency_pct'], 50)
        self.assertEqual(pattern['sample_year_count'], 2)
        self.assertFalse(pattern['is_candidate'])

    def test_candidate_threshold_and_summary(self):
        rows = []
        for year, price in zip(range(2020, 2025), [80, 90, 90, 110, 100]):
            rows += [row(f"{year}-10", 100), row(f"{year}-11", price)]
        result = self.analyze(rows)
        summary = summary_for_month(result, 11)
        self.assertEqual(summary['candidate_count'], 1)
        self.assertEqual(summary['candidates'][0]['median_change_pct'], -10)
        self.assertEqual(summary['candidates'][0]['drop_frequency_pct'], 60)
        self.assertEqual(summary['candidates'][0]['rank'], 1)
        with self.assertRaises(ValueError):
            summary_for_month(result, 13)

    def test_review_duplicate_and_nonpositive_prices_rejected(self):
        bad = row("2024-10", 100)
        bad['quality_flags'] = 'conflicting_prices'
        for rows in [[bad], [row("2024-10", 0)], [row("2024-10", 'NaN')],
                     [row("2024-10", 100), row("2024-10", 120)]]:
            with self.assertRaises(ValueError):
                self.analyze(rows)

    def test_out_of_window_and_stale_observations_are_not_candidates(self):
        rows = []
        for year in range(2019, 2023):
            rows += [row(f"{year}-10", 100), row(f"{year}-11", 80)]
        result = self.analyze(rows, min_years=3)
        self.assertEqual(result['monthly_patterns'][0]['sample_years'], [2020, 2021, 2022])
        self.assertFalse(result['monthly_patterns'][0]['has_recent_observation'])
        self.assertEqual(result['rankings']['11'], [])


if __name__ == "__main__":
    unittest.main()
