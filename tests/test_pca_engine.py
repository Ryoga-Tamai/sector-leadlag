"""Unit tests for src/pca_engine.py.

All tests use the paper's canonical dimensions: n_us=11, n_jp=17, K=3.
"""

import numpy as np
import pytest

from src.pca_engine import (
    build_prior_subspace,
    build_target_correlation,
    compute_lead_lag_signal,
    compute_regularized_correlation,
    extract_top_eigenvectors,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

N_US = 11
N_JP = 17
N = N_US + N_JP
K = 3


def _make_masks() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Stable sector classification masks matching US-11 / JP-17 paper layout."""
    us_cyc = np.array([True, True, True, True, False, False, False, False, False, False, False])
    us_def = np.array([False, False, False, False, True, True, True, False, False, False, False])
    jp_cyc = np.array([True, True, True, True, True, True, False, False, False,
                       False, False, False, False, False, False, False, False])
    jp_def = np.array([False, False, False, False, False, False, True, True, True,
                       True, False, False, False, False, False, False, False])
    return us_cyc, us_def, jp_cyc, jp_def


def _make_prior_subspace() -> np.ndarray:
    us_cyc, us_def, jp_cyc, jp_def = _make_masks()
    return build_prior_subspace(N_US, N_JP, us_cyc, us_def, jp_cyc, jp_def)


def _make_spd_matrix(size: int, rng: np.random.Generator) -> np.ndarray:
    """Random symmetric positive-definite matrix normalised to a correlation matrix."""
    A = rng.standard_normal((size, size))
    C = A @ A.T + np.eye(size) * size
    d = np.sqrt(np.diag(C))
    return C / np.outer(d, d)


# ---------------------------------------------------------------------------
# 1. Orthogonality of prior subspace
# ---------------------------------------------------------------------------


def test_prior_subspace_orthogonality():
    V0 = _make_prior_subspace()
    assert V0.shape == (N, 3)

    # Each column must be unit-norm
    for k in range(3):
        assert abs(np.linalg.norm(V0[:, k]) - 1.0) < 1e-10, f"Column {k} is not unit-norm"

    # Columns must be mutually orthogonal  →  V0.T @ V0 ≈ I
    assert np.allclose(V0.T @ V0, np.eye(3), atol=1e-10)


# ---------------------------------------------------------------------------
# 2. Global factor has equal elements
# ---------------------------------------------------------------------------


def test_prior_subspace_global_factor():
    V0 = _make_prior_subspace()
    v1 = V0[:, 0]
    # All elements equal up to sign (unit-normalised equal-weight vector)
    assert np.allclose(np.abs(v1), np.abs(v1[0]), atol=1e-10)


# ---------------------------------------------------------------------------
# 3. Target correlation has unit diagonal
# ---------------------------------------------------------------------------


def test_target_correlation_diagonal():
    V0 = _make_prior_subspace()
    rng = np.random.default_rng(42)
    C_full = _make_spd_matrix(N, rng)

    C0 = build_target_correlation(V0, C_full)

    assert C0.shape == (N, N)
    assert np.allclose(np.diag(C0), 1.0, atol=1e-10)


# ---------------------------------------------------------------------------
# 4. Extreme-lambda cases for regularised correlation
# ---------------------------------------------------------------------------


def test_regularized_correlation_extreme_cases():
    rng = np.random.default_rng(0)
    C_t = _make_spd_matrix(N, rng)
    C_0 = _make_spd_matrix(N, rng)

    assert np.allclose(compute_regularized_correlation(C_t, C_0, lam=0.0), C_t)
    assert np.allclose(compute_regularized_correlation(C_t, C_0, lam=1.0), C_0)


# ---------------------------------------------------------------------------
# 5. Eigenvector extraction shape
# ---------------------------------------------------------------------------


def test_extract_eigenvectors_shape():
    rng = np.random.default_rng(7)
    C_reg = _make_spd_matrix(N, rng)

    V_U, V_J = extract_top_eigenvectors(C_reg, K, N_US)

    assert V_U.shape == (N_US, K), f"V_U shape mismatch: {V_U.shape}"
    assert V_J.shape == (N_JP, K), f"V_J shape mismatch: {V_J.shape}"


# ---------------------------------------------------------------------------
# 6. Lead-lag signal shape
# ---------------------------------------------------------------------------


def test_lead_lag_signal_shape():
    rng = np.random.default_rng(99)
    C_reg = _make_spd_matrix(N, rng)
    V_U, V_J = extract_top_eigenvectors(C_reg, K, N_US)

    z_us_t = rng.standard_normal(N_US)
    z_jp_pred = compute_lead_lag_signal(z_us_t, V_U, V_J)

    assert z_jp_pred.shape == (N_JP,), f"Signal shape mismatch: {z_jp_pred.shape}"
