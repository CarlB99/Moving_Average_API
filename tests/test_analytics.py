import json
from decimal import Decimal

import pandas as pd
import pytest

from app.analytics import clean, load_raw, moving_average


def frame(rows):
    df = pd.DataFrame(rows, columns=["instrument", "date", "price"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def weekdays(n, start="2024-01-01"):
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, periods=n)]


def test_known_values_and_incomplete_window():
    df = frame([("A", d, p) for d, p in zip(weekdays(4), [1.0, 2.0, 3.0, 4.0], strict=True)])
    ma = moving_average(df, 2)["moving_average"].tolist()
    assert ma[0] is None
    assert ma[1:] == [Decimal("1.5"), Decimal("2.5"), Decimal("3.5")]


def test_window_one_equals_price_and_window_too_large_is_all_null():
    df = frame([("A", d, p) for d, p in zip(weekdays(3), [5.0, 6.0, 7.0], strict=True)])
    assert moving_average(df, 1)["moving_average"].tolist() == [5.0, 6.0, 7.0]
    assert moving_average(df, 4)["moving_average"].isna().all()


def test_invalid_window_raises():
    with pytest.raises(ValueError):
        moving_average(frame([]), 0)


def test_instruments_are_independent_and_unsorted_input_is_sorted():
    days = weekdays(3)
    rows = [("B", days[2], 30.0), ("A", days[1], 2.0), ("B", days[0], 10.0)]
    rows += [("A", days[0], 1.0), ("B", days[1], 20.0), ("A", days[2], 3.0)]
    out = moving_average(frame(rows), 3)
    assert out["instrument"].tolist() == ["A"] * 3 + ["B"] * 3
    assert out.groupby("instrument")["moving_average"].last().tolist() == [2.0, 20.0]


def test_average_is_exact_decimal_not_binary_float():
    # floats give (104.67 + 104.66) / 2 = 104.66499999999999, which would round down to 104.66
    df = frame([("A", d, p) for d, p in zip(weekdays(2), [104.67, 104.66], strict=True)])
    assert moving_average(df, 2)["moving_average"].iloc[1] == Decimal("104.665")


def test_constant_price_series():
    df = frame([("A", d, 42.0) for d in weekdays(10)])
    assert (moving_average(df, 5)["moving_average"].dropna() == 42.0).all()


def test_no_look_ahead():
    days = weekdays(8)
    base = frame([("A", d, float(i)) for i, d in enumerate(days[:5])])
    extended = frame([("A", d, float(i * 7)) for i, d in enumerate(days)])
    extended.loc[:4, "price"] = base["price"]
    before = moving_average(base, 3)["moving_average"]
    after = moving_average(extended, 3)["moving_average"].iloc[:5]
    pd.testing.assert_series_equal(before, after)


def raw(rows):
    return pd.DataFrame(rows, columns=["instrument", "date", "price"])


def test_clean_excludes_invalid_records():
    d = weekdays(5)
    out = clean(
        raw(
            [
                ("A", "2024-02-31", 10.0),  # invalid date
                ("A", "2024-01-06", 10.0),  # Saturday
                ("A", d[0], None),  # missing price
                ("A", d[0], 11.0),  # duplicate with a price -> kept
                ("A", d[1], 12.0),
                ("A", d[1], 12.0),  # exact duplicate -> kept once
                ("A", d[2], 13.0),
                ("A", d[2], 14.0),  # conflicting -> both excluded
                ("A", d[3], 0.0),  # zero price
            ]
        )
    )
    assert out["price"].tolist() == [11.0, 12.0]


def test_negative_and_outlier_prices_excluded():
    prices = [100.0, -101.0, 100.0, 1020.0, 30.0, 240.0, 100.0]
    out = clean(raw([("A", d, p) for d, p in zip(weekdays(7), prices, strict=True)]))
    # median of positive prices is 100: 1020 (>250) and 30 (<40) excluded, 240 kept
    assert out["price"].tolist() == [100.0, 100.0, 240.0, 100.0]


def test_load_raw_skips_metadata_and_malformed_records(tmp_path):
    path = tmp_path / "data.json"
    records = [{"date": "2024-01-01", "price": 1}, "junk", 42, None]
    path.write_text(json.dumps({"Description": "x", "I1": records}))
    assert load_raw(path).to_dict("records") == [
        {"instrument": "I1", "date": "2024-01-01", "price": 1}
    ]


def test_clean_rejects_wrongly_typed_values():
    d = weekdays(5)
    rows = [("A", d[0], 100.0), ("A", d[1], True), ("A", d[2], "101.0"), ("A", d[3], [1])]
    rows += [("A", 20240105, 100.0)]  # date must be a "YYYY-MM-DD" string
    assert clean(raw(rows))["price"].tolist() == [100.0]


def test_supplied_dataset_counts():
    df = load_raw()
    assert clean(df).groupby("instrument").size().to_dict() == {"Inst1": 512, "Inst2": 509}
