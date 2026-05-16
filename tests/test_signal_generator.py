"""Unit tests for :mod:`src.signal_generator` (SECTION 4).

The most important test, :func:`test_generate_signal_matches_backtest`,
re-implements the SECTION 2C backtest loop body inline and confirms
:func:`generate_signal` produces bit-identical output for the same
synthetic inputs.  This guards against silent logic drift between the
notebook (paper replication) and the production module (LINE / Pages
runtime).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.pca_engine import (
    build_prior_subspace,
    build_target_correlation,
    compute_regularized_correlation,
    extract_top_eigenvectors,
)
from src.signal_generator import (
    SignalConfig,
    generate_signal,
    load_prior_correlation,
)
from src.universe import (
    ALL_TICKERS,
    JP_TICKERS,
    N_JP,
    N_TOTAL,
    N_US,
    get_universe_masks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_prices(
    n_days: int,
    n_tickers: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return random-walk Open / Close frames on a business-day calendar.

    Close path is built from cumulative product of small returns so the
    column variance is non-zero (the SECTION 2C loop asserts non-zero
    sigma_w; we honour the same precondition).  Open is Close shifted
    by a small intraday move so OC returns are non-degenerate.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start="2020-01-02", periods=n_days)
    cc = rng.normal(loc=0.0, scale=0.012, size=(n_days, n_tickers))
    close = 100.0 * np.exp(np.cumsum(cc, axis=0))
    intraday = rng.normal(loc=0.0, scale=0.005, size=(n_days, n_tickers))
    open_ = close * np.exp(-intraday)
    cols = ALL_TICKERS if n_tickers == N_TOTAL else [f"T{i}" for i in range(n_tickers)]
    return (
        pd.DataFrame(open_, index=idx, columns=cols),
        pd.DataFrame(close, index=idx, columns=cols),
    )


def _build_C0_from_close(close_df: pd.DataFrame) -> np.ndarray:
    """Build C0 from a close frame the same way the notebook does."""
    masks = get_universe_masks()
    V0 = build_prior_subspace(
        N_US, N_JP,
        masks["us_cyclical"], masks["us_defensive"],
        masks["jp_cyclical"], masks["jp_defensive"],
    )
    cc = close_df.pct_change().dropna(how="any")
    mu = cc.mean()
    sigma = cc.std(ddof=1)
    Z = (cc - mu) / sigma
    C_full = Z.corr().to_numpy()
    return build_target_correlation(V0, C_full)


# ---------------------------------------------------------------------------
# SignalConfig defaults
# ---------------------------------------------------------------------------

def test_signal_config_defaults():
    """Defaults must match requirements_v3.md §2.2."""
    cfg = SignalConfig()
    assert cfg.window_length == 60
    assert cfg.n_components == 3
    assert cfg.lambda_reg == 0.9
    assert cfg.quantile == 0.3
    # 17 * 0.3 = 5.1 → floor = 5  (SECTION 2C: Q_LONG = Q_SHORT = 5)
    assert cfg.basket_size(N_JP) == 5


def test_signal_config_basket_size_uses_floor():
    cfg = SignalConfig(quantile=0.4)
    # 17 * 0.4 = 6.8 → floor = 6
    assert cfg.basket_size(N_JP) == 6


def test_signal_config_is_frozen():
    cfg = SignalConfig()
    with pytest.raises(Exception):
        cfg.window_length = 30  # type: ignore[misc]


# ---------------------------------------------------------------------------
# load_prior_correlation
# ---------------------------------------------------------------------------

def test_load_prior_correlation_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        load_prior_correlation(str(tmp_path / "does_not_exist.npy"))


def test_load_prior_correlation_wrong_shape_raises(tmp_path):
    path = tmp_path / "wrong.npy"
    np.save(path, np.zeros((10, 10)))
    with pytest.raises(ValueError, match="shape"):
        load_prior_correlation(str(path))


def test_load_prior_correlation_round_trip(tmp_path):
    expected = np.eye(N_TOTAL)
    path = tmp_path / "C_full.npy"
    np.save(path, expected)
    loaded = load_prior_correlation(str(path))
    np.testing.assert_array_equal(loaded, expected)


# ---------------------------------------------------------------------------
# generate_signal — output shape
# ---------------------------------------------------------------------------

def test_generate_signal_shape():
    """Output shapes / sizes follow the SECTION 4 spec for 26×100 input."""
    open_df, close_df = _synthetic_prices(n_days=100, n_tickers=N_TOTAL, seed=42)
    C0 = _build_C0_from_close(close_df)
    target = close_df.index[80]

    out = generate_signal(open_df, close_df, target, C0)

    assert out["date"] == pd.Timestamp(target)
    assert isinstance(out["long_basket"], list) and len(out["long_basket"]) == 5
    assert isinstance(out["short_basket"], list) and len(out["short_basket"]) == 5
    assert set(out["long_basket"]).isdisjoint(set(out["short_basket"]))
    assert isinstance(out["all_scores"], pd.Series)
    assert len(out["all_scores"]) == N_JP
    assert list(out["all_scores"].index) == JP_TICKERS
    assert isinstance(out["factor_scores"], np.ndarray)
    assert out["factor_scores"].shape == (3,)


def test_generate_signal_long_short_are_top_bottom_of_scores():
    open_df, close_df = _synthetic_prices(n_days=120, n_tickers=N_TOTAL, seed=7)
    C0 = _build_C0_from_close(close_df)
    target = close_df.index[100]

    out = generate_signal(open_df, close_df, target, C0)

    scores = out["all_scores"]
    sorted_desc = scores.sort_values(ascending=False)
    assert list(sorted_desc.index[:5]) == out["long_basket"]
    # Short basket = bottom-5; SECTION 2C uses rank_desc[-5:] which is
    # ascending-order from rank 12..16 (5th worst to worst).
    assert sorted(out["short_basket"]) == sorted(list(sorted_desc.index[-5:]))


# ---------------------------------------------------------------------------
# generate_signal — bit-identical to inline SECTION 2C loop
# ---------------------------------------------------------------------------

def test_generate_signal_matches_backtest():
    """Inline SECTION 2C loop body must agree with generate_signal.

    This is the core consistency contract: the production module and
    the notebook re-run on the same data must produce the same signal,
    long / short baskets, and factor scores — bit-identical.
    """
    open_df, close_df = _synthetic_prices(n_days=200, n_tickers=N_TOTAL, seed=20260516)
    C0 = _build_C0_from_close(close_df)
    cfg = SignalConfig()  # defaults: L=60, K=3, λ=0.9, q=0.3

    # cc_returns identical to notebook cell 6
    cc_np = close_df.pct_change().to_numpy()
    L = cfg.window_length
    K = cfg.n_components
    LAM = cfg.lambda_reg
    Q = cfg.basket_size(N_JP)

    # Sample several t-values (early, mid, late in the test calendar).
    # The minimum usable t is L+1 — at t=L the window cc[0:L] would
    # include row 0, which is NaN by construction (pct_change first row).
    for t in (L + 1, 90, 150, 199):
        target = close_df.index[t]

        # ---- inline SECTION 2C loop body ----
        W = cc_np[t - L : t]
        mu_w = W.mean(axis=0)
        sigma_w = W.std(axis=0, ddof=1)
        Z_w = (W - mu_w) / sigma_w
        C_t = (Z_w.T @ Z_w) / (L - 1)
        C_reg = compute_regularized_correlation(C_t, C0, lam=LAM)
        V_U, V_J = extract_top_eigenvectors(C_reg, K, N_US)
        cc_t = cc_np[t]
        z_t = (cc_t - mu_w) / sigma_w
        z_us_t = z_t[:N_US]
        f_t_ref = V_U.T @ z_us_t
        signal_jp_ref = V_J @ f_t_ref
        rank_desc = np.argsort(-signal_jp_ref)
        long_ref = [JP_TICKERS[i] for i in rank_desc[:Q]]
        short_ref = [JP_TICKERS[i] for i in rank_desc[-Q:]]

        # ---- generate_signal output ----
        out = generate_signal(open_df, close_df, target, C0, cfg)

        # ---- compare every field bit-identically ----
        np.testing.assert_array_equal(
            out["all_scores"].values, signal_jp_ref,
            err_msg=f"signal mismatch at t={t}",
        )
        np.testing.assert_array_equal(
            out["factor_scores"], f_t_ref,
            err_msg=f"factor_scores mismatch at t={t}",
        )
        assert out["long_basket"] == long_ref, (
            f"long_basket mismatch at t={t}: {out['long_basket']} vs {long_ref}"
        )
        assert out["short_basket"] == short_ref, (
            f"short_basket mismatch at t={t}: {out['short_basket']} vs {short_ref}"
        )


# ---------------------------------------------------------------------------
# generate_signal — edge cases (ValueError contract)
# ---------------------------------------------------------------------------

def test_generate_signal_raises_for_unknown_date():
    open_df, close_df = _synthetic_prices(n_days=80, n_tickers=N_TOTAL, seed=1)
    C0 = _build_C0_from_close(close_df)
    unknown = pd.Timestamp("1999-01-01")
    with pytest.raises(ValueError, match="calendar"):
        generate_signal(open_df, close_df, unknown, C0)


def test_generate_signal_raises_when_window_underfilled():
    """Requesting a signal before t=L should raise."""
    open_df, close_df = _synthetic_prices(n_days=80, n_tickers=N_TOTAL, seed=1)
    C0 = _build_C0_from_close(close_df)
    target = close_df.index[10]  # 10 < L=60
    with pytest.raises(ValueError, match="prior business days"):
        generate_signal(open_df, close_df, target, C0)


def test_generate_signal_raises_on_nan_in_window():
    open_df, close_df = _synthetic_prices(n_days=80, n_tickers=N_TOTAL, seed=1)
    C0 = _build_C0_from_close(close_df)
    target = close_df.index[70]
    # Inject NaN inside the window [10, 70)
    close_df.iloc[40, 5] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        generate_signal(open_df, close_df, target, C0)


def test_generate_signal_raises_when_columns_missing():
    open_df, close_df = _synthetic_prices(n_days=80, n_tickers=N_TOTAL, seed=1)
    C0 = _build_C0_from_close(close_df)
    target = close_df.index[70]
    truncated = close_df.drop(columns=["XLK"])
    with pytest.raises(ValueError, match="26"):
        generate_signal(open_df, truncated, target, C0)


def test_generate_signal_raises_on_index_mismatch():
    open_df, close_df = _synthetic_prices(n_days=80, n_tickers=N_TOTAL, seed=1)
    C0 = _build_C0_from_close(close_df)
    target = close_df.index[70]
    # Shift the open index by one business day
    open_shifted = open_df.copy()
    open_shifted.index = open_shifted.index + pd.tseries.offsets.BDay(1)
    with pytest.raises(ValueError, match="index"):
        generate_signal(open_shifted, close_df, target, C0)
