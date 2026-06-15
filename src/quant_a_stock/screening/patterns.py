from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BaseBreakoutSetupConfig:
    base_window: int = 120
    trend_window: int = 120
    volume_window: int = 20
    max_base_range: float = 0.65
    proximity_pct: float = 0.05
    volume_ratio_min: float = 1.3
    max_ret_20: float = 0.35


@dataclass(frozen=True)
class AccumulationSetupConfig:
    base_window: int = 250
    trend_window: int = 120
    volume_window: int = 20
    max_base_range: float = 0.45
    min_price_position: float = 0.30
    max_price_position: float = 0.82
    min_distance_to_high: float = -0.35
    max_distance_to_high: float = -0.04
    min_close_vs_trend: float = -0.05
    max_close_vs_trend: float = 0.12
    max_close_vs_cost: float = 0.18
    min_volume_ratio: float = 1.05
    max_volume_ratio: float = 2.20
    max_ret_20: float = 0.15
    max_ret_60: float = 0.30
    monthly_window: int = 36
    weekly_window: int = 20


def _clip_score(value: float, low: float = 0.0, high: float = 100.0) -> float:
    if np.isnan(value):
        return 0.0
    return float(min(max(value, low), high))


def _proximity_score(distance_to_high: float, proximity_pct: float) -> float:
    if np.isnan(distance_to_high):
        return 0.0
    if distance_to_high <= 0:
        return _clip_score((distance_to_high + proximity_pct) / proximity_pct * 20, high=20)
    return _clip_score(20 - distance_to_high / 0.20 * 20, high=20)


def score_base_breakout_setup(
    candles: pd.DataFrame,
    *,
    symbol: str,
    config: BaseBreakoutSetupConfig = BaseBreakoutSetupConfig(),
) -> dict[str, float | str] | None:
    frame = candles.copy()
    if frame.empty:
        return None

    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    required_bars = max(
        config.base_window,
        config.trend_window,
        config.volume_window,
        60,
    ) + 21
    if len(frame) < required_bars:
        return None

    close = frame["close"]
    volume = frame["volume"]
    amount = frame["amount"] if "amount" in frame.columns else close * volume

    prior_high = close.shift(1).rolling(config.base_window, min_periods=config.base_window).max()
    prior_low = close.shift(1).rolling(config.base_window, min_periods=config.base_window).min()
    base_range = prior_high / prior_low - 1
    trend_ma = close.rolling(config.trend_window, min_periods=config.trend_window).mean()
    trend_slope_20 = trend_ma / trend_ma.shift(20) - 1
    volume_ratio = volume / volume.rolling(config.volume_window, min_periods=config.volume_window).mean()
    amount_ma20 = amount.rolling(config.volume_window, min_periods=config.volume_window).mean()
    ret_20 = close / close.shift(20) - 1
    ret_60 = close / close.shift(60) - 1
    distance_to_high = close / prior_high - 1
    close_vs_trend = close / trend_ma - 1

    idx = frame.index[-1]
    latest = frame.loc[idx]

    base_score = _clip_score(
        (config.max_base_range - base_range.loc[idx]) / 0.45 * 25,
        high=25,
    )
    proximity_score = _proximity_score(distance_to_high.loc[idx], config.proximity_pct)
    trend_score = _clip_score((close_vs_trend.loc[idx] + 0.02) / 0.16 * 20, high=20)
    slope_score = _clip_score((trend_slope_20.loc[idx] + 0.01) / 0.08 * 15, high=15)
    volume_score = _clip_score((volume_ratio.loc[idx] - 1.0) / 2.0 * 20, high=20)
    overheat_penalty = (
        _clip_score((ret_20.loc[idx] - config.max_ret_20) / 0.25 * 60, high=60)
        + _clip_score((close_vs_trend.loc[idx] - 0.50) / 1.0 * 30, high=30)
        + _clip_score((base_range.loc[idx] - config.max_base_range) / 1.0 * 20, high=20)
    )

    score = base_score + proximity_score + trend_score + slope_score + volume_score - overheat_penalty
    score = _clip_score(score)

    stage = "watch"
    if close.loc[idx] > prior_high.loc[idx]:
        stage = "breakout"
    elif distance_to_high.loc[idx] >= -config.proximity_pct:
        stage = "near_breakout"
    if ret_20.loc[idx] > config.max_ret_20:
        stage = "extended"

    return {
        "symbol": symbol,
        "timestamp": str(pd.Timestamp(latest["timestamp"]).date()),
        "stage": stage,
        "score": round(score, 2),
        "close": round(float(close.loc[idx]), 4),
        "base_range_pct": round(float(base_range.loc[idx]), 4),
        "distance_to_high_pct": round(float(distance_to_high.loc[idx]), 4),
        "close_vs_trend_pct": round(float(close_vs_trend.loc[idx]), 4),
        "trend_slope_20_pct": round(float(trend_slope_20.loc[idx]), 4),
        "volume_ratio": round(float(volume_ratio.loc[idx]), 4),
        "amount_ma20": round(float(amount_ma20.loc[idx]), 2),
        "ret_20_pct": round(float(ret_20.loc[idx]), 4),
        "ret_60_pct": round(float(ret_60.loc[idx]), 4),
    }


def scan_base_breakout_setups(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    config: BaseBreakoutSetupConfig = BaseBreakoutSetupConfig(),
    min_score: float = 50.0,
    include_extended: bool = False,
    stages: set[str] | None = None,
    min_amount_ma20: float | None = None,
    min_volume_ratio: float | None = None,
    max_close_vs_trend: float | None = None,
    max_ret_20: float | None = None,
    require_positive_trend_slope: bool = False,
) -> pd.DataFrame:
    rows = []
    for symbol, candles in candles_by_symbol.items():
        row = score_base_breakout_setup(candles, symbol=symbol, config=config)
        if row is None:
            continue
        if not include_extended and row["stage"] == "extended":
            continue
        if stages is not None and str(row["stage"]) not in stages:
            continue
        if min_amount_ma20 is not None and float(row["amount_ma20"]) < min_amount_ma20:
            continue
        if min_volume_ratio is not None and float(row["volume_ratio"]) < min_volume_ratio:
            continue
        if max_close_vs_trend is not None and float(row["close_vs_trend_pct"]) > max_close_vs_trend:
            continue
        if max_ret_20 is not None and float(row["ret_20_pct"]) > max_ret_20:
            continue
        if require_positive_trend_slope and float(row["trend_slope_20_pct"]) <= 0:
            continue
        if float(row["score"]) >= min_score:
            rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["score", "volume_ratio"], ascending=[False, False]).reset_index(
        drop=True
    )


def score_accumulation_setup(
    candles: pd.DataFrame,
    *,
    symbol: str,
    config: AccumulationSetupConfig = AccumulationSetupConfig(),
) -> dict[str, float | str] | None:
    frame = candles.copy()
    if frame.empty:
        return None

    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    required_bars = max(
        config.base_window,
        config.trend_window,
        config.volume_window,
        60,
    ) + 21
    if len(frame) < required_bars:
        return None

    close = frame["close"]
    volume = frame["volume"]
    amount = frame["amount"] if "amount" in frame.columns else close * volume

    prior_high = close.shift(1).rolling(config.base_window, min_periods=config.base_window).max()
    prior_low = close.shift(1).rolling(config.base_window, min_periods=config.base_window).min()
    base_range = prior_high / prior_low - 1
    price_position = (close - prior_low) / (prior_high - prior_low)
    cost_price = amount.shift(1).rolling(config.base_window).sum() / volume.shift(1).rolling(
        config.base_window
    ).sum()
    trend_ma = close.rolling(config.trend_window, min_periods=config.trend_window).mean()
    trend_slope_20 = trend_ma / trend_ma.shift(20) - 1
    volume_ma = volume.rolling(config.volume_window, min_periods=config.volume_window).mean()
    volume_ratio = volume / volume_ma
    amount_ma20 = amount.rolling(config.volume_window, min_periods=config.volume_window).mean()
    ret_20 = close / close.shift(20) - 1
    ret_60 = close / close.shift(60) - 1
    distance_to_high = close / prior_high - 1
    close_vs_trend = close / trend_ma - 1
    close_vs_cost = close / cost_price - 1
    mtf = _multi_timeframe_metrics(frame, config=config)

    idx = frame.index[-1]
    latest = frame.loc[idx]
    metrics = {
        "base_range": float(base_range.loc[idx]),
        "price_position": float(price_position.loc[idx]),
        "distance_to_high": float(distance_to_high.loc[idx]),
        "close_vs_trend": float(close_vs_trend.loc[idx]),
        "close_vs_cost": float(close_vs_cost.loc[idx]),
        "trend_slope_20": float(trend_slope_20.loc[idx]),
        "volume_ratio": float(volume_ratio.loc[idx]),
        "ret_20": float(ret_20.loc[idx]),
        "ret_60": float(ret_60.loc[idx]),
    }
    if any(np.isnan(value) for value in metrics.values()):
        return None

    base_score = _clip_score((config.max_base_range - metrics["base_range"]) / 0.25 * 18, high=18)
    position_score = _band_score(
        metrics["price_position"],
        low=config.min_price_position,
        high=config.max_price_position,
        target=0.62,
        points=18,
    )
    distance_score = _band_score(
        metrics["distance_to_high"],
        low=config.min_distance_to_high,
        high=config.max_distance_to_high,
        target=-0.12,
        points=14,
    )
    trend_score = _band_score(
        metrics["close_vs_trend"],
        low=config.min_close_vs_trend,
        high=config.max_close_vs_trend,
        target=0.04,
        points=14,
    )
    cost_score = _band_score(
        metrics["close_vs_cost"],
        low=-0.08,
        high=config.max_close_vs_cost,
        target=0.06,
        points=12,
    )
    slope_score = _clip_score((metrics["trend_slope_20"] + 0.015) / 0.06 * 10, high=10)
    volume_score = _band_score(
        metrics["volume_ratio"],
        low=config.min_volume_ratio,
        high=config.max_volume_ratio,
        target=1.35,
        points=14,
    )
    calm_score = (
        _clip_score((config.max_ret_20 - metrics["ret_20"]) / 0.18 * 5, high=5)
        + _clip_score((config.max_ret_60 - metrics["ret_60"]) / 0.35 * 5, high=5)
    )

    overheat_penalty = (
        _clip_score((metrics["ret_20"] - config.max_ret_20) / 0.15 * 25, high=25)
        + _clip_score((metrics["ret_60"] - config.max_ret_60) / 0.25 * 20, high=20)
        + _clip_score((metrics["close_vs_trend"] - config.max_close_vs_trend) / 0.20 * 20, high=20)
        + _clip_score((metrics["close_vs_cost"] - config.max_close_vs_cost) / 0.25 * 20, high=20)
        + _clip_score((metrics["price_position"] - config.max_price_position) / 0.18 * 20, high=20)
        + _clip_score((metrics["volume_ratio"] - config.max_volume_ratio) / 2.0 * 12, high=12)
        + _clip_score((metrics["base_range"] - config.max_base_range) / 0.35 * 18, high=18)
    )
    daily_score = _clip_score(
        base_score
        + position_score
        + distance_score
        + trend_score
        + cost_score
        + slope_score
        + volume_score
        + calm_score
        - overheat_penalty
    )
    monthly_score = _monthly_setup_score(mtf)
    weekly_score = _weekly_setup_score(mtf)
    mtf_score = _clip_score(daily_score * 0.45 + weekly_score * 0.30 + monthly_score * 0.25)

    stage = "accumulation"
    if (
        metrics["distance_to_high"] > config.max_distance_to_high
        or metrics["price_position"] > config.max_price_position
    ):
        stage = "pre_breakout"
    if (
        metrics["ret_20"] > config.max_ret_20
        or metrics["ret_60"] > config.max_ret_60
        or metrics["close_vs_trend"] > config.max_close_vs_trend
        or metrics["close_vs_cost"] > config.max_close_vs_cost
        or metrics["volume_ratio"] > config.max_volume_ratio
        or metrics["base_range"] > config.max_base_range
    ):
        stage = "overheated"
    setup_phase = _setup_phase(
        stage=stage,
        daily=metrics,
        mtf=mtf,
    )

    return {
        "symbol": symbol,
        "timestamp": str(pd.Timestamp(latest["timestamp"]).date()),
        "stage": stage,
        "setup_phase": setup_phase,
        "score": round(mtf_score, 2),
        "mtf_score": round(mtf_score, 2),
        "daily_score": round(daily_score, 2),
        "weekly_score": round(weekly_score, 2),
        "monthly_score": round(monthly_score, 2),
        "close": round(float(close.loc[idx]), 4),
        "base_range_pct": round(metrics["base_range"], 4),
        "price_position_pct": round(metrics["price_position"], 4),
        "monthly_position_pct": round(mtf["monthly_position"], 4),
        "monthly_range_pct": round(mtf["monthly_range"], 4),
        "monthly_ma_slope_pct": round(mtf["monthly_ma_slope"], 4),
        "weekly_position_pct": round(mtf["weekly_position"], 4),
        "weekly_range_pct": round(mtf["weekly_range"], 4),
        "weekly_trend_slope_pct": round(mtf["weekly_trend_slope"], 4),
        "weekly_volume_ratio": round(mtf["weekly_volume_ratio"], 4),
        "distance_to_high_pct": round(metrics["distance_to_high"], 4),
        "close_vs_trend_pct": round(metrics["close_vs_trend"], 4),
        "close_vs_cost_pct": round(metrics["close_vs_cost"], 4),
        "trend_slope_20_pct": round(metrics["trend_slope_20"], 4),
        "volume_ratio": round(metrics["volume_ratio"], 4),
        "amount_ma20": round(float(amount_ma20.loc[idx]), 2),
        "ret_20_pct": round(metrics["ret_20"], 4),
        "ret_60_pct": round(metrics["ret_60"], 4),
    }


def scan_accumulation_setups(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    config: AccumulationSetupConfig = AccumulationSetupConfig(),
    min_score: float = 50.0,
    stages: set[str] | None = None,
    min_amount_ma20: float | None = None,
    min_volume_ratio: float | None = None,
    max_volume_ratio: float | None = None,
    max_close_vs_trend: float | None = None,
    max_close_vs_cost: float | None = None,
    max_ret_20: float | None = None,
    max_ret_60: float | None = None,
    max_price_position: float | None = None,
    require_positive_trend_slope: bool = False,
) -> pd.DataFrame:
    rows = []
    for symbol, candles in candles_by_symbol.items():
        row = score_accumulation_setup(candles, symbol=symbol, config=config)
        if row is None:
            continue
        if stages is not None and str(row["stage"]) not in stages:
            continue
        if min_amount_ma20 is not None and float(row["amount_ma20"]) < min_amount_ma20:
            continue
        if min_volume_ratio is not None and float(row["volume_ratio"]) < min_volume_ratio:
            continue
        if max_volume_ratio is not None and float(row["volume_ratio"]) > max_volume_ratio:
            continue
        if max_close_vs_trend is not None and float(row["close_vs_trend_pct"]) > max_close_vs_trend:
            continue
        if max_close_vs_cost is not None and float(row["close_vs_cost_pct"]) > max_close_vs_cost:
            continue
        if max_ret_20 is not None and float(row["ret_20_pct"]) > max_ret_20:
            continue
        if max_ret_60 is not None and float(row["ret_60_pct"]) > max_ret_60:
            continue
        if max_price_position is not None and float(row["price_position_pct"]) > max_price_position:
            continue
        if require_positive_trend_slope and float(row["trend_slope_20_pct"]) <= 0:
            continue
        if float(row["score"]) >= min_score:
            rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["score", "volume_ratio"], ascending=[False, False]).reset_index(
        drop=True
    )


def _band_score(value: float, *, low: float, high: float, target: float, points: float) -> float:
    if np.isnan(value) or value < low or value > high:
        return 0.0
    span = max(target - low, high - target)
    if span <= 0:
        return points
    return _clip_score(points * (1 - abs(value - target) / span), high=points)


def _multi_timeframe_metrics(
    frame: pd.DataFrame,
    *,
    config: AccumulationSetupConfig,
) -> dict[str, float]:
    weekly = _resample_ohlcv(frame, "W-FRI")
    try:
        monthly = _resample_ohlcv(frame, "ME")
    except ValueError:
        monthly = _resample_ohlcv(frame, "M")

    monthly_tail = monthly.tail(config.monthly_window)
    if len(monthly_tail) < 8:
        monthly_position = np.nan
        monthly_range = np.nan
        monthly_ma_slope = np.nan
    else:
        monthly_high = float(monthly_tail["high"].max())
        monthly_low = float(monthly_tail["low"].min())
        monthly_close = float(monthly_tail["close"].iloc[-1])
        monthly_position = _range_position(monthly_close, monthly_low, monthly_high)
        monthly_range = monthly_high / monthly_low - 1 if monthly_low > 0 else np.nan
        monthly_ma = monthly["close"].rolling(12, min_periods=min(6, len(monthly))).mean()
        monthly_ma_slope = _series_slope(monthly_ma, periods=3)

    weekly_tail = weekly.tail(config.weekly_window)
    if len(weekly_tail) < 10:
        weekly_position = np.nan
        weekly_range = np.nan
        weekly_trend_slope = np.nan
        weekly_volume_ratio = np.nan
    else:
        weekly_high = float(weekly_tail["high"].max())
        weekly_low = float(weekly_tail["low"].min())
        weekly_close = float(weekly_tail["close"].iloc[-1])
        weekly_position = _range_position(weekly_close, weekly_low, weekly_high)
        weekly_range = weekly_high / weekly_low - 1 if weekly_low > 0 else np.nan
        weekly_ma = weekly["close"].rolling(config.weekly_window, min_periods=10).mean()
        weekly_trend_slope = _series_slope(weekly_ma, periods=4)
        weekly_volume_ma = weekly["volume"].rolling(config.weekly_window, min_periods=10).mean()
        weekly_volume_ratio = float(weekly["volume"].iloc[-1] / weekly_volume_ma.iloc[-1])

    return {
        "monthly_position": monthly_position,
        "monthly_range": monthly_range,
        "monthly_ma_slope": monthly_ma_slope,
        "weekly_position": weekly_position,
        "weekly_range": weekly_range,
        "weekly_trend_slope": weekly_trend_slope,
        "weekly_volume_ratio": weekly_volume_ratio,
    }


def _resample_ohlcv(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    data = frame.copy()
    data = data.set_index("timestamp").sort_index()
    amount = data["amount"] if "amount" in data.columns else data["close"] * data["volume"]
    output = pd.DataFrame(
        {
            "open": data["open"].resample(rule).first(),
            "high": data["high"].resample(rule).max(),
            "low": data["low"].resample(rule).min(),
            "close": data["close"].resample(rule).last(),
            "volume": data["volume"].resample(rule).sum(),
            "amount": amount.resample(rule).sum(),
        }
    )
    return output.dropna(subset=["open", "high", "low", "close"])


def _range_position(value: float, low: float, high: float) -> float:
    if high <= low:
        return np.nan
    return (value - low) / (high - low)


def _series_slope(series: pd.Series, *, periods: int) -> float:
    clean = series.dropna()
    if len(clean) <= periods:
        return 0.0
    previous = float(clean.iloc[-periods - 1])
    current = float(clean.iloc[-1])
    if previous == 0:
        return 0.0
    return current / previous - 1


def _monthly_setup_score(mtf: dict[str, float]) -> float:
    if np.isnan(mtf["monthly_position"]) or np.isnan(mtf["monthly_range"]):
        return 50.0
    position_score = _band_score(
        mtf["monthly_position"],
        low=0.12,
        high=0.72,
        target=0.42,
        points=45,
    )
    range_score = _clip_score((1.20 - mtf["monthly_range"]) / 1.20 * 25, high=25)
    slope_score = _clip_score((mtf["monthly_ma_slope"] + 0.04) / 0.10 * 30, high=30)
    return _clip_score(position_score + range_score + slope_score)


def _weekly_setup_score(mtf: dict[str, float]) -> float:
    if np.isnan(mtf["weekly_position"]) or np.isnan(mtf["weekly_range"]):
        return 50.0
    position_score = _band_score(
        mtf["weekly_position"],
        low=0.30,
        high=0.88,
        target=0.62,
        points=35,
    )
    range_score = _clip_score((0.42 - mtf["weekly_range"]) / 0.42 * 25, high=25)
    slope_score = _clip_score((mtf["weekly_trend_slope"] + 0.03) / 0.10 * 25, high=25)
    volume_score = _band_score(
        mtf["weekly_volume_ratio"],
        low=0.80,
        high=2.20,
        target=1.25,
        points=15,
    )
    return _clip_score(position_score + range_score + slope_score + volume_score)


def _setup_phase(*, stage: str, daily: dict[str, float], mtf: dict[str, float]) -> str:
    if stage == "overheated":
        return "已过热"
    if stage == "pre_breakout":
        return "接近突破确认"
    if mtf["monthly_position"] <= 0.45 and mtf["weekly_trend_slope"] <= 0.02:
        return "长期低位蓄势"
    if mtf["weekly_trend_slope"] > 0.02 and daily["volume_ratio"] >= 1.10:
        return "周线右侧启动"
    if daily["close_vs_trend"] > 0 and daily["volume_ratio"] >= 1.15:
        return "日线触发观察"
    return "低位潜伏观察"
