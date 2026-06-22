from __future__ import annotations

import numpy as np
import pandas as pd

from quant_a_stock.screening.patterns import scan_accumulation_setups
from quant_a_stock.screening.patterns import scan_base_breakout_setups
from quant_a_stock.screening.patterns import scan_trend_pullback_setups


def test_base_breakout_scanner_penalizes_extended_moves() -> None:
    days = 180
    quiet = np.linspace(10, 12, 150)
    vertical = np.linspace(12, 60, 30)
    close = pd.Series(np.concatenate([quiet, vertical]))
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=days, freq="B"),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": close * 1_000_000,
            "symbol": "688146",
        }
    )

    result = scan_base_breakout_setups(
        {"688146": candles},
        min_score=0,
        include_extended=True,
    )

    assert result.loc[0, "stage"] == "extended"
    assert result.loc[0, "score"] < 50


def test_base_breakout_scanner_can_filter_by_stage_and_liquidity() -> None:
    days = 180
    close = pd.Series(np.linspace(10, 12, days))
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=days, freq="B"),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": 1_000_000,
            "symbol": "000001",
        }
    )

    result = scan_base_breakout_setups(
        {"000001": candles},
        min_score=0,
        stages={"near_breakout"},
        min_amount_ma20=100_000_000,
    )

    assert result.empty


def test_accumulation_scanner_finds_long_calm_setup() -> None:
    days = 320
    base = 12 + np.sin(np.linspace(0, 12 * np.pi, days)) * 0.9
    drift = np.linspace(-0.7, 0.6, days)
    close = pd.Series(base + drift)
    close.iloc[-1] = 12.6
    volume = pd.Series(np.full(days, 1_000_000.0))
    volume.iloc[-1] = 1_350_000
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=days, freq="B"),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
            "amount": close * volume * 100,
            "symbol": "000001",
        }
    )

    result = scan_accumulation_setups(
        {"000001": candles},
        min_score=40,
        stages={"accumulation"},
        require_positive_trend_slope=True,
    )

    assert not result.empty
    assert result.loc[0, "stage"] == "accumulation"
    assert result.loc[0, "setup_phase"] in {
        "长期低位蓄势",
        "周线右侧启动",
        "日线触发观察",
        "低位潜伏观察",
    }
    assert "monthly_position_pct" in result.columns
    assert "weekly_trend_slope_pct" in result.columns
    assert "mtf_score" in result.columns
    assert result.loc[0, "price_position_pct"] < 0.82
    assert result.loc[0, "ret_20_pct"] < 0.15


def test_accumulation_scanner_filters_near_high_as_not_early() -> None:
    days = 320
    close = pd.Series(np.linspace(10, 12.5, days))
    close.iloc[-40:-1] = 12.2
    close.iloc[-1] = 12.48
    volume = pd.Series(np.full(days, 1_000_000.0))
    volume.iloc[-1] = 1_300_000
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=days, freq="B"),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
            "amount": close * volume * 100,
            "symbol": "000002",
        }
    )

    result = scan_accumulation_setups(
        {"000002": candles},
        min_score=0,
        stages={"accumulation"},
    )

    assert result.empty


def test_trend_pullback_scanner_finds_strong_trend_resume() -> None:
    calm = np.linspace(10, 12, 180)
    impulse = np.linspace(12, 22, 50)
    pullback = np.linspace(22, 18, 20)
    resume = np.linspace(18, 20, 10)
    close = pd.Series(np.concatenate([calm, impulse, pullback, resume]))
    days = len(close)
    volume = pd.Series(np.full(days, 2_000_000.0))
    volume.iloc[-1] = 2_500_000
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=days, freq="B"),
            "open": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": volume,
            "amount": close * volume * 100,
            "symbol": "300548",
        }
    )

    result = scan_trend_pullback_setups(
        {"300548": candles},
        min_score=40,
        stages={"trend_pullback", "trend_resume"},
        min_amount_ma20=100_000_000,
        min_ret_60=0.18,
        max_ret_20=0.18,
        max_close_vs_trend=0.65,
        max_drawdown_from_high=0.32,
        max_volume_ratio=3.20,
    )

    assert not result.empty
    assert result.loc[0, "stage"] in {"trend_pullback", "trend_resume"}
    assert result.loc[0, "ret_60_pct"] >= 0.18
    assert result.loc[0, "ret_20_pct"] <= 0.18
    assert result.loc[0, "drawdown_from_high_pct"] >= -0.32
