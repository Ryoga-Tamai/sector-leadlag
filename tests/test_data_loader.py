"""Unit tests for :mod:`src.data_loader` (SECTION 3).

Tests are split into:

* **Offline tests** — exercise the helpers that do not touch the
  network (calendar intersection, cache I/O, gap detection).
* **Network test** — guarded by ``@pytest.mark.network`` so the default
  ``-m "not network"`` run skips it.  Fetches the last ~month of XLK
  from yfinance to confirm the live path still works end-to-end.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.data_loader import (
    FetchPricesError,
    _build_from_yfinance_frame,
    _cache_satisfies,
    _load_cache,
    _max_consecutive_nan_run,
    _save_cache,
    fetch_prices,
    get_common_calendar,
)


def _bdates(n: int, start: str = "2020-01-02") -> pd.DatetimeIndex:
    return pd.bdate_range(start=start, periods=n)


# ---------------------------------------------------------------------------
# get_common_calendar
# ---------------------------------------------------------------------------

def test_common_calendar_keeps_only_all_nonnull_rows():
    idx = _bdates(5)
    close = pd.DataFrame(
        {
            "A": [1.0, np.nan, 3.0, 4.0, 5.0],
            "B": [10.0, 20.0, 30.0, np.nan, 50.0],
            "C": [100.0, 200.0, 300.0, 400.0, 500.0],
        },
        index=idx,
    )

    cal = get_common_calendar(close)

    # Row 0, 2, 4 are fully non-null; rows 1 and 3 each have one NaN.
    assert list(cal) == [idx[0], idx[2], idx[4]]


def test_common_calendar_preserves_order_and_type():
    idx = _bdates(3)
    close = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx)
    cal = get_common_calendar(close)
    assert isinstance(cal, pd.DatetimeIndex)
    assert cal.equals(idx)


def test_common_calendar_rejects_non_dataframe():
    with pytest.raises(TypeError):
        get_common_calendar([1, 2, 3])


def test_common_calendar_rejects_non_datetime_index():
    df = pd.DataFrame({"A": [1.0, 2.0]}, index=[0, 1])
    with pytest.raises(ValueError):
        get_common_calendar(df)


# ---------------------------------------------------------------------------
# _max_consecutive_nan_run
# ---------------------------------------------------------------------------

def test_max_consecutive_nan_run_finds_longest_run():
    s = pd.Series([1.0, np.nan, np.nan, 1.0, np.nan, np.nan, np.nan, 1.0])
    assert _max_consecutive_nan_run(s) == 3


def test_max_consecutive_nan_run_zero_when_no_nan():
    s = pd.Series([1.0, 2.0, 3.0])
    assert _max_consecutive_nan_run(s) == 0


# ---------------------------------------------------------------------------
# cache I/O round-trip
# ---------------------------------------------------------------------------

def test_save_and_load_cache_round_trip(tmp_path):
    idx = _bdates(4)
    tickers = ["XLK", "1617.T"]
    open_df = pd.DataFrame(
        np.arange(8, dtype=float).reshape(4, 2),
        index=idx, columns=tickers,
    )
    close_df = open_df + 0.5
    raw = pd.concat(
        {"Open": open_df, "Close": close_df},
        axis=1, names=["field", "ticker"],
    )
    raw.index.name = "Date"

    path = tmp_path / "cache.csv"
    _save_cache(raw, str(path))
    loaded = _load_cache(str(path))

    pd.testing.assert_frame_equal(loaded, raw, check_freq=False)
    # Index reloaded as DatetimeIndex with the expected name
    assert isinstance(loaded.index, pd.DatetimeIndex)
    assert loaded.index.name == "Date"
    # Columns reloaded as MultiIndex with the expected level names
    assert isinstance(loaded.columns, pd.MultiIndex)
    assert loaded.columns.names == ["field", "ticker"]


# ---------------------------------------------------------------------------
# _cache_satisfies
# ---------------------------------------------------------------------------

def test_cache_satisfies_when_fully_covered():
    idx = _bdates(20, start="2020-01-01")
    cached = pd.DataFrame(
        np.zeros((20, 2)),
        index=idx,
        columns=pd.MultiIndex.from_tuples(
            [("Open", "A"), ("Close", "A")], names=["field", "ticker"]
        ),
    )
    ok, reasons = _cache_satisfies(
        cached,
        start=pd.Timestamp("2020-01-02"),
        effective_end=pd.Timestamp("2020-01-20"),
        tickers=["A"],
        staleness_tol=pd.Timedelta(days=7),
    )
    assert ok is True
    assert reasons == []


def test_cache_satisfies_flags_late_start():
    idx = _bdates(5, start="2020-02-01")
    cached = pd.DataFrame(
        np.zeros((5, 2)),
        index=idx,
        columns=pd.MultiIndex.from_tuples(
            [("Open", "A"), ("Close", "A")], names=["field", "ticker"]
        ),
    )
    ok, reasons = _cache_satisfies(
        cached,
        start=pd.Timestamp("2020-01-01"),
        effective_end=pd.Timestamp("2020-02-07"),
        tickers=["A"],
        staleness_tol=pd.Timedelta(days=7),
    )
    assert ok is False
    assert any("start" in r for r in reasons)


def test_cache_satisfies_flags_missing_tickers():
    idx = _bdates(10, start="2020-01-01")
    cached = pd.DataFrame(
        np.zeros((10, 2)),
        index=idx,
        columns=pd.MultiIndex.from_tuples(
            [("Open", "A"), ("Close", "A")], names=["field", "ticker"]
        ),
    )
    ok, reasons = _cache_satisfies(
        cached,
        start=pd.Timestamp("2020-01-02"),
        effective_end=pd.Timestamp("2020-01-10"),
        tickers=["A", "B"],
        staleness_tol=pd.Timedelta(days=7),
    )
    assert ok is False
    assert any("ticker" in r for r in reasons)


# ---------------------------------------------------------------------------
# fetch_prices — offline path via injected cache
# ---------------------------------------------------------------------------

def test_fetch_prices_reads_from_cache_and_intersects(tmp_path):
    """A pre-populated cache should let fetch_prices return without yfinance."""
    idx = _bdates(6, start="2020-01-02")
    tickers = ["A", "B"]

    # Inject one NaN in A (row 2) and one NaN in B (row 4)
    open_df = pd.DataFrame(
        {
            "A": [1.0, 1.0, np.nan, 1.0, 1.0, 1.0],
            "B": [2.0, 2.0, 2.0, 2.0, np.nan, 2.0],
        },
        index=idx,
    )
    close_df = open_df + 0.1
    raw = pd.concat(
        {"Open": open_df, "Close": close_df},
        axis=1, names=["field", "ticker"],
    )
    raw.index.name = "Date"
    path = tmp_path / "cache.csv"
    _save_cache(raw, str(path))

    od, cd = fetch_prices(
        start_date="2020-01-02",
        end_date="2020-01-09",
        tickers=tickers,
        cache_path=str(path),
        staleness_tol_days=3650,  # never stale for the test
    )

    # Intersection drops the two rows that contain NaN on either side
    assert len(od) == 4
    assert od.index.equals(cd.index)
    assert list(od.columns) == tickers
    assert list(cd.columns) == tickers
    assert not od.isna().values.any()
    assert not cd.isna().values.any()


def test_fetch_prices_rejects_empty_tickers():
    with pytest.raises(ValueError):
        fetch_prices("2020-01-01", "2020-02-01", tickers=[])


def test_fetch_prices_rejects_duplicate_tickers():
    with pytest.raises(ValueError):
        fetch_prices("2020-01-01", "2020-02-01", tickers=["A", "A"])


# ---------------------------------------------------------------------------
# _build_from_yfinance_frame
# ---------------------------------------------------------------------------

def test_build_from_yfinance_multiindex_frame():
    idx = _bdates(3)
    tickers = ["A", "B"]
    cols = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close"], tickers],
        names=["field", "ticker"],
    )
    payload = pd.DataFrame(
        np.arange(3 * len(cols), dtype=float).reshape(3, len(cols)),
        index=idx, columns=cols,
    )

    raw = _build_from_yfinance_frame(payload, tickers)

    assert list(raw.columns.get_level_values("field").unique()) == ["Open", "Close"]
    assert list(raw["Open"].columns) == tickers
    assert list(raw["Close"].columns) == tickers
    assert raw.index.name == "Date"


def test_build_from_yfinance_rejects_missing_open_close():
    idx = _bdates(2)
    cols = pd.MultiIndex.from_product(
        [["High", "Low"], ["A"]], names=["field", "ticker"]
    )
    payload = pd.DataFrame(np.zeros((2, 2)), index=idx, columns=cols)
    with pytest.raises(FetchPricesError):
        _build_from_yfinance_frame(payload, ["A"])


# ---------------------------------------------------------------------------
# Live network test (skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_fetch_prices_xlk_recent_month():
    """End-to-end: fetch ~1 month of XLK from yfinance and sanity-check it."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=45)
    od, cd = fetch_prices(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        tickers=["XLK"],
        cache_path=None,
    )
    assert len(cd) > 10, f"Expected >10 trading days, got {len(cd)}"
    assert list(cd.columns) == ["XLK"]
    assert list(od.columns) == ["XLK"]
    assert od.index.equals(cd.index)
    assert (cd["XLK"] > 0).all()
    assert (od["XLK"] > 0).all()
