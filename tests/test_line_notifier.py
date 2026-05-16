"""Unit tests for :mod:`src.line_notifier` (SECTION 6)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest
import requests

from src.line_notifier import (
    LINE_PUSH_ENDPOINT,
    format_signal_message,
    send_error_notification,
    send_line_message,
)
from src.universe import JP_SECTOR_NAMES


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _dummy_signal_result() -> dict:
    long_basket = ["1618.T", "1629.T", "1625.T", "1631.T", "1624.T"]
    short_basket = ["1633.T", "1627.T", "1621.T", "1630.T", "1617.T"]
    return {
        "date": pd.Timestamp("2026-05-15"),
        "long_basket": long_basket,
        "short_basket": short_basket,
        "all_scores": pd.Series([0.0] * 17),  # not used by formatter
        "factor_scores": np.array([0.7412, -3.0478, -0.5333]),
    }


def _dummy_lot_result() -> dict:
    long = [
        {"ticker": "1618.T", "lots": 1,   "shares": 10,   "price": 36390.0, "value": 363_900.0},
        {"ticker": "1629.T", "lots": 168, "shares": 1680, "price":   296.8, "value": 498_624.0},
        {"ticker": "1625.T", "lots": 0,   "shares": 0,    "price": 60170.0, "value":       0.0},
        {"ticker": "1631.T", "lots": 1,   "shares": 10,   "price": 34440.0, "value": 344_400.0},
        {"ticker": "1624.T", "lots": 0,   "shares": 0,    "price": 88520.0, "value":       0.0},
    ]
    short = [
        {"ticker": "1633.T", "lots": 0,  "shares": 0,   "price": 52970.0, "value":       0.0},
        {"ticker": "1627.T", "lots": 4,  "shares": 40,  "price": 11905.0, "value": 476_200.0},
        {"ticker": "1621.T", "lots": 1,  "shares": 10,  "price": 30350.0, "value": 303_500.0},
        {"ticker": "1630.T", "lots": 1,  "shares": 10,  "price": 35840.0, "value": 358_400.0},
        {"ticker": "1617.T", "lots": 10, "shares": 100, "price":  4551.0, "value": 455_100.0},
    ]
    total_long = sum(r["value"] for r in long)
    total_short = sum(r["value"] for r in short)
    return {
        "long": long,
        "short": short,
        "total_long_value": total_long,
        "total_short_value": total_short,
        "total_gross_exposure": total_long + total_short,
        "cash_remaining": 5_000_000 - (total_long + total_short),
    }


# ---------------------------------------------------------------------------
# format_signal_message
# ---------------------------------------------------------------------------

def test_format_signal_message_contains_all_tickers_and_sectors():
    msg = format_signal_message(_dummy_signal_result(), _dummy_lot_result(), 5_000_000)
    # All 10 tickers appear
    for tk in ["1618.T", "1629.T", "1625.T", "1631.T", "1624.T",
               "1633.T", "1627.T", "1621.T", "1630.T", "1617.T"]:
        assert tk in msg, f"ticker {tk} not in message"
    # Sample sector names appear (full long names get truncated, so look at the prefix)
    for tk in ["1618.T", "1629.T", "1631.T", "1617.T"]:
        sector_prefix = JP_SECTOR_NAMES[tk][:3]  # first 3 chars survive any width slicing
        assert sector_prefix in msg, f"sector for {tk} ({JP_SECTOR_NAMES[tk]}) not in message"


def test_format_signal_message_has_capital_and_factor_scores():
    msg = format_signal_message(_dummy_signal_result(), _dummy_lot_result(), 5_000_000)
    assert "5,000,000" in msg, "capital should be formatted with thousand separators"
    # PC1=+0.741 PC2=-3.048 PC3=-0.533 (3 decimal places)
    assert "PC1=+0.741" in msg
    assert "PC2=-3.048" in msg
    assert "PC3=-0.533" in msg


def test_format_signal_message_has_aggregate_exposure():
    lot_result = _dummy_lot_result()
    msg = format_signal_message(_dummy_signal_result(), lot_result, 5_000_000)
    # Aggregate values must appear (thousand-separated)
    for key in ("total_long_value", "total_short_value", "total_gross_exposure", "cash_remaining"):
        assert f"{lot_result[key]:,.0f}" in msg, f"{key} not in message"


def test_format_signal_message_includes_lot_counts():
    """Lot counts should be visible per row (e.g., lots=168, lots=10)."""
    msg = format_signal_message(_dummy_signal_result(), _dummy_lot_result(), 5_000_000)
    assert "lots=168" in msg  # 1629.T row
    assert "lots= 10" in msg or "lots=10" in msg  # 1617.T row


def test_format_signal_message_truncates_when_too_long():
    """Pathological inputs longer than the LINE limit must still produce ≤ 4900 chars."""
    sig = _dummy_signal_result()
    lot = _dummy_lot_result()
    # Hugely inflate the long basket to push past the 5000-char limit
    huge_row = {"ticker": "9999.T", "lots": 1, "shares": 10, "price": 1.0, "value": 10.0}
    lot["long"] = [huge_row] * 5000  # ~50 chars * 5000 = 250k chars worth of basket rows
    msg = format_signal_message(sig, lot, 5_000_000)
    assert len(msg) <= 4900
    assert msg.endswith("...")


# ---------------------------------------------------------------------------
# send_line_message — input validation
# ---------------------------------------------------------------------------

def test_send_line_message_empty_message_returns_false(caplog):
    assert send_line_message("", "tok", "U123") is False


def test_send_line_message_empty_token_returns_false():
    assert send_line_message("hi", "", "U123") is False


def test_send_line_message_empty_user_id_returns_false():
    assert send_line_message("hi", "tok", "") is False


def test_send_line_message_too_long_returns_false():
    assert send_line_message("a" * 5001, "tok", "U123") is False


# ---------------------------------------------------------------------------
# send_line_message — transport (mocked)
# ---------------------------------------------------------------------------

def test_send_line_message_success_returns_true():
    with patch("src.line_notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, text="{}")
        ok = send_line_message("hello", "tok", "U123")
    assert ok is True
    # Verify the call used the right endpoint, headers, and body
    args, kwargs = mock_post.call_args
    assert args[0] == LINE_PUSH_ENDPOINT
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["timeout"] == 10.0
    # Body is JSON-encoded; parse and check it
    import json as _json
    body = _json.loads(kwargs["data"])
    assert body["to"] == "U123"
    assert body["messages"] == [{"type": "text", "text": "hello"}]


def test_send_line_message_non_200_returns_false():
    with patch("src.line_notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=401,
            json=lambda: {"message": "Authentication failed"},
            text='{"message":"Authentication failed"}',
        )
        ok = send_line_message("hello", "bad_token", "U123")
    assert ok is False


def test_send_line_message_network_error_returns_false():
    with patch("src.line_notifier.requests.post",
               side_effect=requests.ConnectionError("boom")):
        ok = send_line_message("hello", "tok", "U123")
    assert ok is False


def test_send_line_message_timeout_returns_false():
    with patch("src.line_notifier.requests.post",
               side_effect=requests.Timeout("slow")):
        ok = send_line_message("hello", "tok", "U123")
    assert ok is False


# ---------------------------------------------------------------------------
# send_error_notification
# ---------------------------------------------------------------------------

def _capture_send(sent: dict[str, str]):
    """Build a side_effect that records the rendered message and returns True."""
    def _impl(msg: str, tok: str, uid: str) -> bool:
        sent["msg"] = msg
        return True
    return _impl


def test_send_error_notification_envelope_format():
    """Error envelope must include the [ERROR] tag, a timestamp, and the body."""
    sent: dict[str, str] = {}
    with patch("src.line_notifier.send_line_message",
               side_effect=_capture_send(sent)):
        ok = send_error_notification("KeyError: 'foo'", "tok", "U123")
    assert ok is True
    assert "[ERROR]" in sent["msg"]
    assert "time:" in sent["msg"]
    assert "KeyError: 'foo'" in sent["msg"]


def test_send_error_notification_truncates_long_body():
    long_err = "X" * 10_000
    sent: dict[str, str] = {}
    with patch("src.line_notifier.send_line_message",
               side_effect=_capture_send(sent)):
        send_error_notification(long_err, "tok", "U123")
    assert len(sent["msg"]) <= 4900


# ---------------------------------------------------------------------------
# Live network smoke (skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_send_line_message_invalid_token_returns_false():
    """An obviously-invalid token must yield False — never an exception.

    This is the canonical "negative integration test" requested in the
    SECTION 6 spec.  It also confirms the transport layer is wired up
    (it actually hits api.line.me) without sending a real message.
    """
    ok = send_line_message(
        "smoke test — should never arrive",
        channel_access_token="this_is_not_a_valid_token",
        user_id="U0000000000000000000000000000000",
    )
    assert ok is False
