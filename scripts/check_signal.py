#!/usr/bin/env python3
"""Smoke-test :func:`src.signal_generator.generate_signal` on recent data.

Fetches the most recent ~120 business days for the 26-ticker universe
(via yfinance + cache), loads the long-run correlation
``data/prior/C_full.npy``, builds ``C0`` against the current
universe, and prints the signal for the latest common business day.

Run from the repository root::

    python scripts/check_signal.py

Use ``--target-date YYYY-MM-DD`` to inspect a historical day instead
of the latest available one.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

# Make the project root importable when run as ``python scripts/check_signal.py``.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.data_loader import fetch_prices  # noqa: E402
from src.pca_engine import (                # noqa: E402
    build_prior_subspace,
    build_target_correlation,
)
from src.signal_generator import (           # noqa: E402
    SignalConfig,
    generate_signal,
    load_prior_correlation,
)
from src.universe import (                   # noqa: E402
    ALL_TICKERS,
    JP_SECTOR_NAMES,
    N_JP,
    N_US,
    get_universe_masks,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run a one-day signal smoke check.")
    p.add_argument(
        "--target-date",
        type=str,
        default=None,
        help="Signal date (YYYY-MM-DD). Defaults to the latest common business day.",
    )
    p.add_argument(
        "--lookback-days",
        type=int,
        default=180,
        help="Calendar-day lookback for the price fetch (default: 180, ~120 bdays).",
    )
    p.add_argument(
        "--cache-path",
        type=str,
        default=os.path.join("data", "cache_prices.csv"),
        help="Price cache CSV. Pass an empty string to disable caching.",
    )
    p.add_argument(
        "--prior-path",
        type=str,
        default=os.path.join("data", "prior", "C_full.npy"),
        help="Path to the pre-computed long-run correlation matrix.",
    )
    return p.parse_args()


def _build_C0() -> np.ndarray:
    """Load ``C_full`` and project it onto the K0=3 prior subspace."""
    masks = get_universe_masks()
    V0 = build_prior_subspace(
        N_US, N_JP,
        masks["us_cyclical"], masks["us_defensive"],
        masks["jp_cyclical"], masks["jp_defensive"],
    )
    args = _parse_args()
    C_full = load_prior_correlation(args.prior_path)
    return build_target_correlation(V0, C_full)


def main() -> int:
    args = _parse_args()
    cache_path = args.cache_path if args.cache_path else None

    # ---- 1. price fetch ----
    end = date.today()
    start = end - timedelta(days=args.lookback_days)
    print(f"[1/3] fetching {len(ALL_TICKERS)} tickers, "
          f"{start.isoformat()} … {end.isoformat()}")
    open_df, close_df = fetch_prices(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        tickers=ALL_TICKERS,
        cache_path=cache_path,
    )
    print(f"      common business days: {len(close_df)} "
          f"({close_df.index.min().date()} → {close_df.index.max().date()})")

    # ---- 2. prior C0 ----
    print(f"[2/3] loading prior correlation: {args.prior_path}")
    masks = get_universe_masks()
    V0 = build_prior_subspace(
        N_US, N_JP,
        masks["us_cyclical"], masks["us_defensive"],
        masks["jp_cyclical"], masks["jp_defensive"],
    )
    C_full = load_prior_correlation(args.prior_path)
    C0 = build_target_correlation(V0, C_full)
    print(f"      C0 shape: {C0.shape}")

    # ---- 3. signal ----
    if args.target_date is not None:
        target = pd.Timestamp(args.target_date)
        if target not in close_df.index:
            print(f"ERROR: {target.date()} is not on the common business-day calendar")
            return 1
    else:
        target = close_df.index[-1]
    print(f"[3/3] generating signal for {target.date()}")

    cfg = SignalConfig()
    out = generate_signal(open_df, close_df, target, C0, cfg)

    print()
    print("=" * 60)
    print(f"Signal date         : {out['date'].date()}")
    print(f"Window length L     : {cfg.window_length}")
    print(f"Factor scores f_t   : {np.round(out['factor_scores'], 4).tolist()}")
    print()
    print("Long  (top 5):")
    for tk in out["long_basket"]:
        score = out["all_scores"][tk]
        print(f"  {tk:8s}  {JP_SECTOR_NAMES.get(tk, ''):<14s}  score={score:+.4f}")
    print()
    print("Short (bottom 5):")
    for tk in out["short_basket"]:
        score = out["all_scores"][tk]
        print(f"  {tk:8s}  {JP_SECTOR_NAMES.get(tk, ''):<14s}  score={score:+.4f}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
