"""
Lot sizing for the daily long/short basket (SECTION 5).

Given a capital budget in JPY and the long / short basket produced by
:func:`src.signal_generator.generate_signal`, compute how many tradeable
lots (単元) to buy / short for each ticker.  TOPIX-17 sector ETFs trade
in 10-share units (単元株式数 = 10).

Allocation rule
---------------
* 50 % of capital is earmarked for the long side, 50 % for the short
  side.  Inside each side the budget is distributed evenly across the
  tickers (``capital_jpy * 0.5 / len(tickers)`` per ticker).
* For each ticker, ``shares = floor(target_jpy / price)`` is rounded
  down to the nearest tradeable unit:
  ``lots = floor(shares / unit_size)`` and the actually-investable
  share count becomes ``lots * unit_size``.
* ``cash_remaining = capital_jpy − (total_long_value + total_short_value)``
  is reported so the caller can detect under-utilisation.

The function is pure arithmetic — it never touches the network.
:func:`fetch_latest_prices` is the only network-bound helper.
"""

from __future__ import annotations

import logging
import math
from typing import Iterable, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "calculate_lots",
    "fetch_latest_prices",
]


# ---------------------------------------------------------------------------
# Pure lot sizing
# ---------------------------------------------------------------------------

def _allocate_side(
    tickers: list[str],
    side_capital: float,
    prices_dict: Mapping[str, float],
    unit_size: int,
) -> tuple[list[dict], float]:
    """Allocate one side (long or short) and return ``(rows, total_value)``."""
    if not tickers:
        return [], 0.0
    target_per_ticker = side_capital / len(tickers)

    rows: list[dict] = []
    total_value = 0.0
    for tk in tickers:
        if tk not in prices_dict:
            raise ValueError(f"price for {tk!r} not in prices_dict")
        price = float(prices_dict[tk])
        if not math.isfinite(price) or price <= 0:
            raise ValueError(
                f"invalid price for {tk!r}: {price} (must be finite and > 0)"
            )

        raw_shares = math.floor(target_per_ticker / price)
        lots = raw_shares // unit_size
        shares = lots * unit_size
        value = shares * price
        total_value += value

        rows.append({
            "ticker": tk,
            "lots": int(lots),
            "shares": int(shares),
            "price": price,
            "value": float(value),
        })
    return rows, total_value


def calculate_lots(
    capital_jpy: float,
    long_tickers: Iterable[str],
    short_tickers: Iterable[str],
    prices_dict: Mapping[str, float],
    unit_size: int = 10,
) -> dict:
    """Compute lot sizes for the long / short baskets.

    Parameters
    ----------
    capital_jpy
        Total capital budget in JPY.  Half is allocated to the long
        side, half to the short side.
    long_tickers, short_tickers
        Iterables of JP tickers (e.g. ``"1618.T"``) that form the
        baskets.  Typically each contains 5 tickers, but any positive
        length is accepted.
    prices_dict
        Mapping ``ticker → price`` (JPY per share, most-recent close).
        Every ticker in ``long_tickers`` and ``short_tickers`` must be
        a key.
    unit_size
        Tradeable unit (単元株式数).  TOPIX-17 sector ETFs default to
        10 shares per lot.

    Returns
    -------
    dict
        ``{
            'long':   [{'ticker', 'lots', 'shares', 'price', 'value'}, ...],
            'short':  [...],
            'total_long_value':     float,
            'total_short_value':    float,
            'total_gross_exposure': float,
            'cash_remaining':       float,
        }``

    Raises
    ------
    ValueError
        If ``capital_jpy`` is non-positive, ``unit_size`` is not a
        positive integer, ``prices_dict`` is missing a ticker, or any
        price is non-positive / non-finite.
    """
    if not (isinstance(capital_jpy, (int, float)) and math.isfinite(capital_jpy)):
        raise ValueError(f"capital_jpy must be finite, got {capital_jpy!r}")
    if capital_jpy <= 0:
        raise ValueError(f"capital_jpy must be > 0, got {capital_jpy}")
    if not (isinstance(unit_size, int) and unit_size > 0):
        raise ValueError(f"unit_size must be a positive int, got {unit_size!r}")

    long_list = list(long_tickers)
    short_list = list(short_tickers)
    if not long_list and not short_list:
        raise ValueError("at least one of long_tickers / short_tickers must be non-empty")

    side_capital = capital_jpy * 0.5
    long_rows, total_long = _allocate_side(long_list, side_capital, prices_dict, unit_size)
    short_rows, total_short = _allocate_side(short_list, side_capital, prices_dict, unit_size)

    gross_exposure = total_long + total_short
    cash_remaining = capital_jpy - gross_exposure

    return {
        "long": long_rows,
        "short": short_rows,
        "total_long_value": float(total_long),
        "total_short_value": float(total_short),
        "total_gross_exposure": float(gross_exposure),
        "cash_remaining": float(cash_remaining),
    }


# ---------------------------------------------------------------------------
# Live price fetch
# ---------------------------------------------------------------------------

def fetch_latest_prices(tickers: Iterable[str]) -> dict[str, float]:
    """Return ``ticker → most-recent price`` from yfinance.

    Uses ``yf.Ticker(ticker).fast_info["last_price"]`` for each ticker,
    which is the lightweight quote endpoint (no full history download).

    Parameters
    ----------
    tickers
        Iterable of yfinance ticker symbols (e.g. ``"1618.T"``).

    Returns
    -------
    dict[str, float]
        Mapping ``ticker → price (JPY for .T tickers, USD for US)``.

    Raises
    ------
    RuntimeError
        If any ticker's last price cannot be retrieved.  The error
        message lists every failing ticker so the caller can decide
        whether to retry the full request or fall back to cached
        prices.
    """
    # Local import keeps yfinance off the import path for offline unit tests.
    import yfinance as yf

    ticker_list = list(tickers)
    if not ticker_list:
        raise ValueError("tickers must contain at least one symbol")
    if len(set(ticker_list)) != len(ticker_list):
        raise ValueError("tickers must be unique")

    out: dict[str, float] = {}
    failures: list[tuple[str, str]] = []
    for tk in ticker_list:
        try:
            info = yf.Ticker(tk).fast_info
            # fast_info supports both attribute and mapping access; the
            # attribute form (``info.last_price``) is documented for
            # yfinance >= 0.2 — fall back to mapping access if needed.
            price = getattr(info, "last_price", None)
            if price is None:
                price = info["last_price"]  # type: ignore[index]
            if price is None or not math.isfinite(float(price)) or float(price) <= 0:
                raise RuntimeError(f"invalid last_price: {price!r}")
            out[tk] = float(price)
        except Exception as exc:  # noqa: BLE001 — surface every failure
            failures.append((tk, repr(exc)))

    if failures:
        details = "; ".join(f"{tk}: {err}" for tk, err in failures)
        raise RuntimeError(
            f"fetch_latest_prices failed for {len(failures)} ticker(s): {details}"
        )

    return out
