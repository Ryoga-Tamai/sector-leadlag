"""
26-ticker fixed universe for the US-Japan sector lead-lag strategy (v3).

Corresponds to §2.1 of requirements_v3.md.

US side: 9 Select Sector SPDR ETFs (XLC and XLRE excluded due to late listing).
JP side: 17 NEXT FUNDS TOPIX-17 sector ETFs (all listed before 2010).

The strategy uses these tickers in a fixed order: US_TICKERS first (n_us=9),
then JP_TICKERS (n_jp=17). The combined ALL_TICKERS list (length 26) defines
the column ordering for every price/return/correlation matrix downstream.
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Ticker universe (26 tickers, fixed order)
# ---------------------------------------------------------------------------

US_TICKERS: list[str] = [
    "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY",
]  # 9 tickers; XLC (2018-listed) and XLRE (2015-listed) are excluded

JP_TICKERS: list[str] = [
    "1617.T", "1618.T", "1619.T", "1620.T", "1621.T", "1622.T", "1623.T",
    "1624.T", "1625.T", "1626.T", "1627.T", "1628.T", "1629.T", "1630.T",
    "1631.T", "1632.T", "1633.T",
]  # 17 tickers

ALL_TICKERS: list[str] = US_TICKERS + JP_TICKERS  # 26 tickers

N_US: int = len(US_TICKERS)   # 9
N_JP: int = len(JP_TICKERS)   # 17
N_TOTAL: int = len(ALL_TICKERS)  # 26

# ---------------------------------------------------------------------------
# Cyclical / Defensive classification (§2.1 requirements_v3.md)
# ---------------------------------------------------------------------------

US_CYCLICAL: list[str] = ["XLB", "XLE", "XLF"]
US_DEFENSIVE: list[str] = ["XLK", "XLP", "XLU", "XLV"]
# US neutral: XLI, XLY

JP_CYCLICAL: list[str] = ["1618.T", "1625.T", "1629.T", "1631.T"]
JP_DEFENSIVE: list[str] = ["1617.T", "1621.T", "1627.T", "1630.T"]
# JP neutral: all others (1619, 1620, 1622, 1623, 1624, 1626, 1628, 1632, 1633)

# ---------------------------------------------------------------------------
# Human-readable sector names (for LINE notification / dashboard)
# ---------------------------------------------------------------------------

US_SECTOR_NAMES: dict[str, str] = {
    "XLB": "Materials",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLK": "Information Technology",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
}

JP_SECTOR_NAMES: dict[str, str] = {
    "1617.T": "食品",
    "1618.T": "エネルギー資源",
    "1619.T": "建設・資材",
    "1620.T": "素材・化学",
    "1621.T": "医薬品",
    "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄",
    "1624.T": "機械",
    "1625.T": "電機・精密",
    "1626.T": "情報通信・サービスその他",
    "1627.T": "電力・ガス",
    "1628.T": "運輸・物流",
    "1629.T": "商社・卸売",
    "1630.T": "小売",
    "1631.T": "銀行",
    "1632.T": "金融（除く銀行）",
    "1633.T": "不動産",
}

# ---------------------------------------------------------------------------
# Mask builder
# ---------------------------------------------------------------------------


def get_universe_masks() -> dict[str, np.ndarray]:
    """Return boolean masks for sector classification in US_TICKERS / JP_TICKERS order.

    Returns
    -------
    dict with four keys:
        'us_cyclical':  np.ndarray(bool, shape=(N_US,))  — True where ticker in US_CYCLICAL
        'us_defensive': np.ndarray(bool, shape=(N_US,))  — True where ticker in US_DEFENSIVE
        'jp_cyclical':  np.ndarray(bool, shape=(N_JP,))  — True where ticker in JP_CYCLICAL
        'jp_defensive': np.ndarray(bool, shape=(N_JP,))  — True where ticker in JP_DEFENSIVE

    The mask order follows US_TICKERS / JP_TICKERS exactly, so it can be passed
    directly to src.pca_engine.build_prior_subspace().
    """
    us_cyc_set = set(US_CYCLICAL)
    us_def_set = set(US_DEFENSIVE)
    jp_cyc_set = set(JP_CYCLICAL)
    jp_def_set = set(JP_DEFENSIVE)

    return {
        "us_cyclical":  np.array([t in us_cyc_set for t in US_TICKERS], dtype=bool),
        "us_defensive": np.array([t in us_def_set for t in US_TICKERS], dtype=bool),
        "jp_cyclical":  np.array([t in jp_cyc_set for t in JP_TICKERS], dtype=bool),
        "jp_defensive": np.array([t in jp_def_set for t in JP_TICKERS], dtype=bool),
    }


# ---------------------------------------------------------------------------
# Self-check (executed once at import time to catch typos)
# ---------------------------------------------------------------------------

assert N_US == 9, f"Expected 9 US tickers, got {N_US}"
assert N_JP == 17, f"Expected 17 JP tickers, got {N_JP}"
assert N_TOTAL == 26, f"Expected 26 total tickers, got {N_TOTAL}"
assert len(set(ALL_TICKERS)) == 26, "Duplicate tickers detected in ALL_TICKERS"
assert set(US_CYCLICAL).issubset(US_TICKERS), "US_CYCLICAL contains unknown ticker"
assert set(US_DEFENSIVE).issubset(US_TICKERS), "US_DEFENSIVE contains unknown ticker"
assert set(JP_CYCLICAL).issubset(JP_TICKERS), "JP_CYCLICAL contains unknown ticker"
assert set(JP_DEFENSIVE).issubset(JP_TICKERS), "JP_DEFENSIVE contains unknown ticker"
assert set(US_CYCLICAL).isdisjoint(US_DEFENSIVE), "US ticker in both cyc/def"
assert set(JP_CYCLICAL).isdisjoint(JP_DEFENSIVE), "JP ticker in both cyc/def"
assert set(US_SECTOR_NAMES.keys()) == set(US_TICKERS), "US_SECTOR_NAMES key mismatch"
assert set(JP_SECTOR_NAMES.keys()) == set(JP_TICKERS), "JP_SECTOR_NAMES key mismatch"
