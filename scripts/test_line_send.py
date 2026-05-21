#!/usr/bin/env python3
"""Manual smoke test for :mod:`src.line_notifier`.

Reads ``LINE_CHANNEL_ACCESS_TOKEN`` and ``LINE_USER_ID`` from ``.env``
(via ``python-dotenv``), then sends a short text message to the
configured LINE user and prints the result.

Run from the repository root::

    python scripts/test_line_send.py

Use ``--with-signal`` to skip the canned message and instead push a
realistic signal (computed on the most recent common business day)
through :func:`format_signal_message`.  This validates the full
pipeline ``fetch_prices → generate_signal → fetch_latest_prices →
calculate_lots → format_signal_message → send_line_message``.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Repo root on sys.path so ``python scripts/test_line_send.py`` works.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402

from src.line_notifier import format_signal_message, send_line_message  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LINE notifier smoke test.")
    p.add_argument(
        "--with-signal",
        action="store_true",
        help="Compute today's signal + lots and push that instead of a canned ping.",
    )
    p.add_argument(
        "--capital",
        type=int,
        default=5_000_000,
        help="Capital (JPY) for the lot calculation when --with-signal is set.",
    )
    return p.parse_args()


def _build_signal_message(capital_jpy: int) -> str:
    """Run the full pipeline and return a LINE-ready message body."""
    # Local imports — they trigger yfinance / numpy, so keep them inside the
    # branch that actually needs them.
    from src.data_loader import fetch_prices
    from src.lot_calculator import calculate_lots, fetch_latest_prices
    from src.pca_engine import build_prior_subspace, build_target_correlation
    from src.signal_generator import (
        SignalConfig, generate_signal, load_prior_correlation,
    )
    from src.universe import (
        ALL_TICKERS, N_JP, N_US, get_universe_masks,
    )

    print("[pipeline] fetching prices...")
    open_df, close_df = fetch_prices(
        start_date="2025-11-01",
        end_date=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat(),
        tickers=ALL_TICKERS,
        cache_path=os.path.join(REPO_ROOT, "data", "cache_prices.csv"),
    )
    print(f"[pipeline] common business days: {len(close_df)}")

    masks = get_universe_masks()
    V0 = build_prior_subspace(
        N_US, N_JP,
        masks["us_cyclical"], masks["us_defensive"],
        masks["jp_cyclical"], masks["jp_defensive"],
    )
    C0 = build_target_correlation(
        V0,
        load_prior_correlation(os.path.join(REPO_ROOT, "data", "prior", "C_full.npy")),
    )

    target = close_df.index[-1]
    print(f"[pipeline] generating signal for {target.date()}")
    sig = generate_signal(open_df, close_df, target, C0, SignalConfig())

    print(f"[pipeline] fetching latest prices for {len(sig['long_basket']) + len(sig['short_basket'])} tickers")
    prices = fetch_latest_prices(sig["long_basket"] + sig["short_basket"])
    lots = calculate_lots(capital_jpy, sig["long_basket"], sig["short_basket"], prices, unit_size=10)

    return format_signal_message(sig, lots, capital_jpy)


def main() -> int:
    args = _parse_args()

    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")

    if not token or not user_id:
        print(
            "ERROR: LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID must be set in .env",
            file=sys.stderr,
        )
        print(
            f"  LINE_CHANNEL_ACCESS_TOKEN set : {bool(token)}",
            file=sys.stderr,
        )
        print(
            f"  LINE_USER_ID              set : {bool(user_id)}",
            file=sys.stderr,
        )
        return 2

    # Mask both values so screenshots / shared logs don't leak secrets.
    tok_preview = token[:6] + "..." + token[-4:] if len(token) > 12 else "***"
    uid_preview = user_id[:6] + "..." if len(user_id) > 8 else "***"
    print(f"[env] LINE_CHANNEL_ACCESS_TOKEN: {tok_preview}")
    print(f"[env] LINE_USER_ID            : {uid_preview}")

    if args.with_signal:
        message = _build_signal_message(args.capital)
        print("[message] full pipeline result (first 200 chars):")
        print(message[:200])
    else:
        jst_now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S %Z")
        message = (
            "[動作確認] 日米業種リードラグ LINE通知\n"
            f"時刻: {jst_now}\n"
            "これは scripts/test_line_send.py から送信した動作確認メッセージです。\n"
            "この通知がスマホに届けば send_line_message が正常に動作しています。"
        )

    print("[send] pushing to LINE...")
    ok = send_line_message(message, token, user_id)
    if ok:
        print("[send] OK  -- LINE Push API returned 200")
        return 0
    print("[send] FAIL -- see error log above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
