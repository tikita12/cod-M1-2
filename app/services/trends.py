"""Actual monthly prices, separated by variety, grade and sale quantity."""
from collections import defaultdict
from decimal import Decimal


def build_trends(records):
    groups = defaultdict(dict)
    for row in records:
        key = (row['item_name'], row['variety_name'], row['grade_name'],
               str(Decimal(str(row['comparison_quantity'])).normalize()), row['comparison_unit'])
        groups[key][row['year_month']] = float(row['average_price'])
    result = defaultdict(list)
    for key, observations in sorted(groups.items()):
        year = max(observations)[:4]
        quantity = format(Decimal(key[3]), 'f')
        result[key[0]].append({
            'variety_name': key[1], 'grade_name': key[2], 'quantity': quantity,
            'unit': key[4], 'year': int(year),
            'points': [{'month': m, 'price': observations.get(f'{year}-{m:02d}')}
                       for m in range(1, 13)],
            'history': [{'year': int(period[:4]), 'month': int(period[5:]), 'price': price}
                        for period, price in sorted(observations.items())]})
    for series in result.values():
        series.sort(key=lambda s: (-s['year'], -sum(p['price'] is not None for p in s['points']),
                                   s['variety_name'], s['grade_name'], s['quantity'], s['unit']))
    return dict(result)
