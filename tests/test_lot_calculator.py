"""Unit tests for :mod:`src.lot_calculator` (SECTION 5)."""

from __future__ import annotations

import math

import pytest

from src.lot_calculator import calculate_lots, fetch_latest_prices


# ---------------------------------------------------------------------------
# calculate_lots — basic / underfunded / invariants
# ---------------------------------------------------------------------------

def test_calculate_lots_basic():
    """5,000,000 JPY split 50/50 into 5 long + 5 short tickers with dummy prices."""
    capital = 5_000_000
    long_tickers = ["1618.T", "1625.T", "1629.T", "1631.T", "1624.T"]
    short_tickers = ["1617.T", "1621.T", "1627.T", "1630.T", "1633.T"]
    prices = {
        "1618.T": 2000.0, "1625.T": 2500.0, "1629.T": 3000.0,
        "1631.T": 1800.0, "1624.T": 4000.0,
        "1617.T": 2200.0, "1621.T": 2800.0, "1627.T": 1500.0,
        "1630.T": 2600.0, "1633.T": 1900.0,
    }

    out = calculate_lots(capital, long_tickers, short_tickers, prices, unit_size=10)

    # ---- structural ----
    assert set(out.keys()) == {
        "long", "short",
        "total_long_value", "total_short_value",
        "total_gross_exposure", "cash_remaining",
    }
    assert len(out["long"]) == 5 and len(out["short"]) == 5

    # ---- per-ticker invariants ----
    target_per = capital * 0.5 / 5  # 500_000 JPY/ticker
    for row in out["long"] + out["short"]:
        assert set(row.keys()) == {"ticker", "lots", "shares", "price", "value"}
        # lots * unit_size == shares
        assert row["lots"] * 10 == row["shares"], f"unit-size mismatch on {row['ticker']}"
        # shares * price == value
        assert math.isclose(row["shares"] * row["price"], row["value"], rel_tol=1e-12)
        # value <= target_per (we never overshoot per-ticker budget)
        assert row["value"] <= target_per + 1e-9, (
            f"{row['ticker']} value {row['value']} exceeds target {target_per}"
        )
        # under-spend per ticker is bounded by one lot's worth at most
        assert (target_per - row["value"]) < row["price"] * 10 + 1e-9, (
            f"{row['ticker']} under-spent by more than one lot"
        )

    # ---- aggregate invariants ----
    sum_long = sum(r["value"] for r in out["long"])
    sum_short = sum(r["value"] for r in out["short"])
    assert math.isclose(out["total_long_value"], sum_long, rel_tol=1e-12)
    assert math.isclose(out["total_short_value"], sum_short, rel_tol=1e-12)
    assert math.isclose(
        out["total_gross_exposure"], sum_long + sum_short, rel_tol=1e-12,
    )
    assert math.isclose(
        out["cash_remaining"], capital - (sum_long + sum_short), rel_tol=1e-12,
    )
    # We never over-spend
    assert out["cash_remaining"] >= 0


def test_calculate_lots_hand_calc_single_pair():
    """One long + one short ticker, hand-verifiable numbers."""
    # 1,000,000 JPY → 500k per side → with price 1234, raw_shares = floor(500_000/1234) = 405
    # lots = 405 // 10 = 40 → shares = 400 → value = 400 * 1234 = 493,600
    out = calculate_lots(
        1_000_000, ["A.T"], ["B.T"],
        {"A.T": 1234.0, "B.T": 567.0},
        unit_size=10,
    )
    long_row = out["long"][0]
    assert long_row["lots"] == 40
    assert long_row["shares"] == 400
    assert long_row["value"] == 400 * 1234.0

    # short side: 500_000 / 567 = 881.83 → raw 881 → lots 88 → shares 880
    short_row = out["short"][0]
    assert short_row["lots"] == 88
    assert short_row["shares"] == 880
    assert short_row["value"] == 880 * 567.0

    assert out["total_gross_exposure"] == 400 * 1234.0 + 880 * 567.0
    assert out["cash_remaining"] == 1_000_000 - out["total_gross_exposure"]
    assert out["cash_remaining"] >= 0


def test_calculate_lots_underfunded_returns_zero_lots():
    """If the budget can't afford a single lot, lots=0 and value=0 (no exception)."""
    # 50,000 JPY for 5 tickers → 5_000 per ticker
    # price 1,000,000 → raw_shares = 0 → lots = 0
    out = calculate_lots(
        50_000,
        ["A.T", "B.T", "C.T", "D.T", "E.T"],
        ["F.T", "G.T", "H.T", "I.T", "J.T"],
        {tk: 1_000_000.0 for tk in "ABCDEFGHIJ"} | {f"{c}.T": 1_000_000.0 for c in "ABCDEFGHIJ"},
        unit_size=10,
    )
    assert all(row["lots"] == 0 and row["shares"] == 0 and row["value"] == 0
               for row in out["long"] + out["short"])
    assert out["total_long_value"] == 0
    assert out["total_short_value"] == 0
    assert out["total_gross_exposure"] == 0
    assert out["cash_remaining"] == 50_000


def test_calculate_lots_respects_custom_unit_size():
    """Non-default unit_size (e.g. 100) is honoured."""
    out = calculate_lots(
        1_000_000, ["A.T"], ["B.T"],
        {"A.T": 500.0, "B.T": 500.0},
        unit_size=100,
    )
    # 500_000 / 500 = 1000 raw shares → lots = 1000 // 100 = 10 → shares = 1000
    assert out["long"][0]["lots"] == 10
    assert out["long"][0]["shares"] == 1000
    assert out["short"][0]["shares"] == 1000


# ---------------------------------------------------------------------------
# calculate_lots — input validation
# ---------------------------------------------------------------------------

def test_calculate_lots_rejects_non_positive_capital():
    with pytest.raises(ValueError, match="capital"):
        calculate_lots(0, ["A"], ["B"], {"A": 100.0, "B": 100.0})
    with pytest.raises(ValueError, match="capital"):
        calculate_lots(-1, ["A"], ["B"], {"A": 100.0, "B": 100.0})


def test_calculate_lots_rejects_invalid_unit_size():
    with pytest.raises(ValueError, match="unit_size"):
        calculate_lots(1_000, ["A"], ["B"], {"A": 100.0, "B": 100.0}, unit_size=0)
    with pytest.raises(ValueError, match="unit_size"):
        calculate_lots(1_000, ["A"], ["B"], {"A": 100.0, "B": 100.0}, unit_size=-10)


def test_calculate_lots_rejects_missing_price():
    with pytest.raises(ValueError, match="prices_dict"):
        calculate_lots(1_000_000, ["A.T"], ["B.T"], {"A.T": 100.0}, unit_size=10)


def test_calculate_lots_rejects_non_positive_price():
    with pytest.raises(ValueError, match="invalid price"):
        calculate_lots(1_000_000, ["A.T"], ["B.T"], {"A.T": 0.0, "B.T": 100.0})
    with pytest.raises(ValueError, match="invalid price"):
        calculate_lots(1_000_000, ["A.T"], ["B.T"], {"A.T": -10.0, "B.T": 100.0})


def test_calculate_lots_rejects_non_finite_price():
    with pytest.raises(ValueError, match="invalid price"):
        calculate_lots(1_000_000, ["A.T"], ["B.T"], {"A.T": float("nan"), "B.T": 100.0})
    with pytest.raises(ValueError, match="invalid price"):
        calculate_lots(1_000_000, ["A.T"], ["B.T"], {"A.T": float("inf"), "B.T": 100.0})


def test_calculate_lots_rejects_empty_baskets():
    with pytest.raises(ValueError, match="non-empty"):
        calculate_lots(1_000_000, [], [], {})


# ---------------------------------------------------------------------------
# fetch_latest_prices — offline validation
# ---------------------------------------------------------------------------

def test_fetch_latest_prices_rejects_empty():
    with pytest.raises(ValueError):
        fetch_latest_prices([])


def test_fetch_latest_prices_rejects_duplicates():
    with pytest.raises(ValueError, match="unique"):
        fetch_latest_prices(["1618.T", "1618.T"])


# ---------------------------------------------------------------------------
# fetch_latest_prices — live network (skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_fetch_latest_prices_xlk():
    """XLK is liquid and rarely halted; its last_price should be retrievable."""
    out = fetch_latest_prices(["XLK"])
    assert set(out.keys()) == {"XLK"}
    assert isinstance(out["XLK"], float)
    assert out["XLK"] > 0


@pytest.mark.network
def test_fetch_latest_prices_jp_etf():
    """Sanity check on the production JP ticker format."""
    out = fetch_latest_prices(["1618.T"])
    assert set(out.keys()) == {"1618.T"}
    assert out["1618.T"] > 0
