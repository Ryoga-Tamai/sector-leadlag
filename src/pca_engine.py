"""
PCA engine implementing the subspace-regularized lead-lag strategy.

Corresponds to sections 3.1–3.3 of:
"部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略"
"""

import numpy as np


def _gram_schmidt_step(v: np.ndarray, basis: list[np.ndarray]) -> np.ndarray:
    """Project out all components in `basis` from `v`, then normalise."""
    for b in basis:
        v = v - np.dot(v, b) * b
    norm = np.linalg.norm(v)
    if norm < 1e-12:
        raise ValueError("Vector is linearly dependent on the existing basis.")
    return v / norm


def build_prior_subspace(
    n_us: int,
    n_jp: int,
    us_cyclical_mask: np.ndarray,
    us_defensive_mask: np.ndarray,
    jp_cyclical_mask: np.ndarray,
    jp_defensive_mask: np.ndarray,
) -> np.ndarray:
    """Construct the K0=3 prior eigenvector matrix V0 (section 3.1).

    Args:
        n_us: Number of US sectors (paper: 11).
        n_jp: Number of JP sectors (paper: 17).
        us_cyclical_mask: Boolean mask for US cyclical sectors, shape (n_us,).
        us_defensive_mask: Boolean mask for US defensive sectors, shape (n_us,).
        jp_cyclical_mask: Boolean mask for JP cyclical sectors, shape (n_jp,).
        jp_defensive_mask: Boolean mask for JP defensive sectors, shape (n_jp,).

    Returns:
        V0: Column-orthonormal prior eigenvectors, shape (n_us+n_jp, 3).
    """
    N = n_us + n_jp

    # v1: global factor — equal weight across all assets
    v1_raw = np.ones(N)
    v1 = v1_raw / np.linalg.norm(v1_raw)

    # v2: country spread — US=+1, JP=−1; orthogonalised against v1
    v2_raw = np.empty(N)
    v2_raw[:n_us] = 1.0
    v2_raw[n_us:] = -1.0
    v2 = _gram_schmidt_step(v2_raw, [v1])

    # v3: cyclical/defensive sign — cyc=+1, def=−1, neutral=0;
    #     orthogonalised against v1 and v2
    v3_raw = np.zeros(N)
    v3_raw[:n_us][us_cyclical_mask] = 1.0
    v3_raw[:n_us][us_defensive_mask] = -1.0
    v3_raw[n_us:][jp_cyclical_mask] = 1.0
    v3_raw[n_us:][jp_defensive_mask] = -1.0
    v3 = _gram_schmidt_step(v3_raw, [v1, v2])

    return np.column_stack([v1, v2, v3])


def build_target_correlation(
    V0: np.ndarray,
    C_full: np.ndarray,
) -> np.ndarray:
    """Build the prior correlation matrix C0 from V0 and a long-run correlation (eqs. 10–12).

    Args:
        V0: Prior eigenvectors, shape (N, K0).
        C_full: Long-run (or identity) correlation matrix, shape (N, N).

    Returns:
        C0: Prior correlation matrix with unit diagonal, shape (N, N).
    """
    # Eq. (10): project C_full onto the prior subspace
    D0 = np.diag(np.diag(V0.T @ C_full @ V0))

    # Eq. (11): reconstruct in original space
    C_raw = V0 @ D0 @ V0.T

    # Eq. (12): normalise so diagonal equals 1
    d = np.sqrt(np.diag(C_raw))
    C0 = C_raw / np.outer(d, d)

    # Guard against floating-point drift
    np.fill_diagonal(C0, 1.0)
    return C0


def compute_regularized_correlation(
    C_t: np.ndarray,
    C_0: np.ndarray,
    lam: float = 0.9,
) -> np.ndarray:
    """Blend the window correlation with the prior (eq. 13).

    Args:
        C_t: In-sample (rolling-window) correlation matrix, shape (N, N).
        C_0: Prior correlation matrix, shape (N, N).
        lam: Regularisation weight λ ∈ [0, 1] (paper default: 0.9).

    Returns:
        C_reg: Regularised correlation matrix, shape (N, N).
    """
    return (1.0 - lam) * C_t + lam * C_0


def extract_top_eigenvectors(
    C_reg: np.ndarray,
    K: int,
    n_us: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Decompose C_reg and return the top-K eigenvectors split by country (eqs. 14–16).

    Args:
        C_reg: Regularised correlation matrix, shape (N, N).
        K: Number of factors to retain (paper: 3).
        n_us: Number of US sectors; JP count is inferred as N − n_us.

    Returns:
        V_U: US-block of eigenvectors, shape (n_us, K).
        V_J: JP-block of eigenvectors, shape (n_jp, K).
    """
    # eigh is numerically stable for real symmetric matrices
    eigenvalues, eigenvectors = np.linalg.eigh(C_reg)

    # eigh returns ascending order; reverse to descending
    idx = np.argsort(eigenvalues)[::-1]
    eigenvectors = eigenvectors[:, idx]

    V_top = eigenvectors[:, :K]
    V_U = V_top[:n_us, :]
    V_J = V_top[n_us:, :]
    return V_U, V_J


def compute_lead_lag_signal(
    z_us_t: np.ndarray,
    V_U: np.ndarray,
    V_J: np.ndarray,
) -> np.ndarray:
    """Project today's US returns through the factor model to predict JP returns (eqs. 18–20).

    Args:
        z_us_t: Standardised US sector returns for day t, shape (n_us,).
        V_U: US eigenvector block, shape (n_us, K).
        V_J: JP eigenvector block, shape (n_jp, K).

    Returns:
        z_jp_pred: Predicted standardised JP sector returns for day t+1, shape (n_jp,).
    """
    # Eq. (18)-(19): project US returns onto shared factors
    f_t = V_U.T @ z_us_t

    # Eq. (20): reconstruct JP signal
    return V_J @ f_t
