from datetime import time

import pytest

from app import parse_cutoff, parse_price_cents


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("6.50", 650),
        ("6.5", 650),
        (" 2 ", 200),
        ("0", 0),
        ("1000", 100_000),
        ("5.555", 556),  # rounds half up
        ("5.554", 555),
    ],
)
def test_parse_price_cents_accepts_prices(text, cents):
    assert parse_price_cents(text) == cents


@pytest.mark.parametrize(
    "text",
    # Issue #2: inf and huge values used to crash with a 500.
    ["", "abc", "-1", "-0.01", "1000.01", "inf", "-inf", "Infinity", "nan", "1e17", "1e300"],
)
def test_parse_price_cents_rejects_non_prices(text):
    assert parse_price_cents(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("11:30", time(11, 30)),
        ("11:30:00", time(11, 30)),
        ("", None),
        ("   ", None),
        (None, None),
        ("banana", None),
        ("25:00", None),
    ],
)
def test_parse_cutoff(text, expected):
    assert parse_cutoff(text) == expected
