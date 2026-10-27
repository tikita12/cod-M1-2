"""Price cursors retain all sort keys, including timestamp microseconds."""
import re

from google.api_core.datetime_helpers import from_rfc3339, to_rfc3339


def encode_price_cursor(row):
    created_at = row['created_at']
    stamp = to_rfc3339(created_at, ignore_zone=False)
    return f"{row['year_month']}|{stamp}|{row['id']}"


def decode_price_cursor(cursor):
    parts = cursor.split('|')
    if (len(parts) != 3 or not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', parts[0])
            or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z', parts[1])
            or not re.fullmatch(r'[0-9a-f]{64}', parts[2])):
        raise ValueError('Invalid price cursor')
    return parts[0], from_rfc3339(parts[1]), parts[2]
