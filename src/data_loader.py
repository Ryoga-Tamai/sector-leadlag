"""
Production data loader for the US-Japan sector lead-lag strategy (v3).

Encapsulates the SECTION 2A logic (yfinance download → MultiIndex cache
→ common business-day intersection) into a single entry point,
:func:`fetch_prices`, plus a small helper, :func:`get_common_calendar`.

Design rules (requirements_v3.md §3)
-----------------------------------
* yfinance is called with ``auto_adjust=True`` so Open and Close are
  dividend- and split-adjusted.
* Open **and** Close are both returned so :func:`src.returns.compute_oc_returns`
  can compute same-day OC returns downstream.
* The returned ``open_df`` and ``close_df`` share the same
  ``DatetimeIndex`` — the common business-day calendar — and the same
  column order (``ALL_TICKERS`` by default).
* On a fresh fetch the response is persisted to ``cache_path`` as a
  MultiIndex CSV ``(field ∈ {"Open", "Close"}, ticker)`` with a
  two-row header.  This matches the cache format already produced by
  the SECTION 2 notebook so cached files are interchangeable.
* Transient yfinance failures are retried up to three times with
  exponential backoff (1 s → 2 s → 4 s).

This module is the only place where data acquisition I/O lives; the
notebook will be migrated to call ``fetch_prices`` in SECTION 7.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Iterable, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = [
    "fetch_prices",
    "get_common_calendar",
    "FetchPricesError",
]


class FetchPricesError(RuntimeError):
    """Raised when price data cannot be obtained after all retries."""


# ---------------------------------------------------------------------------
# Cache I/O helpers (private)
# ---------------------------------------------------------------------------

def _load_cache(path: str) -> pd.DataFrame:
    """Read a MultiIndex price cache written by :func:`_save_cache`."""
    df = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["field", "ticker"])
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    return df


def _save_cache(df: pd.DataFrame, path: str) -> None:
    """Write the MultiIndex (field, ticker) DataFrame to CSV."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df.to_csv(path)


def _download_with_retry(
    tickers: list[str],
    start: str,
    end: str,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Call ``yfinance.download`` with exponential-backoff retries.

    Sleep schedule: ``2**attempt`` seconds (1, 2, 4) between retries.
    """
    # Import inside the function so importing this module does not pull
    # yfinance (handy for offline unit tests).
    import yfinance as yf

    last_err: Optional[BaseException] = None
    for attempt in range(max_retries):
        try:
            df = yf.download(
                tickers,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="column",
            )
            if df is None or df.empty:
                raise FetchPricesError("yfinance returned an empty DataFrame")
            return df
        except Exception as exc:  # noqa: BLE001 — surface every yfinance failure
            last_err = exc
            wait = 2 ** attempt
            logger.warning(
                "yfinance retry %d/%d failed (%r); sleeping %ds",
                attempt + 1, max_retries, exc, wait,
            )
            time.sleep(wait)
    raise FetchPricesError(
        f"yfinance download failed after {max_retries} retries: {last_err!r}"
    ) from last_err


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_common_calendar(close_df: pd.DataFrame) -> pd.DatetimeIndex:
    """Return the common business-day calendar from a close-price frame.

    A common business day is a date on which **every** column of
    ``close_df`` has a non-null value.  This is the intersection rule
    from requirements_v3.md §3.2.

    Parameters
    ----------
    close_df
        Adjusted-close prices, indexed by ``DatetimeIndex``, one column
        per ticker.

    Returns
    -------
    pd.DatetimeIndex
        Dates on which all columns are non-null, preserving the input
        order.
    """
    if not isinstance(close_df, pd.DataFrame):
        raise TypeError(
            f"close_df must be a pandas DataFrame, got {type(close_df).__name__}"
        )
    if not isinstance(close_df.index, pd.DatetimeIndex):
        raise ValueError(
            f"close_df.index must be a DatetimeIndex, got {type(close_df.index).__name__}"
        )
    mask = close_df.notna().all(axis=1)
    return close_df.index[mask]


def _max_consecutive_nan_run(s: pd.Series) -> int:
    """Length of the longest consecutive NaN run in ``s`` (0 if none)."""
    nan_flags = s.isna().to_numpy().astype(np.int8)
    best = run = 0
    for x in nan_flags:
        run = run + 1 if x else 0
        if run > best:
            best = run
    return int(best)


def _warn_consecutive_gaps(close_raw: pd.DataFrame, tickers: list[str]) -> None:
    """Log a warning for tickers with ≥3-day consecutive NaN runs."""
    gaps = {t: _max_consecutive_nan_run(close_raw[t]) for t in tickers}
    flagged = {t: n for t, n in gaps.items() if n >= 3}
    if flagged:
        logger.warning(
            "tickers with >=3 consecutive NaN in raw Close: %s "
            "(tolerated; intersection removes them)", flagged,
        )


def _build_from_yfinance_frame(
    downloaded: pd.DataFrame,
    tickers: list[str],
) -> pd.DataFrame:
    """Convert a yfinance ``download`` frame into the MultiIndex cache layout."""
    if isinstance(downloaded.columns, pd.MultiIndex):
        fields = downloaded.columns.get_level_values(0).unique().tolist()
        if "Open" not in fields or "Close" not in fields:
            raise FetchPricesError(
                f"Expected Open & Close columns from yfinance; got fields={fields}"
            )
        open_df = downloaded["Open"][tickers].copy()
        close_df = downloaded["Close"][tickers].copy()
    else:
        # Single-ticker shortcut — yfinance returns flat columns
        if "Open" not in downloaded.columns or "Close" not in downloaded.columns:
            raise FetchPricesError(
                "Single-ticker frame lacks Open/Close columns"
            )
        open_df = downloaded[["Open"]].copy()
        open_df.columns = tickers
        close_df = downloaded[["Close"]].copy()
        close_df.columns = tickers

    raw = pd.concat(
        {"Open": open_df, "Close": close_df},
        axis=1,
        names=["field", "ticker"],
    )
    raw.index = pd.to_datetime(raw.index)
    raw.index.name = "Date"
    return raw


def _cache_satisfies(
    cached: pd.DataFrame,
    start: pd.Timestamp,
    effective_end: pd.Timestamp,
    tickers: list[str],
    staleness_tol: pd.Timedelta,
) -> tuple[bool, list[str]]:
    """Return ``(usable, reasons)`` describing whether ``cached`` covers the request.

    The same ``staleness_tol`` is applied symmetrically to both ends — markets
    are typically closed for the first few calendar days of January (so a cache
    starting on 2010-01-04 still "covers" a request for 2010-01-01), and we
    accept a similar lag at the upper bound.
    """
    reasons: list[str] = []
    cached_start = cached.index.min()
    cached_end = cached.index.max()
    if cached_start > (start + staleness_tol):
        reasons.append(f"start>{(start + staleness_tol).date()}")
    if cached_end < (effective_end - staleness_tol):
        reasons.append(f"end<{(effective_end - staleness_tol).date()}")
    cached_tickers = set(cached.columns.get_level_values("ticker"))
    if not set(tickers).issubset(cached_tickers):
        reasons.append("tickers missing")
    return (len(reasons) == 0, reasons)


def fetch_prices(
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    tickers: Optional[Iterable[str]] = None,
    cache_path: Optional[str] = None,
    staleness_tol_days: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch adjusted Open / Close prices on the common business-day calendar.

    Mirrors SECTION 2A of ``notebooks/01_paper_replication.ipynb`` so
    production callers get a frame that is byte-identical (modulo
    yfinance refresh) to what the notebook computed.

    Parameters
    ----------
    start_date, end_date
        Inclusive request range.  ``end_date`` may exceed today, in
        which case it is clipped to today (``end_date`` is also padded
        by one calendar day before being passed to yfinance, whose
        ``end`` argument is exclusive).
    tickers
        Iterable of tickers in the desired column order.  When
        ``None``, :data:`src.universe.ALL_TICKERS` is used (the
        production default).
    cache_path
        Optional path to a MultiIndex CSV cache.  If set, the cache is
        consulted first and written on a fresh fetch.
    staleness_tol_days
        How many calendar days the cache may lag behind ``end_date``
        before triggering a refetch.  Default 7 (covers weekends and
        most JP/US holiday clusters).

    Returns
    -------
    (open_df, close_df)
        Adjusted Open and Close on the common business-day calendar.
        Both frames share index and column order.  No NaN in either.

    Raises
    ------
    FetchPricesError
        When yfinance fails after all retries or returns insufficient
        data.
    """
    # Resolve tickers without importing universe at module load time
    if tickers is None:
        from src.universe import ALL_TICKERS  # local import keeps deps light
        tickers_list = list(ALL_TICKERS)
    else:
        tickers_list = list(tickers)
    if len(tickers_list) == 0:
        raise ValueError("tickers must contain at least one ticker")
    if len(set(tickers_list)) != len(tickers_list):
        raise ValueError("tickers must be unique")

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    today_ts = pd.Timestamp(pd.Timestamp.today().normalize())
    effective_end = min(end_ts, today_ts)
    staleness_tol = pd.Timedelta(days=staleness_tol_days)

    raw: Optional[pd.DataFrame] = None

    if cache_path and os.path.exists(cache_path):
        try:
            cached = _load_cache(cache_path)
            usable, reasons = _cache_satisfies(
                cached, start_ts, effective_end, tickers_list, staleness_tol
            )
            if usable:
                logger.info(
                    "Using cache: %s (%s … %s, rows=%d)",
                    cache_path, cached.index.min().date(),
                    cached.index.max().date(), len(cached),
                )
                raw = cached
            else:
                logger.info(
                    "Cache exists but is stale (%s); refetching.", ", ".join(reasons)
                )
        except Exception as exc:  # noqa: BLE001 — fall back to a fresh download
            logger.warning("Cache read failed (%r); refetching.", exc)

    if raw is None:
        fetch_start = start_ts.strftime("%Y-%m-%d")
        fetch_end = (effective_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(
            "Downloading %d tickers from yfinance: %s … %s",
            len(tickers_list), fetch_start, fetch_end,
        )
        downloaded = _download_with_retry(tickers_list, fetch_start, fetch_end)
        raw = _build_from_yfinance_frame(downloaded, tickers_list)
        if cache_path:
            _save_cache(raw, cache_path)
            logger.info("Cache written: %s (%d rows)", cache_path, len(raw))

    # Slice to the requested range (cache may extend further than the request)
    raw = raw.loc[(raw.index >= start_ts) & (raw.index <= effective_end)]
    if raw.empty:
        raise FetchPricesError(
            f"No rows in requested range {start_ts.date()} … {effective_end.date()}"
        )

    open_raw = raw["Open"][tickers_list].copy()
    close_raw = raw["Close"][tickers_list].copy()

    # Gap audit BEFORE intersection (requirements_v3 §3.3)
    _warn_consecutive_gaps(close_raw, tickers_list)

    # Common business-day intersection: every ticker's Close non-null.
    common_dates = get_common_calendar(close_raw)
    close_df = close_raw.loc[common_dates].copy()
    open_df = open_raw.loc[common_dates].copy()

    # Open may still have NaN on dates where every Close is non-null;
    # in that case intersect again with Open availability.
    open_nan = int(open_df.isna().sum().sum())
    if open_nan > 0:
        logger.info(
            "%d Open cells NaN on common-Close dates; intersecting Open too.", open_nan,
        )
        both_ok = open_df.notna().all(axis=1) & close_df.notna().all(axis=1)
        common_dates = close_df.index[both_ok]
        close_df = close_df.loc[common_dates].copy()
        open_df = open_df.loc[common_dates].copy()

    if close_df.empty:
        raise FetchPricesError("No common business days after intersection")
    if open_df.isna().values.any() or close_df.isna().values.any():
        raise FetchPricesError("Open/Close still contains NaN after intersection")

    return open_df, close_df
