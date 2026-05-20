"""Unit tests for :mod:`src.main` (SECTION 7)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import src.main as main_module
from src.main import (
    DEFAULT_CAPITAL_JPY,
    HISTORY_LIMIT,
    _build_history,
    _resolve_capital,
    _write_docs_data_json,
    _write_signal_csv,
    run_pipeline,
)
from src.universe import ALL_TICKERS, JP_TICKERS, N_JP


# ---------------------------------------------------------------------------
# Test fixtures — deterministic OHLC + signal/lot results
# ---------------------------------------------------------------------------

def _dummy_ohlc(n_rows: int = 70) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build deterministic Open / Close frames on a synthetic calendar."""
    rng = np.random.default_rng(seed=42)
    dates = pd.bdate_range(end=pd.Timestamp("2026-05-15"), periods=n_rows)
    close = pd.DataFrame(
        100.0 + rng.standard_normal((n_rows, len(ALL_TICKERS))).cumsum(axis=0),
        index=dates,
        columns=ALL_TICKERS,
    )
    open_ = close * (1.0 + rng.standard_normal(close.shape) * 0.001)
    return open_, close


def _dummy_signal_result(date: pd.Timestamp | None = None) -> dict:
    """Reasonable signal payload with all 17 scores and 5/5 baskets."""
    if date is None:
        date = pd.Timestamp("2026-05-15")
    rng = np.random.default_rng(seed=7)
    scores = pd.Series(
        rng.standard_normal(N_JP), index=JP_TICKERS, name="signal"
    )
    order = scores.sort_values(ascending=False).index.tolist()
    long_basket = order[:5]
    short_basket = order[-5:]
    return {
        "date": date,
        "long_basket": long_basket,
        "short_basket": short_basket,
        "all_scores": scores,
        "factor_scores": np.array([0.4521, -1.2034, 0.8812]),
    }


def _dummy_lot_result(signal_result: dict) -> dict:
    """A lot result that matches the basket structure of ``signal_result``."""
    long_rows = [
        {"ticker": tk, "lots": i + 1, "shares": (i + 1) * 10,
         "price": 1000.0 + i, "value": (i + 1) * 10 * (1000.0 + i)}
        for i, tk in enumerate(signal_result["long_basket"])
    ]
    short_rows = [
        {"ticker": tk, "lots": i + 1, "shares": (i + 1) * 10,
         "price": 2000.0 + i, "value": (i + 1) * 10 * (2000.0 + i)}
        for i, tk in enumerate(signal_result["short_basket"])
    ]
    total_long = sum(r["value"] for r in long_rows)
    total_short = sum(r["value"] for r in short_rows)
    return {
        "long": long_rows,
        "short": short_rows,
        "total_long_value": total_long,
        "total_short_value": total_short,
        "total_gross_exposure": total_long + total_short,
        "cash_remaining": 5_000_000 - (total_long + total_short),
    }


# ---------------------------------------------------------------------------
# _resolve_capital
# ---------------------------------------------------------------------------

class TestResolveCapital:
    """Behavioural tests for ``_resolve_capital`` env parsing."""

    def test_none_falls_back_to_default(self):
        assert _resolve_capital(None) == float(DEFAULT_CAPITAL_JPY)

    def test_empty_string_falls_back_to_default(self):
        assert _resolve_capital("") == float(DEFAULT_CAPITAL_JPY)

    def test_numeric_string_is_parsed(self):
        assert _resolve_capital("7500000") == 7_500_000.0

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="must be > 0"):
            _resolve_capital("-100")

    def test_non_numeric_rejected(self):
        with pytest.raises(ValueError, match="must be numeric"):
            _resolve_capital("not-a-number")


# ---------------------------------------------------------------------------
# _write_signal_csv
# ---------------------------------------------------------------------------

class TestWriteSignalCsv:
    """The per-day CSV must contain 17 JP rows with the canonical schema."""

    def test_writes_17_rows_with_expected_columns(self, tmp_path: Path):
        signal = _dummy_signal_result()
        lots = _dummy_lot_result(signal)
        out = tmp_path / "2026-05-15.csv"

        _write_signal_csv(signal, lots, out)

        with out.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert reader.fieldnames == [
            "date", "ticker", "score", "rank", "position", "suggested_lots",
        ]
        assert len(rows) == 17
        assert {r["ticker"] for r in rows} == set(JP_TICKERS)
        assert {r["date"] for r in rows} == {"2026-05-15"}

    def test_positions_match_baskets(self, tmp_path: Path):
        signal = _dummy_signal_result()
        lots = _dummy_lot_result(signal)
        out = tmp_path / "2026-05-15.csv"

        _write_signal_csv(signal, lots, out)

        df = pd.read_csv(out)
        long_rows = df.loc[df["position"] == "long", "ticker"].tolist()
        short_rows = df.loc[df["position"] == "short", "ticker"].tolist()
        neutral_rows = df.loc[df["position"] == "neutral", "ticker"].tolist()

        assert set(long_rows) == set(signal["long_basket"])
        assert set(short_rows) == set(signal["short_basket"])
        assert len(neutral_rows) == 17 - 5 - 5
        # Suggested lots: 0 for neutral, positive for long/short rows.
        assert (df.loc[df["position"] == "neutral", "suggested_lots"] == 0).all()
        assert (df.loc[df["position"] != "neutral", "suggested_lots"] > 0).all()

    def test_rank_is_unique_and_monotonic_with_score(self, tmp_path: Path):
        signal = _dummy_signal_result()
        lots = _dummy_lot_result(signal)
        out = tmp_path / "out.csv"

        _write_signal_csv(signal, lots, out)

        df = pd.read_csv(out)
        # 17 distinct ranks covering 1..17.
        assert sorted(df["rank"].tolist()) == list(range(1, 18))
        # Highest score → rank 1, lowest → rank 17.
        sorted_by_rank = df.sort_values("rank")
        assert sorted_by_rank["score"].is_monotonic_decreasing


# ---------------------------------------------------------------------------
# _build_history / _write_docs_data_json
# ---------------------------------------------------------------------------

class TestDocsDataJson:
    """The dashboard payload must include current + history."""

    def test_history_aggregates_recent_csvs(self, tmp_path: Path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        # Write three valid per-day CSVs.
        for date in ["2026-05-13", "2026-05-14", "2026-05-15"]:
            sig = _dummy_signal_result(pd.Timestamp(date))
            _write_signal_csv(sig, _dummy_lot_result(sig), signals_dir / f"{date}.csv")

        history = _build_history(signals_dir, limit=10)

        assert len(history) == 3
        assert [h["date"] for h in history] == [
            "2026-05-13", "2026-05-14", "2026-05-15",
        ]
        for entry in history:
            assert len(entry["long"]) == 5
            assert len(entry["short"]) == 5

    def test_history_respects_limit(self, tmp_path: Path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        # 5 CSVs but ask for only 2.
        for date in ["2026-05-11", "2026-05-12", "2026-05-13",
                     "2026-05-14", "2026-05-15"]:
            sig = _dummy_signal_result(pd.Timestamp(date))
            _write_signal_csv(sig, _dummy_lot_result(sig), signals_dir / f"{date}.csv")

        history = _build_history(signals_dir, limit=2)

        assert len(history) == 2
        # Most recent two only.
        assert [h["date"] for h in history] == ["2026-05-14", "2026-05-15"]

    def test_history_skips_corrupt_csv(self, tmp_path: Path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        sig = _dummy_signal_result(pd.Timestamp("2026-05-15"))
        _write_signal_csv(sig, _dummy_lot_result(sig), signals_dir / "2026-05-15.csv")
        # A corrupt sibling — must not crash the build.
        (signals_dir / "2026-05-14.csv").write_text("not,a,real,csv\n")

        history = _build_history(signals_dir, limit=10)

        # The corrupt file is dropped (missing 'position' column).
        assert [h["date"] for h in history] == ["2026-05-15"]

    def test_docs_payload_schema(self, tmp_path: Path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        sig = _dummy_signal_result(pd.Timestamp("2026-05-15"))
        _write_signal_csv(sig, _dummy_lot_result(sig), signals_dir / "2026-05-15.csv")

        out = tmp_path / "data.json"
        _write_docs_data_json(sig, signals_dir, out)

        payload = json.loads(out.read_text())
        # New schema: basket_size sits alongside the legacy top-level keys.
        assert set(payload.keys()) == {
            "last_updated", "basket_size", "current_signal", "history",
        }
        assert payload["basket_size"] == 5
        cur = payload["current_signal"]
        assert cur["date"] == "2026-05-15"
        assert len(cur["long_basket"]) == 5
        assert len(cur["short_basket"]) == 5
        assert len(cur["factor_scores"]) == 3
        assert set(cur["all_scores"].keys()) == set(JP_TICKERS)
        assert len(payload["history"]) == 1
        # Every history entry must carry realized_return; here oc_returns
        # is not supplied so the field is null.
        assert payload["history"][0]["realized_return"] is None


# ---------------------------------------------------------------------------
# realized_return — backward-looking P/L attribution
# ---------------------------------------------------------------------------

def _make_oc_returns(
    dates: list[pd.Timestamp],
    long_basket: list[str],
    short_basket: list[str],
    *,
    long_value: float,
    short_value: float,
    other_value: float = 0.0,
) -> pd.DataFrame:
    """Build a deterministic JP OC returns frame for realized_return tests.

    Every row gets ``long_value`` for the long-basket tickers,
    ``short_value`` for the short-basket tickers and ``other_value``
    elsewhere — so the expected equal-weighted long-short realized
    return is simply ``long_value - short_value`` per row.
    """
    data = np.full((len(dates), len(JP_TICKERS)), other_value, dtype=float)
    df = pd.DataFrame(data, index=pd.DatetimeIndex(dates), columns=JP_TICKERS)
    df.loc[:, long_basket] = long_value
    df.loc[:, short_basket] = short_value
    return df


class TestRealizedReturn:
    """Realized strategy return must use t+1 OC, never t or earlier."""

    def test_history_entries_include_realized_return_key(self, tmp_path: Path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        sig = _dummy_signal_result(pd.Timestamp("2026-05-15"))
        _write_signal_csv(
            sig, _dummy_lot_result(sig), signals_dir / "2026-05-15.csv"
        )

        history = _build_history(signals_dir, limit=10)

        assert len(history) == 1
        # Schema: every entry carries the new key, even without oc_returns.
        assert set(history[0].keys()) == {
            "date", "long", "short", "realized_return",
        }
        assert history[0]["realized_return"] is None

    def test_realized_return_uses_t_plus_one_oc(self, tmp_path: Path):
        """For date t, realized_return must equal long_avg - short_avg on t+1."""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        sig_t = _dummy_signal_result(pd.Timestamp("2026-05-14"))
        sig_t1 = _dummy_signal_result(pd.Timestamp("2026-05-15"))
        _write_signal_csv(
            sig_t, _dummy_lot_result(sig_t), signals_dir / "2026-05-14.csv"
        )
        _write_signal_csv(
            sig_t1, _dummy_lot_result(sig_t1), signals_dir / "2026-05-15.csv"
        )

        # OC returns crafted so that ON t+1 = 2026-05-15, every long
        # ticker (of the t basket) earns +1% and every short ticker
        # earns -0.5%, while all other tickers are flat.  Expected
        # realized strategy return for t = 2026-05-14 is therefore
        # 0.01 - (-0.005) = 0.015 = 1.5%.
        oc = _make_oc_returns(
            dates=[pd.Timestamp("2026-05-14"), pd.Timestamp("2026-05-15")],
            long_basket=sig_t["long_basket"],
            short_basket=sig_t["short_basket"],
            long_value=0.01,
            short_value=-0.005,
        )

        history = _build_history(signals_dir, limit=10, oc_returns=oc)

        # Two entries: t (with realized_return) and t+1 (no t+2 → None).
        assert len(history) == 2
        entry_t, entry_t1 = history[0], history[1]
        assert entry_t["date"] == "2026-05-14"
        assert entry_t1["date"] == "2026-05-15"

        assert entry_t["realized_return"] == pytest.approx(0.015)
        # The most recent entry has no t+1 available → must stay null.
        assert entry_t1["realized_return"] is None

    def test_realized_return_is_null_for_latest_signal(self, tmp_path: Path):
        """The current signal day has no t+1 OC yet — must be null."""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        sig = _dummy_signal_result(pd.Timestamp("2026-05-15"))
        _write_signal_csv(
            sig, _dummy_lot_result(sig), signals_dir / "2026-05-15.csv"
        )

        # OC frame ends *on* the signal date — no t+1 row.
        oc = _make_oc_returns(
            dates=[pd.Timestamp("2026-05-14"), pd.Timestamp("2026-05-15")],
            long_basket=sig["long_basket"],
            short_basket=sig["short_basket"],
            long_value=0.02,
            short_value=-0.01,
        )

        history = _build_history(signals_dir, limit=10, oc_returns=oc)

        assert len(history) == 1
        assert history[0]["realized_return"] is None

    def test_realized_return_uses_only_t_plus_one_row(self, tmp_path: Path):
        """Realized return must not contaminate t with OC from t or earlier.

        Concretely: if t-1's OC and t's OC are both extreme but t+1's OC
        is zero on every ticker, the realised return at date t must be
        exactly zero — i.e. only the t+1 row is consulted.
        """
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        sig_t_minus_1 = _dummy_signal_result(pd.Timestamp("2026-05-13"))
        sig_t = _dummy_signal_result(pd.Timestamp("2026-05-14"))
        sig_t_plus_1 = _dummy_signal_result(pd.Timestamp("2026-05-15"))
        for s, day in [
            (sig_t_minus_1, "2026-05-13"),
            (sig_t, "2026-05-14"),
            (sig_t_plus_1, "2026-05-15"),
        ]:
            _write_signal_csv(s, _dummy_lot_result(s), signals_dir / f"{day}.csv")

        # OC values that would *break* the test if any other row leaked
        # into the realised-return calculation for date t.
        dates = [
            pd.Timestamp("2026-05-13"),
            pd.Timestamp("2026-05-14"),
            pd.Timestamp("2026-05-15"),
        ]
        oc = pd.DataFrame(
            0.0, index=pd.DatetimeIndex(dates), columns=JP_TICKERS
        )
        # t-1 row: large positive on long, large negative on short.
        oc.loc[dates[0], sig_t["long_basket"]] = 99.0
        oc.loc[dates[0], sig_t["short_basket"]] = -99.0
        # t row: large negative on long, large positive on short.
        oc.loc[dates[1], sig_t["long_basket"]] = -99.0
        oc.loc[dates[1], sig_t["short_basket"]] = 99.0
        # t+1 row: all zeros (the row that *should* be consulted).

        history = _build_history(signals_dir, limit=10, oc_returns=oc)

        entry_t = next(h for h in history if h["date"] == "2026-05-14")
        assert entry_t["realized_return"] == pytest.approx(0.0)

    def test_docs_payload_carries_basket_size_and_realized_history(
        self, tmp_path: Path
    ):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        sig_t = _dummy_signal_result(pd.Timestamp("2026-05-14"))
        sig_t1 = _dummy_signal_result(pd.Timestamp("2026-05-15"))
        _write_signal_csv(
            sig_t, _dummy_lot_result(sig_t), signals_dir / "2026-05-14.csv"
        )
        _write_signal_csv(
            sig_t1, _dummy_lot_result(sig_t1), signals_dir / "2026-05-15.csv"
        )
        oc = _make_oc_returns(
            dates=[pd.Timestamp("2026-05-14"), pd.Timestamp("2026-05-15")],
            long_basket=sig_t["long_basket"],
            short_basket=sig_t["short_basket"],
            long_value=0.01,
            short_value=-0.005,
        )

        out = tmp_path / "data.json"
        _write_docs_data_json(
            sig_t1, signals_dir, out, oc_returns=oc, basket_size=5,
        )

        payload = json.loads(out.read_text())
        assert payload["basket_size"] == 5
        # First history entry (t) has a real number; second (latest) is null.
        h0, h1 = payload["history"][0], payload["history"][1]
        assert h0["date"] == "2026-05-14"
        assert h0["realized_return"] == pytest.approx(0.015)
        assert h1["date"] == "2026-05-15"
        assert h1["realized_return"] is None


# ---------------------------------------------------------------------------
# run_pipeline — end-to-end orchestrator with all I/O mocked
# ---------------------------------------------------------------------------

class TestRunPipeline:
    """End-to-end orchestrator behaviour with all external I/O mocked."""

    @staticmethod
    def _patch_pipeline(monkeypatch, *, signal_result=None, lot_result=None,
                        send_ret=True, raise_step: str | None = None):
        """Install mocks on the names imported into ``src.main``.

        Returns a dict of the installed mocks for assertions.
        """
        open_df, close_df = _dummy_ohlc()
        signal_result = signal_result or _dummy_signal_result(close_df.index[-1])
        lot_result = lot_result or _dummy_lot_result(signal_result)

        def maybe_raise(step: str, ret):
            def _fn(*args, **kwargs):
                if raise_step == step:
                    raise RuntimeError(f"boom@{step}")
                return ret
            return _fn

        mocks = {
            "fetch_prices": MagicMock(
                side_effect=maybe_raise("fetch_prices", (open_df, close_df)),
            ),
            "load_prior_correlation": MagicMock(
                side_effect=maybe_raise(
                    "load_prior_correlation", np.eye(len(ALL_TICKERS))
                ),
            ),
            "generate_signal": MagicMock(
                side_effect=maybe_raise("generate_signal", signal_result),
            ),
            "fetch_latest_prices": MagicMock(
                side_effect=maybe_raise(
                    "fetch_latest_prices",
                    {tk: 1000.0 + i for i, tk in enumerate(
                        signal_result["long_basket"] + signal_result["short_basket"]
                    )},
                ),
            ),
            "calculate_lots": MagicMock(
                side_effect=maybe_raise("calculate_lots", lot_result),
            ),
            "format_signal_message": MagicMock(
                side_effect=maybe_raise("format_signal_message", "stub message"),
            ),
            "send_line_message": MagicMock(
                side_effect=maybe_raise("send_line_message", send_ret),
            ),
            "send_error_notification": MagicMock(return_value=True),
        }
        for name, mock in mocks.items():
            monkeypatch.setattr(main_module, name, mock)
        return mocks, signal_result, lot_result

    def test_happy_path_calls_each_step_in_order(self, tmp_path, monkeypatch):
        mocks, signal, lots = self._patch_pipeline(monkeypatch)

        summary = run_pipeline(
            capital_jpy=5_000_000,
            line_token="TKN",
            line_user_id="U" * 33,
            cache_path=tmp_path / "cache.csv",
            prior_path=tmp_path / "prior.npy",
            signals_dir=tmp_path / "signals",
            docs_data_path=tmp_path / "docs" / "data.json",
        )

        assert summary["steps"] == ["data", "prior", "signal", "lots", "line", "save"]
        assert summary["line_pushed"] is True

        mocks["fetch_prices"].assert_called_once()
        mocks["load_prior_correlation"].assert_called_once()
        mocks["generate_signal"].assert_called_once()
        mocks["fetch_latest_prices"].assert_called_once()
        mocks["calculate_lots"].assert_called_once()
        mocks["format_signal_message"].assert_called_once()
        mocks["send_line_message"].assert_called_once()
        mocks["send_error_notification"].assert_not_called()

        # Files were written.
        date_str = signal["date"].strftime("%Y-%m-%d")
        assert (tmp_path / "signals" / f"{date_str}.csv").exists()
        assert (tmp_path / "docs" / "data.json").exists()

    def test_skips_line_push_when_creds_missing(self, tmp_path, monkeypatch):
        mocks, signal, _ = self._patch_pipeline(monkeypatch)

        summary = run_pipeline(
            capital_jpy=5_000_000,
            line_token="",
            line_user_id="",
            cache_path=tmp_path / "cache.csv",
            prior_path=tmp_path / "prior.npy",
            signals_dir=tmp_path / "signals",
            docs_data_path=tmp_path / "docs" / "data.json",
        )

        mocks["send_line_message"].assert_not_called()
        # ... but file outputs still happen.
        date_str = signal["date"].strftime("%Y-%m-%d")
        assert (tmp_path / "signals" / f"{date_str}.csv").exists()
        assert summary["line_pushed"] is False

    def test_send_line_message_false_does_not_abort(self, tmp_path, monkeypatch):
        mocks, signal, _ = self._patch_pipeline(monkeypatch, send_ret=False)

        summary = run_pipeline(
            capital_jpy=5_000_000,
            line_token="TKN",
            line_user_id="U" * 33,
            cache_path=tmp_path / "cache.csv",
            prior_path=tmp_path / "prior.npy",
            signals_dir=tmp_path / "signals",
            docs_data_path=tmp_path / "docs" / "data.json",
        )

        assert summary["line_pushed"] is False
        assert summary["steps"] == ["data", "prior", "signal", "lots", "line", "save"]
        # Files still written.
        date_str = signal["date"].strftime("%Y-%m-%d")
        assert (tmp_path / "signals" / f"{date_str}.csv").exists()
        assert (tmp_path / "docs" / "data.json").exists()
        mocks["send_error_notification"].assert_not_called()

    def test_signal_failure_triggers_error_notification_and_reraises(
        self, tmp_path, monkeypatch
    ):
        mocks, _, _ = self._patch_pipeline(monkeypatch, raise_step="generate_signal")

        with pytest.raises(RuntimeError, match="boom@generate_signal"):
            run_pipeline(
                capital_jpy=5_000_000,
                line_token="TKN",
                line_user_id="U" * 33,
                cache_path=tmp_path / "cache.csv",
                prior_path=tmp_path / "prior.npy",
                signals_dir=tmp_path / "signals",
                docs_data_path=tmp_path / "docs" / "data.json",
            )

        mocks["send_error_notification"].assert_called_once()
        sent_msg, token, user_id = mocks["send_error_notification"].call_args.args
        assert token == "TKN"
        assert user_id == "U" * 33
        assert "boom@generate_signal" in sent_msg

    def test_failure_without_creds_still_reraises(self, tmp_path, monkeypatch):
        mocks, _, _ = self._patch_pipeline(monkeypatch, raise_step="fetch_prices")

        with pytest.raises(RuntimeError, match="boom@fetch_prices"):
            run_pipeline(
                capital_jpy=5_000_000,
                line_token="",
                line_user_id="",
                cache_path=tmp_path / "cache.csv",
                prior_path=tmp_path / "prior.npy",
                signals_dir=tmp_path / "signals",
                docs_data_path=tmp_path / "docs" / "data.json",
            )

        # No creds → no LINE error push, but exception still propagates.
        mocks["send_error_notification"].assert_not_called()


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------

class TestMainEntry:
    """``main()`` should resolve env vars and delegate to ``run_pipeline``."""

    def test_main_passes_env_to_run_pipeline(self, monkeypatch):
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "TKN")
        monkeypatch.setenv("LINE_USER_ID", "U" * 33)
        monkeypatch.setenv("CAPITAL_JPY", "7000000")

        fake_run = MagicMock(return_value={"steps": []})
        monkeypatch.setattr(main_module, "run_pipeline", fake_run)
        # Avoid clobbering env from a real .env file.
        monkeypatch.setattr(main_module, "load_dotenv", lambda *a, **kw: None)

        rc = main_module.main()

        assert rc == 0
        fake_run.assert_called_once()
        kwargs = fake_run.call_args.kwargs
        assert kwargs["capital_jpy"] == 7_000_000.0
        assert kwargs["line_token"] == "TKN"
        assert kwargs["line_user_id"] == "U" * 33

    def test_main_uses_default_capital_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("CAPITAL_JPY", raising=False)
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "TKN")
        monkeypatch.setenv("LINE_USER_ID", "U" * 33)

        fake_run = MagicMock(return_value={"steps": []})
        monkeypatch.setattr(main_module, "run_pipeline", fake_run)
        monkeypatch.setattr(main_module, "load_dotenv", lambda *a, **kw: None)

        main_module.main()

        kwargs = fake_run.call_args.kwargs
        assert kwargs["capital_jpy"] == float(DEFAULT_CAPITAL_JPY)
