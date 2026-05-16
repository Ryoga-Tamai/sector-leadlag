"""
Return-series helpers for the US-Japan sector lead-lag strategy (v3).

Two return definitions are used:

* **Close-to-Close (CC)** — used as the PCA estimation input
  (requirements_v3.md §2.4).  Computed from adjusted close prices
  (yfinance ``auto_adjust=True``).
* **Open-to-Close (OC)** — used to evaluate strategy P/L on the Japan
  side.  Computed from same-day adjusted Open and Close.

Both helpers mirror the exact pandas operations used in the SECTION 2
backtest notebook (``notebooks/01_paper_replication.ipynb`` cells 6 and
7) so the SECTION 4 ``test_generate_signal_matches_backtest`` test can
compare production output against the notebook bit-for-bit.

Index / column conventions
--------------------------
* ``prices_close`` and ``prices_open`` are indexed by the common
  business-day ``pd.DatetimeIndex`` returned by
  :func:`src.data_loader.get_common_calendar`.
* Column order is preserved verbatim.  Callers are expected to feed
  either ``ALL_TICKERS`` order (CC) or ``JP_TICKERS`` order (OC).
"""

from __future__ import annotations

import pandas as pd

__all__ = ["compute_cc_returns", "compute_oc_returns"]


def compute_cc_returns(prices_close: pd.DataFrame) -> pd.DataFrame:
    """Compute close-to-close (CC) returns.

    Equivalent to ``prices_close.pct_change()``.  The first row is NaN
    by definition; subsequent rows must not contain NaN when
    ``prices_close`` is on the common business-day calendar.

    Parameters
    ----------
    prices_close
        Adjusted-close prices.  Index must be a ``DatetimeIndex``;
        columns are tickers in the order chosen by the caller.

    Returns
    -------
    pd.DataFrame
        Same shape as ``prices_close``.  ``out.iloc[0]`` is all NaN;
        ``out.iloc[t, i] = prices_close.iloc[t, i] / prices_close.iloc[t-1, i] - 1``.

    Raises
    ------
    TypeError
        If ``prices_close`` is not a ``DataFrame``.
    ValueError
        If ``prices_close`` is empty or has a non-``DatetimeIndex``.
    """
    if not isinstance(prices_close, pd.DataFrame):
        raise TypeError(
            f"prices_close must be a pandas DataFrame, got {type(prices_close).__name__}"
        )
    if prices_close.empty:
        raise ValueError("prices_close is empty")
    if not isinstance(prices_close.index, pd.DatetimeIndex):
        raise ValueError(
            f"prices_close.index must be a DatetimeIndex, got {type(prices_close.index).__name__}"
        )

    # fill_method=None propagates NaN instead of silently forward-filling
    # (the default pandas behavior emits a FutureWarning and would mask
    # missing prices, defeating downstream NaN checks in generate_signal).
    # For clean (post-intersection) inputs the output is identical to
    # pct_change()'s legacy default, preserving SECTION 2 parity.
    return prices_close.pct_change(fill_method=None)


def compute_oc_returns(
    prices_open: pd.DataFrame,
    prices_close: pd.DataFrame,
) -> pd.DataFrame:
    """Compute open-to-close (OC) returns.

    ``r_oc[j, t] = Close[j, t] / Open[j, t] - 1``.  Because dividend and
    split adjustments scale the entire day's OHLC by the same factor,
    the Close/Open ratio is invariant to ``auto_adjust`` — the raw
    adjusted Open and Close from yfinance can be used directly
    (requirements_v3.md §2.4).

    The two inputs must share the same index and column order
    (typically the common business-day calendar and ``JP_TICKERS``).

    Parameters
    ----------
    prices_open
        Adjusted-open prices, indexed by common business days.
    prices_close
        Adjusted-close prices, same index and columns as
        ``prices_open``.

    Returns
    -------
    pd.DataFrame
        OC returns, same shape as the inputs.  Must contain no NaN.

    Raises
    ------
    TypeError
        If either input is not a ``DataFrame``.
    ValueError
        If the inputs are empty, have mismatched index/columns, or the
        result contains NaN (which signals an alignment bug upstream).
    """
    if not isinstance(prices_open, pd.DataFrame) or not isinstance(prices_close, pd.DataFrame):
        raise TypeError("prices_open and prices_close must both be pandas DataFrames")
    if prices_open.empty or prices_close.empty:
        raise ValueError("prices_open / prices_close must be non-empty")
    if not prices_open.index.equals(prices_close.index):
        raise ValueError("prices_open and prices_close must share the same index")
    if list(prices_open.columns) != list(prices_close.columns):
        raise ValueError("prices_open and prices_close must share identical column order")

    oc = prices_close / prices_open - 1.0

    if oc.isna().values.any():
        n_nan = int(oc.isna().sum().sum())
        raise ValueError(
            f"OC returns contain {n_nan} NaN cell(s); "
            "Open and Close must both be non-null on every common business day"
        )

    return oc
