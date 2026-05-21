"""
LINE Messaging API push notifier for daily signals (SECTION 6).

The module wraps the LINE Push Message endpoint
(``POST https://api.line.me/v2/bot/message/push``) with the bare
``requests`` library — no LINE SDK dependency.

Two text formatters are provided:

* :func:`format_signal_message` — turns the outputs of
  :func:`src.signal_generator.generate_signal` and
  :func:`src.lot_calculator.calculate_lots` into a single LINE-ready
  text body with sector names (from
  :data:`src.universe.JP_SECTOR_NAMES`).
* :func:`send_error_notification` — formats an error trace into a
  short alert so GitHub Actions / cron failures surface immediately
  on the user's phone.

Both formatters keep the message well under LINE's 5000-character
text limit by truncating long error bodies and using compact column
layouts for the basket tables.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import requests

from src.universe import JP_SECTOR_NAMES

logger = logging.getLogger(__name__)

__all__ = [
    "LINE_PUSH_ENDPOINT",
    "format_signal_message",
    "send_error_notification",
    "send_line_message",
]

LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
_REQUEST_TIMEOUT_S = 10.0
_LINE_TEXT_LIMIT = 4900  # LINE allows 5000 chars; keep a small margin


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_basket_row(row: Mapping[str, Any]) -> str:
    """One line for the long/short table: ``T123  業種  数量=N``."""
    sector = JP_SECTOR_NAMES.get(row["ticker"], "?")
    # 業種名は最大 9 文字（情報通信・サービスその他）に揃える
    return f"  {row['ticker']:8s}{sector:<10s} 数量={row['lots']:>3d}"


def format_signal_message(
    signal_result: Mapping[str, Any],
    lot_result: Mapping[str, Any],
    capital_jpy: float,
) -> str:
    """Render a daily signal as a LINE text body.

    Parameters
    ----------
    signal_result
        Output of :func:`src.signal_generator.generate_signal`.  Must
        contain ``date``, ``long_basket``, ``short_basket``, and
        ``factor_scores``.
    lot_result
        Output of :func:`src.lot_calculator.calculate_lots`.  Must
        contain ``long`` and ``short`` lists with ``ticker`` / ``lots``
        per row, plus aggregate fields ``total_long_value``,
        ``total_short_value``, ``total_gross_exposure``,
        ``cash_remaining``.
    capital_jpy
        Capital budget passed to :func:`calculate_lots`.  Echoed in the
        header for confirmation.

    Returns
    -------
    str
        Plain-text LINE message body.  Emoji are used as section
        separators (LINE supports UTF-8 emoji in text messages).
    """
    date_str = signal_result["date"].strftime("%Y-%m-%d") \
        if hasattr(signal_result["date"], "strftime") else str(signal_result["date"])

    factor_scores = signal_result["factor_scores"]
    f_str = ", ".join(f"PC{i+1}={float(s):+.3f}" for i, s in enumerate(factor_scores))

    long_rows = "\n".join(_format_basket_row(r) for r in lot_result["long"])
    short_rows = "\n".join(_format_basket_row(r) for r in lot_result["short"])

    lines = [
        f"[{date_str}] 日米業種リードラグ シグナル",
        "",
        f"資金: {capital_jpy:,.0f} 円",
        "",
        "買い（上位5）:",
        long_rows,
        "",
        "売り（下位5）:",
        short_rows,
        "",
        f"ファクタースコア: {f_str}",
        "",
        "エクスポージャー:",
        f"  買い : {lot_result['total_long_value']:>12,.0f}",
        f"  売り : {lot_result['total_short_value']:>12,.0f}",
        f"  総額 : {lot_result['total_gross_exposure']:>12,.0f}",
        f"  余力 : {lot_result['cash_remaining']:>12,.0f}",
    ]
    message = "\n".join(lines)
    if len(message) > _LINE_TEXT_LIMIT:
        message = message[: _LINE_TEXT_LIMIT - 3] + "..."
    return message


def send_error_notification(
    error_message: str,
    channel_access_token: str,
    user_id: str,
) -> bool:
    """Wrap an error message in a standard alert envelope and push to LINE.

    The envelope contains an ISO-8601 timestamp in JST plus the error
    body (truncated to keep the LINE payload under the 5000-character
    limit).  Returns the result of :func:`send_line_message`.
    """
    jst = ZoneInfo("Asia/Tokyo")
    timestamp = datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S %Z")
    # Reserve ~200 chars for the envelope; truncate the body if needed.
    body_limit = _LINE_TEXT_LIMIT - 200
    body = error_message if len(error_message) <= body_limit \
        else error_message[: body_limit - 3] + "..."
    msg = (
        "[エラー] 日米業種リードラグ パイプライン\n"
        f"時刻: {timestamp}\n"
        "----\n"
        f"{body}"
    )
    return send_line_message(msg, channel_access_token, user_id)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def send_line_message(
    message: str,
    channel_access_token: str,
    user_id: str,
) -> bool:
    """Push a text message to ``user_id`` via the LINE Push Message API.

    Parameters
    ----------
    message
        Plain text (UTF-8).  Must be 1..5000 characters.
    channel_access_token
        Long-lived channel access token issued from LINE Developers
        Console (``Messaging API設定`` → ``チャネルアクセストークン（長期）``).
    user_id
        LINE user ID (``U`` followed by 32 hex chars).  Typically the
        developer's own user ID from ``チャネル基本設定 → あなたのユーザーID``.

    Returns
    -------
    bool
        ``True`` on HTTP 200 from LINE; ``False`` on any other status,
        connection error, or timeout.  Network failures are logged but
        never raised — callers can treat the return value as a
        success/failure switch without wrapping in try/except.

    Notes
    -----
    The function is **not** retried internally; the caller decides
    retry policy.  The 10-second timeout is meant to make a failing
    push fail fast under GitHub Actions where the cron has a hard
    wall-clock budget.
    """
    if not isinstance(message, str) or not message:
        logger.error("send_line_message: message must be a non-empty str")
        return False
    if not isinstance(channel_access_token, str) or not channel_access_token:
        logger.error("send_line_message: channel_access_token must be non-empty")
        return False
    if not isinstance(user_id, str) or not user_id:
        logger.error("send_line_message: user_id must be non-empty")
        return False
    if len(message) > 5000:
        logger.error("send_line_message: message exceeds LINE 5000-char limit")
        return False

    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
    }
    try:
        resp = requests.post(
            LINE_PUSH_ENDPOINT,
            headers=headers,
            data=json.dumps(payload),
            timeout=_REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.error("LINE push failed (network): %r", exc)
        return False

    if resp.status_code == 200:
        logger.info("LINE push OK (user=%s..., len=%d chars)", user_id[:6], len(message))
        return True

    # Surface the LINE error envelope so log readers can debug fast.
    try:
        err_json = resp.json()
    except ValueError:
        err_json = {"raw": resp.text[:500]}
    logger.error(
        "LINE push failed (HTTP %d): %s", resp.status_code, err_json,
    )
    return False
