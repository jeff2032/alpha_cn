from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from quant_a_stock.backtest.engine import trade_block_reason
from quant_a_stock.screening.patterns import LatentCatalystSetupConfig
from quant_a_stock.screening.patterns import build_latent_catalyst_feature_frame


OBSERVATION_POOL_VERSION = "observation_pool_v2026_08_02_next_open"
OUTCOME_HORIZONS = (1, 3, 5, 10)


@dataclass(frozen=True)
class ObservationPoolReview:
    details: pd.DataFrame
    summary: pd.DataFrame


def evaluate_latent_catalyst_history(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    since: str,
    until: str,
    names: dict[str, str] | None = None,
    benchmark: pd.DataFrame | None = None,
    benchmark_symbol: str = "510300",
    config: LatentCatalystSetupConfig = LatentCatalystSetupConfig(),
    min_score: float = 45.0,
    min_amount_ma20: float | None = None,
) -> ObservationPoolReview:
    rows: list[dict] = []
    name_map = names or {}
    start = pd.Timestamp(since).normalize()
    end = pd.Timestamp(until).normalize()
    amount_floor = min_amount_ma20 if min_amount_ma20 is not None else config.min_amount_ma20

    for symbol, candles in candles_by_symbol.items():
        features = build_latent_catalyst_feature_frame(candles, config=config)
        if features.empty:
            continue
        candidate_mask = (
            features["ret_5_pct"].between(config.min_ret_5, config.max_ret_5)
            & features["ret_20_pct"].between(config.min_ret_20, config.max_ret_20)
            & features["ret_60_pct"].le(config.max_ret_60)
            & features["price_position_pct"].le(config.max_price_position)
            & features["volume_ratio"].between(config.min_volume_ratio, config.max_volume_ratio)
            & features["amount_ma20"].ge(amount_floor)
            & features["score"].ge(min_score)
        )
        entry_mask = candidate_mask & ~candidate_mask.shift(1, fill_value=False)
        entry_mask &= features["timestamp"].between(start, end)
        eligible_indexes: list[int] = []
        last_entry_index = -10_000
        for index in features.index[entry_mask]:
            if int(index) - last_entry_index < 10:
                continue
            eligible_indexes.append(int(index))
            last_entry_index = int(index)
        for episode, index in enumerate(eligible_indexes, start=1):
            rows.append(
                _outcome_row(
                    features,
                    index=index,
                    symbol=str(symbol).zfill(6),
                    name=name_map.get(str(symbol).zfill(6), ""),
                    episode=episode,
                )
            )

    details = pd.DataFrame(rows)
    if details.empty:
        return ObservationPoolReview(details=details, summary=pd.DataFrame())
    details = details.sort_values(["signal_date", "score"], ascending=[True, False]).reset_index(drop=True)
    details["benchmark_symbol"] = benchmark_symbol
    details = _attach_benchmark_outcomes(details, benchmark)
    details["score_bucket"] = pd.cut(
        details["score"],
        bins=[-math.inf, 50, 60, 70, math.inf],
        labels=["45-50", "50-60", "60-70", "70+"],
        right=False,
    ).astype(str)
    summary = _summarize(details)
    return ObservationPoolReview(details=details, summary=summary)


def _outcome_row(frame: pd.DataFrame, *, index: int, symbol: str, name: str, episode: int) -> dict:
    signal = frame.loc[index]
    row = {
        "signal_date": str(pd.Timestamp(signal["timestamp"]).date()),
        "symbol": symbol,
        "name": name,
        "episode_id": f"{symbol}_{pd.Timestamp(signal['timestamp']).strftime('%Y%m%d')}_{episode}",
        "catalyst_state": signal["catalyst_state"],
        "score": round(float(signal["score"]), 2),
        "price_position_pct": round(float(signal["price_position_pct"]), 6),
        "ret_5_pct": round(float(signal["ret_5_pct"]), 6),
        "ret_20_pct": round(float(signal["ret_20_pct"]), 6),
        "ret_60_pct": round(float(signal["ret_60_pct"]), 6),
        "volume_ratio": round(float(signal["volume_ratio"]), 6),
        "amount_ma20": round(float(signal["amount_ma20"]), 2),
        "entry_date": "",
        "entry_open": math.nan,
        "blocked_reason": "缺少次日行情",
        "executable": False,
        "observation_pool_version": OBSERVATION_POOL_VERSION,
    }
    for horizon in OUTCOME_HORIZONS:
        row[f"ret_{horizon}d_from_open"] = math.nan
        row[f"max_{horizon}d_from_open"] = math.nan
        row[f"min_{horizon}d_from_open"] = math.nan

    entry_index = index + 1
    if entry_index >= len(frame):
        return row
    entry = frame.iloc[entry_index]
    entry_open = float(entry.get("open", 0) or 0)
    blocked = trade_block_reason(frame, entry_index, side="buy")
    row["entry_date"] = str(pd.Timestamp(entry["timestamp"]).date())
    row["entry_open"] = round(entry_open, 4) if entry_open > 0 else math.nan
    row["blocked_reason"] = blocked
    row["executable"] = not blocked and entry_open > 0
    if not row["executable"]:
        return row

    for horizon in OUTCOME_HORIZONS:
        target_index = entry_index + horizon - 1
        if target_index >= len(frame):
            continue
        window = frame.iloc[entry_index : target_index + 1]
        target_close = float(frame.iloc[target_index].get("close", 0) or 0)
        high = float(pd.to_numeric(window["high"], errors="coerce").max())
        low = float(pd.to_numeric(window["low"], errors="coerce").min())
        row[f"ret_{horizon}d_from_open"] = round(target_close / entry_open - 1, 6)
        row[f"max_{horizon}d_from_open"] = round(high / entry_open - 1, 6)
        row[f"min_{horizon}d_from_open"] = round(low / entry_open - 1, 6)
    return row


def _summarize(details: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (state, score_bucket), group in details.groupby(["catalyst_state", "score_bucket"], dropna=False):
        executable = group[group["executable"]].copy()
        record = {
            "catalyst_state": state,
            "score_bucket": score_bucket,
            "signals": int(len(group)),
            "executable_count": int(len(executable)),
            "executable_pct": round(float(len(executable) / len(group)), 4),
        }
        for horizon in OUTCOME_HORIZONS:
            column = f"ret_{horizon}d_from_open"
            values = pd.to_numeric(executable[column], errors="coerce").dropna()
            record[f"avg_ret_{horizon}d"] = round(float(values.mean()), 6) if not values.empty else math.nan
            record[f"win_rate_{horizon}d"] = round(float(values.gt(0).mean()), 4) if not values.empty else math.nan
            excess = pd.to_numeric(executable[f"excess_ret_{horizon}d"], errors="coerce").dropna()
            record[f"avg_excess_{horizon}d"] = round(float(excess.mean()), 6) if not excess.empty else math.nan
            record[f"excess_win_rate_{horizon}d"] = round(float(excess.gt(0).mean()), 4) if not excess.empty else math.nan
        record["eligible_for_promotion"] = bool(
            record["executable_count"] >= 40
            and record.get("avg_excess_5d", math.nan) > 0
            and record.get("excess_win_rate_5d", 0.0) >= 0.50
            and record.get("avg_excess_10d", math.nan) > 0
        )
        record["promotion_status"] = "可进入下一轮窄化验证" if record["eligible_for_promotion"] else "不具备升级证据"
        rows.append(record)
    return pd.DataFrame(rows).sort_values(["catalyst_state", "score_bucket"]).reset_index(drop=True)


def _attach_benchmark_outcomes(details: pd.DataFrame, benchmark: pd.DataFrame | None) -> pd.DataFrame:
    output = details.copy()
    for horizon in OUTCOME_HORIZONS:
        output[f"benchmark_ret_{horizon}d"] = math.nan
        output[f"excess_ret_{horizon}d"] = math.nan
    if benchmark is None or benchmark.empty:
        return output
    frame = benchmark.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"]).dt.normalize()
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    date_to_index = {date: index for index, date in enumerate(frame["timestamp"])}
    for row_index, row in output.iterrows():
        if not bool(row.get("executable", False)) or not row.get("entry_date"):
            continue
        entry_date = pd.Timestamp(row["entry_date"]).normalize()
        benchmark_entry_index = date_to_index.get(entry_date)
        if benchmark_entry_index is None:
            continue
        entry_open = float(frame.iloc[benchmark_entry_index].get("open", 0) or 0)
        if entry_open <= 0:
            continue
        for horizon in OUTCOME_HORIZONS:
            target_index = benchmark_entry_index + horizon - 1
            if target_index >= len(frame):
                continue
            target_close = float(frame.iloc[target_index].get("close", 0) or 0)
            benchmark_ret = target_close / entry_open - 1
            stock_ret = row.get(f"ret_{horizon}d_from_open")
            output.at[row_index, f"benchmark_ret_{horizon}d"] = round(benchmark_ret, 6)
            if stock_ret is not None and not pd.isna(stock_ret):
                output.at[row_index, f"excess_ret_{horizon}d"] = round(float(stock_ret) - benchmark_ret, 6)
    return output
