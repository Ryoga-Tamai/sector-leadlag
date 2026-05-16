"""
SECTION 7: Daily orchestrator for the US-Japan sector lead-lag strategy (v3).

This module is the single entry point that GitHub Actions invokes every
weekday after the US close.  It wires together the SECTION 3–6 modules
without re-implementing any business logic:

* :func:`src.data_loader.fetch_prices`
* :func:`src.signal_generator.load_prior_correlation` /
  :func:`src.pca_engine.build_prior_subspace` /
  :func:`src.pca_engine.build_target_correlation` /
  :func:`src.signal_generator.generate_signal`
* :func:`src.lot_calculator.fetch_latest_prices` /
  :func:`src.lot_calculator.calculate_lots`
* :func:`src.line_notifier.format_signal_message` /
  :func:`src.line_notifier.send_line_message` /
  :func:`src.line_notifier.send_error_notification`

Pipeline outputs
----------------
1. ``data/signals/{YYYY-MM-DD}.csv`` — one row per JP ticker
   (``date, ticker, score, rank, position, suggested_lots``).
2. ``docs/data.json`` — current signal plus the most recent
   :data:`HISTORY_LIMIT` historical baskets for the GitHub Pages
   dashboard.

Failure mode
------------
Any unhandled exception inside :func:`run_pipeline` is forwarded to
:func:`src.line_notifier.send_error_notification` (when LINE
credentials are available) and then re-raised so that the GitHub
Actions job is marked as failed.

Idempotency
-----------
Re-running on the same business day overwrites the per-day CSV and the
dashboard JSON.  No state is kept outside the file system.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src.data_loader import fetch_prices
from src.line_notifier import (
    format_signal_message,
    send_error_notification,
    send_line_message,
)
from src.lot_calculator import calculate_lots, fetch_latest_prices
from src.pca_engine import build_prior_subspace, build_target_correlation
from src.signal_generator import (
    SignalConfig,
    generate_signal,
    load_prior_correlation,
)
from src.universe import (
    ALL_TICKERS,
    JP_TICKERS,
    N_JP,
    N_US,
    get_universe_masks,
)

__all__ = [
    "DEFAULT_CAPITAL_JPY",
    "DEFAULT_LOOKBACK_DAYS",
    "HISTORY_LIMIT",
    "main",
    "run_pipeline",
]

# ---------------------------------------------------------------------------
# Defaults (overridable via env / kwargs)
# ---------------------------------------------------------------------------

DEFAULT_LOOKBACK_DAYS: int = 180  # L=60 + buffer for common-business-day intersection
DEFAULT_CAPITAL_JPY: int = 5_000_000
HISTORY_LIMIT: int = 100  # docs/data.json keeps the last N business-day baskets

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = REPO_ROOT / "data"
CACHE_PATH: Path = DATA_DIR / "cache_prices.csv"
PRIOR_PATH: Path = DATA_DIR / "prior" / "C_full.npy"
SIGNALS_DIR: Path = DATA_DIR / "signals"
DOCS_DIR: Path = REPO_ROOT / "docs"
DOCS_DATA_PATH: Path = DOCS_DIR / "data.json"

_JST = ZoneInfo("Asia/Tokyo")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(step: str, message: str = "") -> None:
    """Emit a single structured stdout line.

    Format: ``[YYYY-MM-DDTHH:MM:SS+0900] [STEP] message``.  Goes to
    stdout (not the ``logging`` module) so it lands in GitHub Actions
    job logs without configuration.
    """
    ts = datetime.now(_JST).strftime("%Y-%m-%dT%H:%M:%S%z")
    suffix = f" {message}" if message else ""
    print(f"[{ts}] [{step}]{suffix}", flush=True)


# ---------------------------------------------------------------------------
# Env parsing
# ---------------------------------------------------------------------------

def _resolve_capital(env_val: Optional[str]) -> float:
    """Parse the ``CAPITAL_JPY`` env var, falling back to the default."""
    if env_val is None or env_val == "":
        return float(DEFAULT_CAPITAL_JPY)
    try:
        capital = float(env_val)
    except ValueError as exc:
        raise ValueError(
            f"CAPITAL_JPY must be numeric, got {env_val!r}"
        ) from exc
    if capital <= 0:
        raise ValueError(f"CAPITAL_JPY must be > 0, got {capital}")
    return capital


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_signal_csv(
    signal_result: dict,
    lot_result: dict,
    out_path: Path,
) -> None:
    """Persist a single business-day signal as a CSV (17 JP rows).

    Columns: ``date, ticker, score, rank, position, suggested_lots``.

    * ``rank`` is the 1-based rank by descending score (1 = strongest
      long signal).
    * ``position`` is one of ``"long"``, ``"short"``, ``"neutral"``.
    * ``suggested_lots`` is the lot count from ``calculate_lots`` when
      the ticker is in a basket, otherwise ``0``.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_scores: pd.Series = signal_result["all_scores"]
    rank_desc = all_scores.sort_values(ascending=False)
    rank_map = {ticker: idx + 1 for idx, ticker in enumerate(rank_desc.index)}

    long_set = set(signal_result["long_basket"])
    short_set = set(signal_result["short_basket"])
    lots_long = {row["ticker"]: int(row["lots"]) for row in lot_result["long"]}
    lots_short = {row["ticker"]: int(row["lots"]) for row in lot_result["short"]}

    date_obj = signal_result["date"]
    date_str = (
        date_obj.strftime("%Y-%m-%d")
        if hasattr(date_obj, "strftime")
        else str(date_obj)
    )

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["date", "ticker", "score", "rank", "position", "suggested_lots"]
        )
        for ticker in JP_TICKERS:
            score = float(all_scores[ticker])
            rank = rank_map[ticker]
            if ticker in long_set:
                position = "long"
                lots = lots_long.get(ticker, 0)
            elif ticker in short_set:
                position = "short"
                lots = lots_short.get(ticker, 0)
            else:
                position = "neutral"
                lots = 0
            writer.writerow(
                [date_str, ticker, f"{score:.10g}", rank, position, lots]
            )


def _build_history(signals_dir: Path, limit: int) -> list[dict]:
    """Aggregate the most recent ``limit`` per-day CSVs into a list.

    Each list element is ``{"date", "long", "short"}``.  Files that
    fail to parse are skipped silently so a single corrupt CSV cannot
    poison the dashboard.  Filenames sort chronologically because they
    are ``YYYY-MM-DD.csv``.
    """
    if not signals_dir.exists():
        return []
    csv_files = sorted(signals_dir.glob("*.csv"))
    history: list[dict] = []
    for path in csv_files[-limit:]:
        try:
            df = pd.read_csv(path)
        except Exception:  # noqa: BLE001 — never crash on a single bad CSV
            continue
        if df.empty or "position" not in df.columns or "date" not in df.columns:
            continue
        date_str = str(df.iloc[0]["date"])
        longs = df.loc[df["position"] == "long", "ticker"].tolist()
        shorts = df.loc[df["position"] == "short", "ticker"].tolist()
        history.append({"date": date_str, "long": longs, "short": shorts})
    return history


def _write_docs_data_json(
    signal_result: dict,
    signals_dir: Path,
    out_path: Path,
) -> None:
    """Persist the GitHub Pages payload (current signal + history)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    date_obj = signal_result["date"]
    date_str = (
        date_obj.strftime("%Y-%m-%d")
        if hasattr(date_obj, "strftime")
        else str(date_obj)
    )

    factor_scores = np.asarray(signal_result["factor_scores"]).ravel().tolist()
    all_scores_series: pd.Series = signal_result["all_scores"]

    payload = {
        "last_updated": datetime.now(_JST).isoformat(),
        "current_signal": {
            "date": date_str,
            "long_basket": list(signal_result["long_basket"]),
            "short_basket": list(signal_result["short_basket"]),
            "factor_scores": [float(x) for x in factor_scores],
            "all_scores": {
                tk: float(all_scores_series[tk]) for tk in JP_TICKERS
            },
        },
        "history": _build_history(signals_dir, HISTORY_LIMIT),
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    capital_jpy: float,
    line_token: str,
    line_user_id: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    cache_path: Path = CACHE_PATH,
    prior_path: Path = PRIOR_PATH,
    signals_dir: Path = SIGNALS_DIR,
    docs_data_path: Path = DOCS_DATA_PATH,
) -> dict:
    """Run the end-to-end daily pipeline.

    Returns a small summary dict for tests / dashboards.  On failure,
    sends a LINE error notification (best effort) and re-raises the
    original exception so that the GitHub Actions job fails visibly.

    Parameters
    ----------
    capital_jpy
        Capital budget passed to :func:`calculate_lots`.
    line_token, line_user_id
        LINE Messaging API credentials.  An empty string disables the
        push (used for local dry-runs and CI without secrets).
    lookback_days
        Business-day lookback for ``fetch_prices``; converted to a
        calendar-day window via a ~1.6x safety multiplier.
    cache_path, prior_path, signals_dir, docs_data_path
        File-system locations.  Defaults point at the repository
        layout; tests override these with ``tmp_path``.
    """
    summary: dict = {"steps": [], "line_pushed": False}

    try:
        # --- 1. Fetch prices --------------------------------------------
        _log("DATA", f"fetching last {lookback_days} business days")
        today = pd.Timestamp.today().normalize()
        # ~1.6 calendar days per business day, plus 14 days slack for
        # JP/US holiday clusters.  fetch_prices clips end_date to today.
        start = today - pd.Timedelta(days=int(lookback_days * 1.6) + 14)
        open_df, close_df = fetch_prices(
            start_date=start,
            end_date=today,
            tickers=ALL_TICKERS,
            cache_path=str(cache_path),
        )
        _log(
            "DATA",
            f"rows={len(close_df)} "
            f"({close_df.index.min().date()} … {close_df.index.max().date()})",
        )
        summary["steps"].append("data")

        # --- 2. Prior correlation & target ------------------------------
        _log("PRIOR", f"loading {prior_path}")
        C_full = load_prior_correlation(str(prior_path))
        masks = get_universe_masks()
        V0 = build_prior_subspace(
            n_us=N_US,
            n_jp=N_JP,
            us_cyclical_mask=masks["us_cyclical"],
            us_defensive_mask=masks["us_defensive"],
            jp_cyclical_mask=masks["jp_cyclical"],
            jp_defensive_mask=masks["jp_defensive"],
        )
        C0 = build_target_correlation(V0, C_full)
        summary["steps"].append("prior")

        # --- 3. Generate signal -----------------------------------------
        target_date = close_df.index[-1]
        _log("SIGNAL", f"target_date={target_date.date()}")
        signal_result = generate_signal(
            open_df=open_df,
            close_df=close_df,
            target_date=target_date,
            C0=C0,
            config=SignalConfig(),
        )
        _log(
            "SIGNAL",
            f"long={signal_result['long_basket']} "
            f"short={signal_result['short_basket']}",
        )
        summary["steps"].append("signal")

        # --- 4. Lot calculation -----------------------------------------
        basket = list(signal_result["long_basket"]) + list(
            signal_result["short_basket"]
        )
        _log("LOTS", f"fetching latest prices for {len(basket)} tickers")
        prices = fetch_latest_prices(basket)
        lot_result = calculate_lots(
            capital_jpy=capital_jpy,
            long_tickers=signal_result["long_basket"],
            short_tickers=signal_result["short_basket"],
            prices_dict=prices,
            unit_size=10,
        )
        _log(
            "LOTS",
            f"gross={lot_result['total_gross_exposure']:,.0f} "
            f"cash={lot_result['cash_remaining']:,.0f}",
        )
        summary["steps"].append("lots")

        # --- 5. LINE notification ---------------------------------------
        _log("LINE", "pushing signal message")
        message = format_signal_message(signal_result, lot_result, capital_jpy)
        if line_token and line_user_id:
            pushed = send_line_message(message, line_token, line_user_id)
            if not pushed:
                # Don't abort — the CSV/JSON outputs are still useful.
                _log("LINE", "WARN: send_line_message returned False")
            summary["line_pushed"] = bool(pushed)
        else:
            _log("LINE", "WARN: LINE creds not set; skipping push")
            summary["line_pushed"] = False
        summary["steps"].append("line")

        # --- 6. Persist outputs -----------------------------------------
        date_str = target_date.strftime("%Y-%m-%d")
        signal_csv_path = signals_dir / f"{date_str}.csv"
        _log("SAVE", f"writing {signal_csv_path}")
        _write_signal_csv(signal_result, lot_result, signal_csv_path)

        _log("SAVE", f"writing {docs_data_path}")
        _write_docs_data_json(signal_result, signals_dir, docs_data_path)
        summary["steps"].append("save")
        summary["signal_csv"] = str(signal_csv_path)
        summary["docs_data"] = str(docs_data_path)
        summary["target_date"] = date_str

        _log("DONE", "pipeline finished successfully")
        return summary

    except Exception as exc:
        tb = traceback.format_exc()
        _log("ERROR", repr(exc))
        # Best-effort error notification; never let it mask the original.
        if line_token and line_user_id:
            try:
                send_error_notification(tb, line_token, line_user_id)
            except Exception as notify_exc:  # noqa: BLE001
                _log(
                    "ERROR",
                    f"error notification itself failed: {notify_exc!r}",
                )
        raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI entry point invoked by ``python -m src.main``."""
    load_dotenv()
    line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    line_user_id = os.environ.get("LINE_USER_ID", "")
    capital = _resolve_capital(os.environ.get("CAPITAL_JPY"))

    if not line_token or not line_user_id:
        _log("ENV", "WARN: LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID not set")

    run_pipeline(
        capital_jpy=capital,
        line_token=line_token,
        line_user_id=line_user_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
