"""Unit tests for :mod:`src.returns` (SECTION 3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.returns import compute_cc_returns, compute_oc_returns


def _bdates(n: int, start: str = "2020-01-02") -> pd.DatetimeIndex:
    """Return ``n`` consecutive business days starting at ``start``."""
    return pd.bdate_range(start=start, periods=n)


# ---------------------------------------------------------------------------
# compute_cc_returns
# ---------------------------------------------------------------------------

def test_compute_cc_returns_matches_hand_calc():
    """CC returns must equal `close.pct_change()` to numerical precision."""
    idx = _bdates(4)
    close = pd.DataFrame(
        {
            "A": [100.0, 110.0, 121.0, 132.0],
            "B": [50.0, 48.0, 60.0, 54.0],
        },
        index=idx,
    )

    out = compute_cc_returns(close)

    # First row is all NaN by definition
    assert out.iloc[0].isna().all()

    # Subsequent rows: pct change, hand-verified
    expected_A = np.array([np.nan, 0.10, 0.10, 132.0 / 121.0 - 1.0])
    expected_B = np.array([np.nan, 48.0 / 50.0 - 1.0, 60.0 / 48.0 - 1.0, 54.0 / 60.0 - 1.0])
    np.testing.assert_allclose(out["A"].values, expected_A, rtol=1e-12, equal_nan=True)
    np.testing.assert_allclose(out["B"].values, expected_B, rtol=1e-12, equal_nan=True)

    # Shape, index, and column order preserved
    assert out.shape == close.shape
    assert out.index.equals(close.index)
    assert list(out.columns) == list(close.columns)


def test_compute_cc_returns_no_nan_after_first_row():
    """When inputs are clean, only the first row of CC should be NaN."""
    idx = _bdates(50)
    rng = np.random.default_rng(123)
    # Synthetic positive prices via cumulative product of small returns
    rets = rng.normal(loc=0.0, scale=0.01, size=(50, 5))
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    close = pd.DataFrame(prices, index=idx, columns=list("VWXYZ"))

    out = compute_cc_returns(close)

    assert out.iloc[0].isna().all()
    assert not out.iloc[1:].isna().values.any()


def test_compute_cc_returns_rejects_non_dataframe():
    with pytest.raises(TypeError):
        compute_cc_returns([1, 2, 3])


def test_compute_cc_returns_rejects_non_datetime_index():
    df = pd.DataFrame({"A": [1.0, 2.0]}, index=[0, 1])
    with pytest.raises(ValueError):
        compute_cc_returns(df)


# ---------------------------------------------------------------------------
# compute_oc_returns
# ---------------------------------------------------------------------------

def test_compute_oc_returns_matches_hand_calc():
    """OC returns must equal `close/open - 1` element-wise."""
    idx = _bdates(3)
    open_df = pd.DataFrame(
        {"A": [100.0, 110.0, 120.0], "B": [50.0, 51.0, 52.0]},
        index=idx,
    )
    close_df = pd.DataFrame(
        {"A": [102.0, 108.0, 126.0], "B": [49.5, 53.0, 52.0]},
        index=idx,
    )

    out = compute_oc_returns(open_df, close_df)

    expected_A = np.array([102.0 / 100.0 - 1.0, 108.0 / 110.0 - 1.0, 126.0 / 120.0 - 1.0])
    expected_B = np.array([49.5 / 50.0 - 1.0, 53.0 / 51.0 - 1.0, 52.0 / 52.0 - 1.0])
    np.testing.assert_allclose(out["A"].values, expected_A, rtol=1e-12)
    np.testing.assert_allclose(out["B"].values, expected_B, rtol=1e-12)
    assert out.shape == open_df.shape
    assert out.index.equals(open_df.index)
    assert list(out.columns) == list(open_df.columns)


def test_compute_oc_returns_no_nan():
    """OC must not produce NaN when both inputs are fully populated."""
    idx = _bdates(20)
    rng = np.random.default_rng(7)
    op = pd.DataFrame(100 + rng.normal(0, 1, (20, 3)), index=idx, columns=list("XYZ"))
    cl = pd.DataFrame(100 + rng.normal(0, 1, (20, 3)), index=idx, columns=list("XYZ"))

    out = compute_oc_returns(op, cl)

    assert not out.isna().values.any()


def test_compute_oc_returns_raises_on_index_mismatch():
    op = pd.DataFrame({"A": [100.0]}, index=_bdates(1, "2020-01-02"))
    cl = pd.DataFrame({"A": [101.0]}, index=_bdates(1, "2020-01-03"))
    with pytest.raises(ValueError, match="index"):
        compute_oc_returns(op, cl)


def test_compute_oc_returns_raises_on_column_mismatch():
    idx = _bdates(2)
    op = pd.DataFrame({"A": [100.0, 100.0], "B": [50.0, 50.0]}, index=idx)
    cl = pd.DataFrame({"B": [50.0, 50.0], "A": [101.0, 101.0]}, index=idx)  # reordered
    with pytest.raises(ValueError, match="column"):
        compute_oc_returns(op, cl)


def test_compute_oc_returns_raises_on_nan_input():
    idx = _bdates(2)
    op = pd.DataFrame({"A": [100.0, np.nan]}, index=idx)
    cl = pd.DataFrame({"A": [101.0, 102.0]}, index=idx)
    with pytest.raises(ValueError, match="NaN"):
        compute_oc_returns(op, cl)
