"""Dataset loading, validation and moving-average calculation (no HTTP concerns)."""

import json
import logging
from decimal import Decimal
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

DATA_PATH = Path(__file__).parent / "data" / "input_data.json"
OUTLIER_FACTOR = 2.5  # exclude prices above 2.5x or below 1/2.5 of the instrument median


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON keys, which json.loads would otherwise silently overwrite."""
    keys = [key for key, _ in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"Duplicate keys in data file: {duplicates}")
    return dict(pairs)


def load_raw(path: Path = DATA_PATH) -> pd.DataFrame:
    """Flatten {instrument: [{date, price}, ...]} into rows; non-list keys are metadata."""
    rows = []
    for name, records in json.loads(path.read_text(), object_pairs_hook=_unique_keys).items():
        if not isinstance(records, list):
            continue  # metadata such as "Description"
        for r in records:
            if isinstance(r, dict):
                rows.append({"instrument": name, "date": r.get("date"), "price": r.get("price")})
            else:
                log.warning("Excluded %s record %r: not a {date, price} object", name, r)
    return pd.DataFrame(rows, columns=["instrument", "date", "price"])


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _drop(df: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
    mask = mask.reindex(df.index, fill_value=False)
    for row in df[mask].itertuples():
        day = str(row.date)[:10]
        log.warning("Excluded %s %s (price=%s): %s", row.instrument, day, row.price, reason)
    return df[~mask]


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Validate observations. Never fills, corrects or interpolates; see README for the rules."""
    df = raw.copy()
    df["price"] = pd.to_numeric(df["price"].where(df["price"].map(_is_number)), errors="coerce")
    dates = df["date"].where(df["date"].map(lambda d: isinstance(d, str)))
    parsed = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce")
    df = _drop(df, parsed.isna(), "invalid date")
    df["date"] = parsed[parsed.notna()]
    df = _drop(df, df["date"].dt.day_of_week >= 5, "weekend date")
    df = _drop(df, df["price"].isna(), "missing or non-numeric price")
    df = _drop(df, df["price"] <= 0, "non-positive price")
    median = df.groupby("instrument")["price"].transform("median")
    outlier = (df["price"] > OUTLIER_FACTOR * median) | (df["price"] < median / OUTLIER_FACTOR)
    df = _drop(df, outlier, f"more than {OUTLIER_FACTOR}x from instrument median")

    df = df.drop_duplicates(["instrument", "date", "price"])
    conflicting = df.duplicated(["instrument", "date"], keep=False)
    df = _drop(df, conflicting, "conflicting duplicate prices")
    return df.sort_values(["instrument", "date"]).reset_index(drop=True)


def _exact_trailing_mean(prices: pd.Series, window: int) -> pd.Series:
    """Mean of the last `window` prices in exact decimal arithmetic; None until the window fills.

    Binary floats would store e.g. 104.665 as 104.66499999999999, so rounding it later would be
    wrong. Prices are converted from their shortest decimal form, i.e. as written in the source.
    """
    totals = prices.map(lambda p: Decimal(repr(p))).cumsum()
    means = (totals - totals.shift(window, fill_value=Decimal(0))) / window
    means.iloc[: window - 1] = None
    return means


def moving_average(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Trailing simple moving average over `window` observations, per instrument (as Decimal)."""
    if window < 1:
        raise ValueError("Window must be positive")

    result = df.sort_values(["instrument", "date"]).copy()
    result["moving_average"] = result.groupby("instrument")["price"].transform(
        lambda s: _exact_trailing_mean(s, window)
    )
    return result
