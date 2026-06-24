from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import math
import re

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.cache import load_daily_cache
from quant_a_stock.data.universe import load_universe_file
from quant_a_stock.research.snapshot import SNAPSHOT_ROOT


TRACKED_ACTION_BUCKETS = ("主攻-A2启动确认", "主攻-A3趋势延续", "补票-B2强主题")
TRACKED_TIERS = ("A2", "A3", "B2")
FORWARD_HORIZONS = (1, 3, 5, 10, 15)
DEFAULT_GAP_TRADE_DAYS = 3
DEFAULT_STRATEGY_VERSION = "research_candidates_v1"

ACTION_STAGE_RANK = {
    "补票-B2强主题": 1,
    "主攻-A2启动确认": 2,
    "主攻-A3趋势延续": 3,
}
TIER_STAGE_RANK = {
    "B2": 1,
    "A2": 2,
    "A3": 3,
}


@dataclass(frozen=True)
class CandidateLifecycleTracking:
    target_date: str
    snapshot_dates: list[str]
    lifecycles: pd.DataFrame
    daily: pd.DataFrame
    summary: pd.DataFrame


def build_candidate_lifecycle_tracking(
    *,
    since: str | None = None,
    until: str | None = None,
    snapshot_root: Path = SNAPSHOT_ROOT,
    cache_dir: Path | None = None,
    universe_file: Path | None = None,
    strategy_version: str = DEFAULT_STRATEGY_VERSION,
    gap_trade_days: int = DEFAULT_GAP_TRADE_DAYS,
) -> CandidateLifecycleTracking:
    """Build persistent lifecycle facts for A2/A3/B2 research candidates."""

    snapshot_dates = _snapshot_dates(snapshot_root, until=until)
    if not snapshot_dates:
        return CandidateLifecycleTracking(
            target_date=until or "",
            snapshot_dates=[],
            lifecycles=pd.DataFrame(),
            daily=pd.DataFrame(),
            summary=pd.DataFrame(),
        )

    target_date = snapshot_dates[-1]
    trade_dates = _trading_dates_from_cache(cache_dir or DEFAULT_PATHS.data_cache)
    name_map = _load_name_map(universe_file)
    events_by_symbol = _load_candidate_events(
        snapshot_root=snapshot_root,
        snapshot_dates=snapshot_dates,
        name_map=name_map,
    )
    lifecycles = _build_lifecycle_rows(
        events_by_symbol=events_by_symbol,
        snapshot_dates=snapshot_dates,
        trade_dates=trade_dates,
        cache_dir=cache_dir or DEFAULT_PATHS.data_cache,
        strategy_version=strategy_version,
        gap_trade_days=gap_trade_days,
        target_date=target_date,
    )
    daily = _build_lifecycle_daily_rows(
        lifecycles=lifecycles,
        events_by_symbol=events_by_symbol,
        snapshot_dates=snapshot_dates,
        trade_dates=trade_dates,
        cache_dir=cache_dir or DEFAULT_PATHS.data_cache,
        since=since,
        target_date=target_date,
        gap_trade_days=gap_trade_days,
    )

    if since:
        lifecycles = lifecycles[
            (lifecycles["last_evaluated_date"] >= since) & (lifecycles["first_entry_date"] <= target_date)
        ].reset_index(drop=True)
        if not daily.empty:
            daily = daily[daily["target_date"] >= since].reset_index(drop=True)

    summary = _summarize_lifecycles(lifecycles)
    return CandidateLifecycleTracking(
        target_date=target_date,
        snapshot_dates=[date for date in snapshot_dates if not since or date >= since],
        lifecycles=lifecycles,
        daily=daily,
        summary=summary,
    )


def save_candidate_lifecycle_reports(
    tracking: CandidateLifecycleTracking,
    *,
    reports_dir: Path | None = None,
    top: int = 50,
) -> tuple[Path, Path, Path]:
    root = reports_dir or DEFAULT_PATHS.reports
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    lifecycle_path = root / f"candidate_lifecycles_{stamp}.csv"
    daily_path = root / f"candidate_lifecycle_daily_{stamp}.csv"
    md_path = root / f"candidate_lifecycle_tracking_{stamp}.md"

    tracking.lifecycles.to_csv(lifecycle_path, index=False)
    tracking.daily.to_csv(daily_path, index=False)
    md_path.write_text(_render_lifecycle_markdown(tracking, top=top), encoding="utf-8")
    return lifecycle_path, daily_path, md_path


def _load_candidate_events(
    *,
    snapshot_root: Path,
    snapshot_dates: list[str],
    name_map: dict[str, str],
) -> dict[str, list[dict]]:
    events_by_symbol: dict[str, list[dict]] = {}
    for target_date in snapshot_dates:
        path = snapshot_root / target_date / "research_candidates.csv"
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype={"symbol": str})
        except Exception:
            continue
        if frame.empty or "symbol" not in frame.columns:
            continue
        frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
        for _, row in frame.iterrows():
            if not _is_tracked_candidate(row):
                continue
            event = _event_from_row(row, target_date=target_date, name_map=name_map)
            events_by_symbol.setdefault(event["symbol"], []).append(event)
    for events in events_by_symbol.values():
        events.sort(key=lambda item: item["target_date"])
    return events_by_symbol


def _build_lifecycle_rows(
    *,
    events_by_symbol: dict[str, list[dict]],
    snapshot_dates: list[str],
    trade_dates: list[str],
    cache_dir: Path,
    strategy_version: str,
    gap_trade_days: int,
    target_date: str,
) -> pd.DataFrame:
    rows: list[dict] = []
    daily_frames: dict[str, pd.DataFrame] = {}
    for symbol, events in sorted(events_by_symbol.items()):
        active_events: list[dict] = []
        sequence = 1
        last_event: dict | None = None
        for event in events:
            if last_event is None or _trade_gap(last_event["target_date"], event["target_date"], trade_dates) > gap_trade_days:
                if active_events:
                    rows.append(
                        _lifecycle_row(
                            symbol=symbol,
                            events=active_events,
                            sequence=sequence,
                            target_date=target_date,
                            trade_dates=trade_dates,
                            cache_dir=cache_dir,
                            daily_frames=daily_frames,
                            strategy_version=strategy_version,
                            gap_trade_days=gap_trade_days,
                        )
                    )
                    sequence += 1
                active_events = [event]
            else:
                active_events.append(event)
            last_event = event
        if active_events:
            rows.append(
                _lifecycle_row(
                    symbol=symbol,
                    events=active_events,
                    sequence=sequence,
                    target_date=target_date,
                    trade_dates=trade_dates,
                    cache_dir=cache_dir,
                    daily_frames=daily_frames,
                    strategy_version=strategy_version,
                    gap_trade_days=gap_trade_days,
                )
            )

    if not rows:
        return pd.DataFrame(columns=_lifecycle_columns())
    output = pd.DataFrame(rows)
    return output.sort_values(["first_entry_date", "symbol", "lifecycle_sequence"]).reset_index(drop=True)


def _build_lifecycle_daily_rows(
    *,
    lifecycles: pd.DataFrame,
    events_by_symbol: dict[str, list[dict]],
    snapshot_dates: list[str],
    trade_dates: list[str],
    cache_dir: Path,
    since: str | None,
    target_date: str,
    gap_trade_days: int,
) -> pd.DataFrame:
    if lifecycles.empty:
        return pd.DataFrame(columns=_daily_columns())

    rows: list[dict] = []
    daily_frames: dict[str, pd.DataFrame] = {}
    events_index: dict[tuple[str, str], dict] = {}
    for symbol, events in events_by_symbol.items():
        for event in events:
            events_index[(symbol, event["target_date"])] = event

    for _, lifecycle in lifecycles.iterrows():
        symbol = str(lifecycle["symbol"]).zfill(6)
        first = str(lifecycle["first_entry_date"])
        last_seen = str(lifecycle["last_seen_date"])
        lifecycle_dates = [
            date
            for date in snapshot_dates
            if first <= date <= target_date and (not since or date >= since)
        ]
        previous_observed: dict | None = None
        for date in lifecycle_dates:
            event = events_index.get((symbol, date))
            observed = event is not None and first <= date <= last_seen
            if observed:
                day_status = _event_day_status(event, previous_observed, first_entry=first)
                previous_observed = event
            else:
                gap = _trade_gap(last_seen, date, trade_dates)
                day_status = "removed" if date > last_seen and gap > gap_trade_days else "grace"
            rows.append(
                {
                    "lifecycle_id": lifecycle["lifecycle_id"],
                    "symbol": symbol,
                    "name": lifecycle.get("name", ""),
                    "target_date": date,
                    "first_entry_date": first,
                    "observed": bool(observed),
                    "day_status": day_status,
                    "action_bucket": event.get("action_bucket", "") if event else "",
                    "research_tier": event.get("research_tier", "") if event else "",
                    "research_score": _number(event.get("research_score", 0.0)) if event else math.nan,
                    "risk_level": event.get("risk_level", "") if event else "",
                    "risk_tags": event.get("risk_tags", "") if event else "",
                    "stage": event.get("stage", "") if event else "",
                    "theme": event.get("theme", "") if event else "",
                    "days_since_entry": _trade_elapsed(first, date, trade_dates),
                    **_since_entry_outcome(
                        symbol,
                        first,
                        date,
                        cache_dir=cache_dir,
                        daily_frames=daily_frames,
                    ),
                }
            )

    if not rows:
        return pd.DataFrame(columns=_daily_columns())
    return pd.DataFrame(rows).sort_values(["target_date", "lifecycle_id"]).reset_index(drop=True)


def _lifecycle_row(
    *,
    symbol: str,
    events: list[dict],
    sequence: int,
    target_date: str,
    trade_dates: list[str],
    cache_dir: Path,
    daily_frames: dict[str, pd.DataFrame],
    strategy_version: str,
    gap_trade_days: int,
) -> dict:
    first = events[0]
    last = events[-1]
    first_date = first["target_date"]
    last_seen = last["target_date"]
    first_bucket = first["action_bucket"] or first["research_tier"]
    current_bucket = last["action_bucket"] or last["research_tier"]
    ranked_events = sorted(events, key=lambda item: _stage_rank(item["action_bucket"], item["research_tier"]), reverse=True)
    highest = ranked_events[0]
    highest_bucket = highest["action_bucket"] or highest["research_tier"]
    outcome = _forward_outcome(
        symbol,
        first_date,
        trade_dates,
        cache_dir=cache_dir,
        daily_frames=daily_frames,
    )
    primary_horizon = _primary_horizon(first_bucket)
    max_window = _tracking_window(first_bucket)
    elapsed = _trade_elapsed(first_date, target_date, trade_dates)
    last_gap = _trade_gap(last_seen, target_date, trade_dates)
    result_label = _result_label(outcome, primary_horizon=primary_horizon)
    status = _lifecycle_status(
        elapsed=elapsed,
        max_window=max_window,
        last_gap=last_gap,
        gap_trade_days=gap_trade_days,
    )
    lifecycle_id = "_".join(
        [
            symbol,
            first_date.replace("-", ""),
            _safe_token(strategy_version),
            _safe_token(_bucket_code(first_bucket, first["research_tier"])),
            str(sequence),
        ]
    )
    transitions = _transitions(events)

    row = {
        "lifecycle_id": lifecycle_id,
        "symbol": symbol,
        "name": last.get("name") or first.get("name", ""),
        "strategy_version": strategy_version,
        "lifecycle_sequence": sequence,
        "first_entry_date": first_date,
        "last_seen_date": last_seen,
        "last_evaluated_date": target_date,
        "first_action_bucket": first_bucket,
        "current_action_bucket": current_bucket,
        "highest_action_bucket": highest_bucket,
        "first_tier": first["research_tier"],
        "current_tier": last["research_tier"],
        "highest_tier": highest["research_tier"],
        "days_observed": len(events),
        "days_since_entry": elapsed,
        "gap_trade_days": last_gap,
        "tracking_window_days": max_window,
        "primary_horizon_days": primary_horizon,
        "status": status,
        "result_label": result_label,
        "has_upgrade": transitions["has_upgrade"],
        "has_downgrade": transitions["has_downgrade"],
        "first_score": first["research_score"],
        "current_score": last["research_score"],
        "best_score": max(_number(event.get("research_score", 0.0)) for event in events),
        "score_delta": round(last["research_score"] - first["research_score"], 4),
        "risk_level": last.get("risk_level", ""),
        "risk_tags": last.get("risk_tags", ""),
        "theme": last.get("theme", ""),
        "stage": last.get("stage", ""),
        "setup_phase": last.get("setup_phase", ""),
        "entry_close": _entry_close(symbol, first_date, cache_dir=cache_dir, daily_frames=daily_frames),
    }
    for horizon in FORWARD_HORIZONS:
        prefix = f"{horizon}d"
        row[f"target_date_{prefix}"] = ""
        row[f"ret_{prefix}"] = math.nan
        row[f"high_{prefix}_ret"] = math.nan
        row[f"low_{prefix}_ret"] = math.nan
    row.update(outcome)
    return row


def _event_from_row(row: pd.Series, *, target_date: str, name_map: dict[str, str]) -> dict:
    symbol = str(row.get("symbol", "")).zfill(6)
    action_bucket = _clean_text(row.get("action_bucket", ""))
    tier = _clean_text(row.get("research_tier", ""))
    name = _clean_text(row.get("name", "")) or name_map.get(symbol, "")
    return {
        "target_date": target_date,
        "symbol": symbol,
        "name": name,
        "action_bucket": action_bucket,
        "research_tier": tier,
        "research_score": _number(row.get("research_score", row.get("score", 0.0))),
        "risk_level": _clean_text(row.get("risk_level", "")),
        "risk_tags": _clean_text(row.get("risk_tags", "")),
        "theme": _first_text(
            row.get("theme_cluster", ""),
            row.get("matched_theme", ""),
            row.get("industry", ""),
            row.get("top_keywords", ""),
        ),
        "stage": _clean_text(row.get("stage", "")),
        "setup_phase": _clean_text(row.get("setup_phase", "")),
    }


def _is_tracked_candidate(row: pd.Series) -> bool:
    action_bucket = _clean_text(row.get("action_bucket", ""))
    tier = _clean_text(row.get("research_tier", ""))
    if action_bucket:
        return action_bucket in TRACKED_ACTION_BUCKETS
    return tier in TRACKED_TIERS


def _forward_outcome(
    symbol: str,
    signal_date: str,
    trade_dates: list[str],
    *,
    cache_dir: Path,
    daily_frames: dict[str, pd.DataFrame],
    horizons: tuple[int, ...] = FORWARD_HORIZONS,
) -> dict:
    frame = _load_daily_frame(symbol, cache_dir=cache_dir, daily_frames=daily_frames)
    if frame.empty:
        return {}
    d0 = frame[frame["_date"] == signal_date]
    later_dates = [item for item in trade_dates if item > signal_date]
    if d0.empty or not later_dates:
        return {}
    prev_close = _number(d0.iloc[-1].get("close", 0.0))
    if prev_close <= 0:
        return {}

    outcome: dict[str, float | str] = {}
    for horizon in horizons:
        if len(later_dates) < horizon:
            continue
        target_date = later_dates[horizon - 1]
        window_dates = set(later_dates[:horizon])
        target = frame[frame["_date"] == target_date]
        window = frame[frame["_date"].isin(window_dates)]
        if target.empty or window.empty:
            continue
        close = _number(target.iloc[-1].get("close", 0.0))
        high = _number(window["high"].max(), close)
        low = _number(window["low"].min(), close)
        prefix = f"{horizon}d"
        outcome[f"target_date_{prefix}"] = target_date
        outcome[f"ret_{prefix}"] = close / prev_close - 1
        outcome[f"high_{prefix}_ret"] = high / prev_close - 1
        outcome[f"low_{prefix}_ret"] = low / prev_close - 1
    return outcome


def _since_entry_outcome(
    symbol: str,
    entry_date: str,
    current_date: str,
    *,
    cache_dir: Path,
    daily_frames: dict[str, pd.DataFrame],
) -> dict:
    if current_date < entry_date:
        return {"since_entry_ret": math.nan, "since_entry_high_ret": math.nan, "since_entry_low_ret": math.nan}
    frame = _load_daily_frame(symbol, cache_dir=cache_dir, daily_frames=daily_frames)
    if frame.empty:
        return {"since_entry_ret": math.nan, "since_entry_high_ret": math.nan, "since_entry_low_ret": math.nan}
    entry = frame[frame["_date"] == entry_date]
    current = frame[frame["_date"] == current_date]
    if entry.empty or current.empty:
        return {"since_entry_ret": math.nan, "since_entry_high_ret": math.nan, "since_entry_low_ret": math.nan}
    entry_close = _number(entry.iloc[-1].get("close", 0.0))
    if entry_close <= 0:
        return {"since_entry_ret": math.nan, "since_entry_high_ret": math.nan, "since_entry_low_ret": math.nan}
    if current_date == entry_date:
        return {"since_entry_ret": 0.0, "since_entry_high_ret": 0.0, "since_entry_low_ret": 0.0}
    window = frame[(frame["_date"] > entry_date) & (frame["_date"] <= current_date)]
    if window.empty:
        return {"since_entry_ret": math.nan, "since_entry_high_ret": math.nan, "since_entry_low_ret": math.nan}
    close = _number(current.iloc[-1].get("close", 0.0))
    high = _number(window["high"].max(), close)
    low = _number(window["low"].min(), close)
    return {
        "since_entry_ret": close / entry_close - 1,
        "since_entry_high_ret": high / entry_close - 1,
        "since_entry_low_ret": low / entry_close - 1,
    }


def _load_daily_frame(
    symbol: str,
    *,
    cache_dir: Path,
    daily_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if symbol in daily_frames:
        return daily_frames[symbol]
    try:
        frame = load_daily_cache(symbol, cache_dir=cache_dir)
    except Exception:
        daily_frames[symbol] = pd.DataFrame()
        return daily_frames[symbol]
    output = frame.copy()
    output["timestamp"] = pd.to_datetime(output["timestamp"], errors="coerce")
    output = output.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    output["_date"] = output["timestamp"].dt.date.astype(str)
    daily_frames[symbol] = output
    return output


def _entry_close(
    symbol: str,
    entry_date: str,
    *,
    cache_dir: Path,
    daily_frames: dict[str, pd.DataFrame],
) -> float:
    frame = _load_daily_frame(symbol, cache_dir=cache_dir, daily_frames=daily_frames)
    if frame.empty:
        return math.nan
    row = frame[frame["_date"] == entry_date]
    if row.empty:
        return math.nan
    return _number(row.iloc[-1].get("close", math.nan), math.nan)


def _trading_dates_from_cache(cache_dir: Path) -> list[str]:
    daily_dir = cache_dir / "akshare" / "daily"
    if not daily_dir.exists():
        return []
    dates: set[str] = set()
    for path in daily_dir.glob("*.csv"):
        try:
            frame = pd.read_csv(path, usecols=["timestamp"])
        except Exception:
            continue
        parsed = pd.to_datetime(frame["timestamp"], errors="coerce").dropna()
        dates.update(parsed.dt.date.astype(str).tolist())
    return sorted(dates)


def _snapshot_dates(root: Path, *, until: str | None) -> list[str]:
    if not root.exists():
        return []
    dates = []
    for path in root.iterdir():
        if not path.is_dir() or not (path / "research_candidates.csv").exists():
            continue
        if until and path.name > until:
            continue
        dates.append(path.name)
    return sorted(dates)


def _load_name_map(universe_file: Path | None) -> dict[str, str]:
    path = universe_file or DEFAULT_PATHS.root / "data" / "universe" / "a_stock.csv"
    if not path.exists():
        return {}
    try:
        frame = load_universe_file(path)
    except Exception:
        return {}
    if frame.empty or "symbol" not in frame.columns or "name" not in frame.columns:
        return {}
    output = frame.copy()
    output["symbol"] = output["symbol"].astype(str).str.zfill(6)
    output["name"] = output["name"].fillna("").astype(str)
    return dict(zip(output["symbol"], output["name"]))


def _trade_gap(previous: str, current: str, trade_dates: list[str]) -> int:
    if current <= previous:
        return 0
    if previous in trade_dates and current in trade_dates:
        return max(0, trade_dates.index(current) - trade_dates.index(previous) - 1)
    if trade_dates:
        between = [date for date in trade_dates if previous < date < current]
        return len(between)
    return max(0, (pd.Timestamp(current) - pd.Timestamp(previous)).days - 1)


def _trade_elapsed(first: str, current: str, trade_dates: list[str]) -> int:
    if current <= first:
        return 0
    if first in trade_dates and current in trade_dates:
        return max(0, trade_dates.index(current) - trade_dates.index(first))
    if trade_dates:
        return len([date for date in trade_dates if first < date <= current])
    return max(0, (pd.Timestamp(current) - pd.Timestamp(first)).days)


def _event_day_status(event: dict, previous: dict | None, *, first_entry: str) -> str:
    if event["target_date"] == first_entry:
        return "new"
    if previous is None:
        return "tracking"
    current_rank = _stage_rank(event["action_bucket"], event["research_tier"])
    previous_rank = _stage_rank(previous["action_bucket"], previous["research_tier"])
    if current_rank > previous_rank:
        return "upgraded"
    if current_rank < previous_rank:
        return "downgraded"
    return "tracking"


def _transitions(events: list[dict]) -> dict[str, bool]:
    has_upgrade = False
    has_downgrade = False
    previous = None
    for event in events:
        if previous is None:
            previous = event
            continue
        current_rank = _stage_rank(event["action_bucket"], event["research_tier"])
        previous_rank = _stage_rank(previous["action_bucket"], previous["research_tier"])
        has_upgrade = has_upgrade or current_rank > previous_rank
        has_downgrade = has_downgrade or current_rank < previous_rank
        previous = event
    return {"has_upgrade": has_upgrade, "has_downgrade": has_downgrade}


def _stage_rank(action_bucket: str, tier: str) -> int:
    if action_bucket in ACTION_STAGE_RANK:
        return ACTION_STAGE_RANK[action_bucket]
    return TIER_STAGE_RANK.get(tier, 0)


def _primary_horizon(bucket_or_tier: str) -> int:
    return 10 if bucket_or_tier in {"主攻-A3趋势延续", "A3"} else 5


def _tracking_window(bucket_or_tier: str) -> int:
    return 15 if bucket_or_tier in {"主攻-A3趋势延续", "A3"} else 10


def _lifecycle_status(*, elapsed: int, max_window: int, last_gap: int, gap_trade_days: int) -> str:
    if elapsed >= max_window:
        return "expired"
    if last_gap > gap_trade_days:
        return "removed"
    return "active"


def _result_label(outcome: dict, *, primary_horizon: int) -> str:
    prefix = f"{primary_horizon}d"
    high = outcome.get(f"high_{prefix}_ret")
    low = outcome.get(f"low_{prefix}_ret")
    if high is None or low is None:
        return "pending"
    high_value = _number(high)
    low_value = _number(low)
    if high_value >= 0.15:
        return "strong_hit"
    if high_value >= 0.08:
        return "hit"
    if low_value <= -0.06 and high_value < 0.03:
        return "failed"
    return "neutral"


def _summarize_lifecycles(lifecycles: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "first_action_bucket",
        "count",
        "active_count",
        "hit_count",
        "strong_hit_count",
        "failed_count",
        "avg_ret_3d",
        "avg_ret_5d",
        "avg_ret_10d",
        "avg_high_5d",
        "avg_low_5d",
    ]
    if lifecycles.empty:
        return pd.DataFrame(columns=columns)
    lifecycles = lifecycles.copy()
    for column in ["ret_3d", "ret_5d", "ret_10d", "high_5d_ret", "low_5d_ret"]:
        if column not in lifecycles.columns:
            lifecycles[column] = math.nan
    output = (
        lifecycles.groupby("first_action_bucket", dropna=False)
        .agg(
            count=("symbol", "count"),
            active_count=("status", lambda values: int((values == "active").sum())),
            hit_count=("result_label", lambda values: int(values.isin(["hit", "strong_hit"]).sum())),
            strong_hit_count=("result_label", lambda values: int((values == "strong_hit").sum())),
            failed_count=("result_label", lambda values: int((values == "failed").sum())),
            avg_ret_3d=("ret_3d", "mean"),
            avg_ret_5d=("ret_5d", "mean"),
            avg_ret_10d=("ret_10d", "mean"),
            avg_high_5d=("high_5d_ret", "mean"),
            avg_low_5d=("low_5d_ret", "mean"),
        )
        .reset_index()
    )
    for column in ["avg_ret_3d", "avg_ret_5d", "avg_ret_10d", "avg_high_5d", "avg_low_5d"]:
        output[column] = output[column].round(4)
    return output.loc[:, columns]


def _render_lifecycle_markdown(tracking: CandidateLifecycleTracking, *, top: int) -> str:
    lifecycles = tracking.lifecycles.copy()
    lines = [
        "# 候选生命周期跟踪",
        "",
        f"- 目标日期：{tracking.target_date}",
        f"- 快照日期数：{len(tracking.snapshot_dates)}",
        f"- 生命周期数量：{len(lifecycles)}",
        f"- 跟踪分组：{'、'.join(TRACKED_ACTION_BUCKETS)}",
        "",
        "## 分组表现",
        "",
        _markdown_table(_display_frame(tracking.summary)),
        "",
    ]

    if lifecycles.empty:
        lines.append("无生命周期样本。")
        return "\n".join(lines)

    active = lifecycles[lifecycles["status"] == "active"].sort_values(
        ["result_label", "current_score"], ascending=[True, False]
    )
    lines.extend(["## 仍在跟踪", ""])
    lines.append(
        _markdown_table(
            _display_frame(
                active.head(top).loc[
                    :,
                    _existing(
                        active,
                        [
                            "symbol",
                            "name",
                            "first_entry_date",
                            "current_action_bucket",
                            "result_label",
                            "days_since_entry",
                            "ret_3d",
                            "high_5d_ret",
                            "low_5d_ret",
                            "risk_level",
                            "risk_tags",
                        ],
                    ),
                ],
            )
        )
    )
    lines.extend(["", "## 已命中样本", ""])
    hits = lifecycles[lifecycles["result_label"].isin(["hit", "strong_hit"])].sort_values(
        ["high_5d_ret", "high_10d_ret"], ascending=[False, False]
    )
    lines.append(
        _markdown_table(
            _display_frame(
                hits.head(top).loc[
                    :,
                    _existing(
                        hits,
                        [
                            "symbol",
                            "name",
                            "first_entry_date",
                            "first_action_bucket",
                            "highest_action_bucket",
                            "result_label",
                            "high_5d_ret",
                            "ret_5d",
                            "high_10d_ret",
                            "ret_10d",
                        ],
                    ),
                ],
            )
        )
    )
    lines.extend(["", "## 失败或风险样本", ""])
    risk = lifecycles[
        (lifecycles["result_label"] == "failed")
        | (lifecycles["risk_level"].isin(["中高", "高"]))
    ].sort_values(["result_label", "low_5d_ret"], ascending=[True, True])
    lines.append(
        _markdown_table(
            _display_frame(
                risk.head(top).loc[
                    :,
                    _existing(
                        risk,
                        [
                            "symbol",
                            "name",
                            "first_entry_date",
                            "current_action_bucket",
                            "result_label",
                            "low_5d_ret",
                            "ret_5d",
                            "risk_level",
                            "risk_tags",
                        ],
                    ),
                ],
            )
        )
    )
    lines.extend(
        [
            "",
            "## 使用口径",
            "",
            "- `active` 表示仍在观察窗口内，且最近消失不超过 3 个交易日。",
            "- `expired` 表示观察窗口已经走完，后续主要进入策略复盘。",
            "- `strong_hit` / `hit` / `failed` 根据入池后主要观察窗口的最大浮盈和最大回撤打标。",
            "- 这份报告用于复盘和跟踪，不构成买卖建议。",
        ]
    )
    return "\n".join(lines)


DISPLAY_COLUMN_NAMES = {
    "first_action_bucket": "入池分组",
    "count": "样本",
    "active_count": "仍跟踪",
    "hit_count": "命中",
    "strong_hit_count": "强命中",
    "failed_count": "失败",
    "avg_ret_3d": "3日均值",
    "avg_ret_5d": "5日均值",
    "avg_ret_10d": "10日均值",
    "avg_high_5d": "5日最大浮盈",
    "avg_low_5d": "5日最大回撤",
    "symbol": "代码",
    "name": "名称",
    "first_entry_date": "入池日",
    "current_action_bucket": "当前分组",
    "first_action_bucket": "入池分组",
    "highest_action_bucket": "最高分组",
    "result_label": "结果",
    "days_since_entry": "已走交易日",
    "ret_3d": "3日收益",
    "ret_5d": "5日收益",
    "ret_10d": "10日收益",
    "high_5d_ret": "5日最大浮盈",
    "low_5d_ret": "5日最大回撤",
    "high_10d_ret": "10日最大浮盈",
    "low_10d_ret": "10日最大回撤",
    "risk_level": "风险",
    "risk_tags": "风险标签",
}


def _display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return _format_percent_frame(frame).rename(columns=DISPLAY_COLUMN_NAMES)


def _format_percent_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output.columns:
        if _is_percent_column(column):
            output[column] = output[column].map(_format_pct)
    return output


def _is_percent_column(column: str) -> bool:
    return bool(
        re.match(r"^ret_\d+d$", column)
        or re.match(r"^high_\d+d_ret$", column)
        or re.match(r"^low_\d+d_ret$", column)
        or column.startswith("avg_ret_")
        or column.startswith("avg_high_")
        or column.startswith("avg_low_")
        or column.startswith("since_entry_")
    )


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "无"
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in frame.iterrows():
        values = [_format_markdown_value(row.get(column, "")) for column in frame.columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _format_markdown_value(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value)
    return text.replace("|", "/").replace("\n", " ")


def _format_pct(value: object) -> str:
    number = _number(value, math.nan)
    if math.isnan(number):
        return ""
    return f"{number * 100:.2f}%"


def _existing(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in frame.columns]


def _number(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _first_text(*values: object) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _bucket_code(bucket_or_tier: str, tier: str) -> str:
    mapping = {
        "补票-B2强主题": "B2",
        "主攻-A2启动确认": "A2",
        "主攻-A3趋势延续": "A3",
    }
    return mapping.get(bucket_or_tier, tier or bucket_or_tier or "NA")


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", value)
    return token.strip("_") or "NA"


def _lifecycle_columns() -> list[str]:
    return [
        "lifecycle_id",
        "symbol",
        "name",
        "strategy_version",
        "lifecycle_sequence",
        "first_entry_date",
        "last_seen_date",
        "last_evaluated_date",
        "first_action_bucket",
        "current_action_bucket",
        "highest_action_bucket",
        "first_tier",
        "current_tier",
        "highest_tier",
        "days_observed",
        "days_since_entry",
        "gap_trade_days",
        "tracking_window_days",
        "primary_horizon_days",
        "status",
        "result_label",
    ]


def _daily_columns() -> list[str]:
    return [
        "lifecycle_id",
        "symbol",
        "name",
        "target_date",
        "first_entry_date",
        "observed",
        "day_status",
        "action_bucket",
        "research_tier",
        "research_score",
        "risk_level",
        "risk_tags",
        "stage",
        "theme",
        "days_since_entry",
        "since_entry_ret",
        "since_entry_high_ret",
        "since_entry_low_ret",
    ]
