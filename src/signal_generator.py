"""
Daily signal generator for the US-Japan sector lead-lag strategy (v3).

The single-day computation in :func:`generate_signal` is a 1:1 port of
the SECTION 2C backtest loop in
``notebooks/01_paper_replication.ipynb`` (cell 11).  Both paths follow
the same index convention, the same window-statistics rule, and the
same ranking rule so that
``tests/test_signal_generator.py::test_generate_signal_matches_backtest``
can prove the two implementations are bit-identical.

Inputs come from :mod:`src.data_loader` (open / close on the common
business-day calendar) and the prior correlation ``C0`` built via
:func:`src.pca_engine.build_target_correlation` on top of
``data/prior/C_full.npy``.

Look-ahead safety
-----------------
* The estimation window for date ``t`` is ``cc_returns.iloc[t-L : t]``
  — strictly *before* ``t``.  ``t`` itself is **never** used to compute
  the window mean / std.
* Today's US returns are standardised with the window statistics, not
  with ``t``-inclusive statistics.
* The function returns the signal for ``t+1``; it intentionally does
  **not** consume or look at any data dated after ``t``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from src.pca_engine import (
    compute_regularized_correlation,
    extract_top_eigenvectors,
)
from src.returns import compute_cc_returns
from src.universe import (
    ALL_TICKERS,
    JP_TICKERS,
    N_JP,
    N_TOTAL,
    N_US,
    US_TICKERS,
)

__all__ = [
    "SignalConfig",
    "generate_signal",
    "load_prior_correlation",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalConfig:
    """Hyperparameters for :func:`generate_signal`.

    Defaults mirror requirements_v3.md §2.2 (L=60, K=3, λ=0.9, q=0.3).
    With ``q=0.3`` and ``N_JP=17``, the long / short baskets contain
    ``floor(N_JP * q) = 5`` tickers each.
    """

    window_length: int = 60
    n_components: int = 3
    lambda_reg: float = 0.9
    quantile: float = 0.3

    def basket_size(self, n_jp: int = N_JP) -> int:
        """Number of tickers per long / short basket.

        Uses ``floor(n_jp * quantile)`` to match SECTION 2C, where
        ``Q_LONG = Q_SHORT = 5`` for ``17 * 0.3 = 5.1``.
        """
        return int(np.floor(n_jp * self.quantile))


# ---------------------------------------------------------------------------
# Prior correlation I/O
# ---------------------------------------------------------------------------

def load_prior_correlation(path: str) -> np.ndarray:
    """Load the pre-computed long-run correlation ``C_full`` from a ``.npy`` file.

    Parameters
    ----------
    path
        Path to the ``.npy`` file (typically ``data/prior/C_full.npy``).

    Returns
    -------
    np.ndarray
        Square matrix of shape ``(N_TOTAL, N_TOTAL)``, dtype float.

    Raises
    ------
    ValueError
        If the file is missing or the loaded array is not the expected
        shape.
    """
    if not os.path.exists(path):
        raise ValueError(f"Prior correlation file not found: {path}")
    arr = np.load(path)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"Expected square matrix, got shape {arr.shape}")
    if arr.shape != (N_TOTAL, N_TOTAL):
        raise ValueError(
            f"Expected shape ({N_TOTAL}, {N_TOTAL}), got {arr.shape}"
        )
    return arr.astype(float)


# ---------------------------------------------------------------------------
# Core single-day signal
# ---------------------------------------------------------------------------

def generate_signal(
    open_df: pd.DataFrame,
    close_df: pd.DataFrame,
    target_date: pd.Timestamp | str,
    C0: np.ndarray,
    config: Optional[SignalConfig] = None,
) -> dict:
    """Generate a one-day signal for ``target_date``.

    This is a 1:1 port of the SECTION 2C backtest loop body
    (cell 11 of ``notebooks/01_paper_replication.ipynb``).  Given price
    data on the common business-day calendar, it computes:

    1. ``W_t = cc_returns.iloc[t-L : t]`` (``t`` exclusive).
    2. Window statistics ``mu_w``, ``sigma_w`` (``ddof=1``) and the
       window correlation ``C_t = Z_w.T @ Z_w / (L-1)`` where
       ``Z_w = (W - mu_w) / sigma_w``.
    3. Regularised correlation ``C_reg = (1-λ) C_t + λ C0``, top-K
       eigenvectors split into US / JP blocks ``V_U`` and ``V_J``.
    4. Today's US returns standardised with the **window** statistics
       (never with ``t``-inclusive statistics) → ``z_us_t``.
    5. Factor scores ``f_t = V_U.T @ z_us_t``; predicted JP signal
       ``signal_jp = V_J @ f_t``.
    6. Long basket = top-``Q`` JP tickers by ``signal_jp``; short
       basket = bottom-``Q``, with ``Q = floor(N_JP * quantile)``.

    Parameters
    ----------
    open_df, close_df
        Adjusted Open / Close on the common business-day calendar
        (see :func:`src.data_loader.fetch_prices`).  Columns must
        include all 26 tickers; only ``ALL_TICKERS`` order is used
        downstream.
    target_date
        Signal date ``t``.  Must be a common business day at index
        ``≥ window_length`` (otherwise the window is undefined).
    C0
        Prior correlation matrix, shape ``(N_TOTAL, N_TOTAL)``.
    config
        Hyperparameters; defaults to :class:`SignalConfig()`.

    Returns
    -------
    dict
        Keys:

        * ``"date"`` — ``pd.Timestamp`` of ``t``
        * ``"long_basket"`` — list of JP tickers (top ``Q``)
        * ``"short_basket"`` — list of JP tickers (bottom ``Q``)
        * ``"all_scores"`` — ``pd.Series`` indexed by ``JP_TICKERS``
          with the raw signal ``signal_jp``
        * ``"factor_scores"`` — ``np.ndarray`` of shape ``(K,)``
          containing ``f_t``

    Raises
    ------
    ValueError
        If ``target_date`` is not on the common calendar, the window
        runs off the start of the calendar, or any price in the
        window / on ``t`` is NaN.
    """
    cfg = config if config is not None else SignalConfig()

    # ---- input validation: shape & calendar alignment ----
    if list(open_df.columns) != ALL_TICKERS or list(close_df.columns) != ALL_TICKERS:
        # Re-order rather than fail; production callers may pass a wider frame
        if not set(ALL_TICKERS).issubset(set(close_df.columns)) or \
                not set(ALL_TICKERS).issubset(set(open_df.columns)):
            raise ValueError(
                "open_df / close_df must contain all 26 ALL_TICKERS columns"
            )
        open_df = open_df[ALL_TICKERS]
        close_df = close_df[ALL_TICKERS]
    if not open_df.index.equals(close_df.index):
        raise ValueError("open_df and close_df must share the same index")

    target_ts = pd.Timestamp(target_date)
    if target_ts not in close_df.index:
        raise ValueError(
            f"target_date {target_ts.date()} is not on the common business-day calendar"
        )
    t = close_df.index.get_loc(target_ts)
    if isinstance(t, slice) or isinstance(t, np.ndarray):
        raise ValueError(f"target_date {target_ts.date()} is not unique in the index")

    L = cfg.window_length
    if t < L:
        raise ValueError(
            f"target_date {target_ts.date()} is at index {t}; need at least "
            f"{L} prior business days for the window"
        )

    # ---- CC returns and window ----
    cc_returns = compute_cc_returns(close_df)
    cc_np = cc_returns.to_numpy()  # (N_BIZ, 26); row 0 is NaN

    W = cc_np[t - L : t]
    if W.shape != (L, N_TOTAL):
        raise ValueError(
            f"Window shape {W.shape} != expected ({L}, {N_TOTAL})"
        )
    if np.isnan(W).any():
        raise ValueError(
            f"Estimation window for {target_ts.date()} contains NaN; "
            "the window must lie entirely past the first calendar row"
        )

    # ---- window statistics (ddof=1, identical to SECTION 2C) ----
    mu_w = W.mean(axis=0)
    sigma_w = W.std(axis=0, ddof=1)
    if (sigma_w == 0).any():
        raise ValueError(
            f"Zero-variance ticker in window ending at {target_ts.date()}"
        )
    Z_w = (W - mu_w) / sigma_w                  # (L, 26)
    C_t = (Z_w.T @ Z_w) / (L - 1)               # (26, 26) correlation by construction

    # ---- regularisation + eigendecomposition ----
    C_reg = compute_regularized_correlation(C_t, C0, lam=cfg.lambda_reg)
    V_U, V_J = extract_top_eigenvectors(C_reg, cfg.n_components, N_US)

    # ---- today's standardised US returns (window statistics, not t-inclusive) ----
    cc_t = cc_np[t]
    if np.isnan(cc_t).any():
        raise ValueError(f"CC return on {target_ts.date()} contains NaN")
    z_t = (cc_t - mu_w) / sigma_w
    z_us_t = z_t[:N_US]

    # ---- factor scores + JP signal ----
    f_t = V_U.T @ z_us_t                        # (K,)
    signal_jp = V_J @ f_t                       # (N_JP,)

    # ---- ranking (descending; identical to SECTION 2C) ----
    rank_desc = np.argsort(-signal_jp)
    Q = cfg.basket_size(N_JP)
    long_idx = rank_desc[:Q]
    short_idx = rank_desc[-Q:]

    long_basket = [JP_TICKERS[i] for i in long_idx]
    short_basket = [JP_TICKERS[i] for i in short_idx]

    all_scores = pd.Series(signal_jp, index=JP_TICKERS, name="signal")

    return {
        "date": target_ts,
        "long_basket": long_basket,
        "short_basket": short_basket,
        "all_scores": all_scores,
        "factor_scores": f_t,
    }
