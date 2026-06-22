from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.cache import load_daily_cache
from quant_a_stock.data.universe import load_universe_file
from quant_a_stock.research.snapshot import SNAPSHOT_ROOT


CORE_TIERS = ("A", "B", "A1", "A2", "A3", "B1", "B2")
ACTION_TIERS = ("A", "B", "A1", "A2", "A3", "B1")
FORWARD_HORIZONS = (1, 3, 5)
TIER_ORDER = {
    "A": 1,
    "A1": 1,
    "A2": 2,
    "A3": 3,
    "B": 4,
    "B1": 4,
    "B2": 5,
    "C": 6,
    "观察": 7,
}


@dataclass(frozen=True)
class ResearchReview:
    snapshot_dates: list[str]
    closed_signal_dates: list[str]
    details: pd.DataFrame
    by_tier: pd.DataFrame
    by_tier_horizon: pd.DataFrame
    by_day_tier: pd.DataFrame
    by_stage: pd.DataFrame
    by_stage_horizon: pd.DataFrame
    portfolio: pd.DataFrame
    market_capture: pd.DataFrame
    missed_movers: pd.DataFrame


def build_research_review(
    *,
    since: str | None = None,
    until: str | None = None,
    snapshot_root: Path = SNAPSHOT_ROOT,
    top_movers: int = 20,
    universe_file: Path | None = None,
    min_market_count: int = 100,
) -> ResearchReview:
    snapshot_dates = _snapshot_dates(snapshot_root, since=since, until=until)
    cache_dir = DEFAULT_PATHS.data_cache
    trade_dates = _trading_dates_from_cache(cache_dir=cache_dir, min_count=min_market_count)
    names = _name_map(universe_file)
    daily_frames: dict[str, pd.DataFrame] = {}

    detail_rows: list[dict] = []
    capture_rows: list[dict] = []
    missed_rows: list[dict] = []

    for signal_date in snapshot_dates:
        next_date = _next_trade_date(signal_date, trade_dates)
        if not next_date:
            continue

        snapshot_dir = snapshot_root / signal_date
        candidates = _load_snapshot_candidates(snapshot_dir / "research_candidates.csv", names)
        if candidates.empty:
            continue
        scan_index = _load_snapshot_scan_index(snapshot_dir)

        selected = candidates[candidates["research_tier"].isin(CORE_TIERS)].copy()
        for _, row in selected.iterrows():
            outcome = _forward_outcome(
                str(row["symbol"]),
                signal_date,
                trade_dates,
                cache_dir=cache_dir,
                daily_frames=daily_frames,
            )
            if not outcome:
                continue
            detail_rows.append(
                {
                    "signal_date": signal_date,
                    "next_date": next_date,
                    "symbol": row["symbol"],
                    "name": row.get("name", "") or names.get(row["symbol"], ""),
                    "tier": row["research_tier"],
                    "score": _number(row.get("research_score", row.get("score", 0.0))),
                    "setup_phase": row.get("setup_phase", ""),
                    "stage": row.get("stage", ""),
                    "theme_cluster": row.get("theme_cluster", row.get("matched_theme", "")),
                    **outcome,
                }
            )

        market = _market_next_day_outcomes(
            signal_date,
            next_date,
            names,
            cache_dir=cache_dir,
            daily_frames=daily_frames,
        )
        if market.empty:
            continue

        candidate_symbols = set(candidates["symbol"])
        core_symbols = set(selected["symbol"])
        action_symbols = set(candidates[candidates["research_tier"].isin(ACTION_TIERS)]["symbol"])
        market["in_candidates"] = market["symbol"].isin(candidate_symbols)
        market["in_core"] = market["symbol"].isin(core_symbols)
        market["in_action"] = market["symbol"].isin(action_symbols)

        top = market.sort_values("next_ret", ascending=False).head(top_movers)
        capture_rows.append(
            {
                "signal_date": signal_date,
                "next_date": next_date,
                "market_count": len(market),
                "market_avg_ret": market["next_ret"].mean(),
                "market_median_ret": market["next_ret"].median(),
                "top_movers": len(top),
                "top_in_candidates": int(top["in_candidates"].sum()),
                "top_in_core": int(top["in_core"].sum()),
                "top_in_action": int(top["in_action"].sum()),
            }
        )
        for _, mover in top[~top["in_candidates"]].head(5).iterrows():
            scan_context = scan_index.get(str(mover["symbol"]), {})
            miss_context = _miss_context(
                str(mover["symbol"]),
                signal_date,
                next_date,
                cache_dir=cache_dir,
                daily_frames=daily_frames,
                scan_context=scan_context,
            )
            missed_rows.append(
                {
                    "signal_date": signal_date,
                    "next_date": next_date,
                    "symbol": mover["symbol"],
                    "name": mover["name"],
                    "next_ret": mover["next_ret"],
                    **miss_context,
                }
            )

    details = pd.DataFrame(detail_rows)
    by_tier = _aggregate(details, ["tier"])
    if not by_tier.empty:
        by_tier["tier_rank"] = by_tier["tier"].map(TIER_ORDER).fillna(99)
        by_tier = by_tier.sort_values(["tier_rank", "tier"]).drop(columns=["tier_rank"])

    by_tier_horizon = _aggregate_horizons(details, ["tier"])
    if not by_tier_horizon.empty:
        by_tier_horizon["tier_rank"] = by_tier_horizon["tier"].map(TIER_ORDER).fillna(99)
        by_tier_horizon["horizon_rank"] = by_tier_horizon["horizon"].str.replace("d", "").astype(int)
        by_tier_horizon = by_tier_horizon.sort_values(["tier_rank", "horizon_rank", "tier"]).drop(
            columns=["tier_rank", "horizon_rank"]
        )

    by_day_tier = _aggregate(details, ["signal_date", "next_date", "tier"])
    by_stage = _aggregate(details, ["stage"])
    by_stage_horizon = _aggregate_horizons(details, ["stage"])
    portfolio = _portfolio_summary(details)
    market_capture = pd.DataFrame(capture_rows)
    missed_movers = pd.DataFrame(missed_rows)
    closed_dates = sorted(details["signal_date"].unique().tolist()) if not details.empty else []

    return ResearchReview(
        snapshot_dates=snapshot_dates,
        closed_signal_dates=closed_dates,
        details=details,
        by_tier=by_tier,
        by_tier_horizon=by_tier_horizon,
        by_day_tier=by_day_tier,
        by_stage=by_stage,
        by_stage_horizon=by_stage_horizon,
        portfolio=portfolio,
        market_capture=market_capture,
        missed_movers=missed_movers,
    )


def save_research_review_reports(review: ResearchReview) -> tuple[Path, Path, Path]:
    DEFAULT_PATHS.reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    details_path = DEFAULT_PATHS.reports / f"research_review_details_{stamp}.csv"
    summary_path = DEFAULT_PATHS.reports / f"research_review_summary_{stamp}.csv"
    missed_path = DEFAULT_PATHS.reports / f"research_review_missed_{stamp}.csv"
    markdown_path = DEFAULT_PATHS.reports / f"research_review_{stamp}.md"

    review.details.to_csv(details_path, index=False, encoding="utf-8-sig")
    _summary_tables(review).to_csv(summary_path, index=False, encoding="utf-8-sig")
    review.missed_movers.to_csv(missed_path, index=False, encoding="utf-8-sig")
    markdown_path.write_text(
        _review_markdown(review, details_path, summary_path, missed_path),
        encoding="utf-8",
    )
    return markdown_path, details_path, summary_path


def _summary_tables(review: ResearchReview) -> pd.DataFrame:
    frames = []
    for name, frame in (
        ("by_tier", review.by_tier),
        ("by_tier_horizon", review.by_tier_horizon),
        ("by_day_tier", review.by_day_tier),
        ("by_stage", review.by_stage),
        ("by_stage_horizon", review.by_stage_horizon),
        ("portfolio", review.portfolio),
        ("market_capture", review.market_capture),
    ):
        if frame.empty:
            continue
        output = frame.copy()
        output.insert(0, "table", name)
        frames.append(output)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def _review_markdown(
    review: ResearchReview,
    details_path: Path,
    summary_path: Path,
    missed_path: Path,
) -> str:
    winners = (
        review.details.sort_values("next_ret", ascending=False).head(20)
        if not review.details.empty
        else pd.DataFrame()
    )
    losers = (
        review.details.sort_values("next_ret").head(15)
        if not review.details.empty
        else pd.DataFrame()
    )

    lines = [
        "# 研究候选策略复盘",
        "",
        f"- 可用快照：{', '.join(review.snapshot_dates) or '无'}",
        f"- 已闭环信号日：{', '.join(review.closed_signal_dates) or '无'}",
        f"- 明细 CSV：{details_path}",
        f"- 汇总 CSV：{summary_path}",
        f"- 错过样本 CSV：{missed_path}",
        "",
        "## 核心结论",
        "",
        "- A2、A3、B1/B2 要分开评价：A2 看潜伏转强，A3 看趋势延续，B1/B2 看观察补票。",
        "- 如果 A3 和趋势回踩表现靠前，说明当前市场更奖励主线趋势；如果 A2 次日表现滞后，要继续看 3/5 日窗口，避免误杀潜伏模型。",
        "- 市场强票捕获数偏低时，说明突发催化和 20cm 弹性没有被形态池提前覆盖，需要补“主线突发补票”。",
        "- 这版复盘同时看 1/3/5 个交易日：A2 重点看 3/5 日，A3 重点看 1/3 日，B1/B2 只看是否值得补票观察。",
        "",
        "## 分层 1/3/5 日表现",
        "",
        _markdown_table(
            review.by_tier_horizon,
            percent_cols=[
                "avg_ret",
                "median_ret",
                "win_rate",
                "gt5_rate",
                "lt_minus5_rate",
                "avg_high",
                "avg_low",
                "max_ret",
                "min_ret",
            ],
        ),
        "",
        "## 分层次日表现",
        "",
        _markdown_table(
            review.by_tier,
            percent_cols=[
                "avg_ret",
                "median_ret",
                "win_rate",
                "gt5_rate",
                "lt_minus5_rate",
                "avg_high",
                "avg_low",
                "max_ret",
                "min_ret",
            ],
        ),
        "",
        "## 按日分层表现",
        "",
        _markdown_table(
            review.by_day_tier,
            percent_cols=[
                "avg_ret",
                "median_ret",
                "win_rate",
                "gt5_rate",
                "lt_minus5_rate",
                "avg_high",
                "avg_low",
                "max_ret",
                "min_ret",
            ],
        ),
        "",
        "## 阶段表现",
        "",
        _markdown_table(
            review.by_stage,
            percent_cols=[
                "avg_ret",
                "median_ret",
                "win_rate",
                "gt5_rate",
                "lt_minus5_rate",
                "avg_high",
                "avg_low",
                "max_ret",
                "min_ret",
            ],
        ),
        "",
        "## 阶段 1/3/5 日表现",
        "",
        _markdown_table(
            review.by_stage_horizon,
            percent_cols=[
                "avg_ret",
                "median_ret",
                "win_rate",
                "gt5_rate",
                "lt_minus5_rate",
                "avg_high",
                "avg_low",
                "max_ret",
                "min_ret",
            ],
        ),
        "",
        "## 重点池表现",
        "",
        _markdown_table(review.portfolio, percent_cols=["avg_ret", "win_rate", "max_ret", "min_ret"]),
        "",
        "## 市场强票捕获",
        "",
        _markdown_table(review.market_capture, percent_cols=["market_avg_ret", "market_median_ret"]),
        "",
        "## 命中样本 Top 20",
        "",
        _markdown_table(
            winners[
                _existing(
                    winners,
                    [
                        "signal_date",
                        "next_date",
                        "symbol",
                        "name",
                        "tier",
                        "score",
                        "setup_phase",
                        "stage",
                        "next_ret",
                        "next_high_ret",
                    ],
                )
            ],
            percent_cols=["next_ret", "next_high_ret"],
        ),
        "",
        "## 亏损样本 Top 15",
        "",
        _markdown_table(
            losers[
                _existing(
                    losers,
                    [
                        "signal_date",
                        "next_date",
                        "symbol",
                        "name",
                        "tier",
                        "score",
                        "setup_phase",
                        "stage",
                        "next_ret",
                        "next_low_ret",
                    ],
                )
            ],
            percent_cols=["next_ret", "next_low_ret"],
        ),
        "",
        "## 明显错过样本和风险提示",
        "",
        _markdown_table(
            review.missed_movers[
                _existing(
                    review.missed_movers,
                    [
                        "signal_date",
                        "next_date",
                        "symbol",
                        "name",
                        "next_ret",
                        "miss_reason",
                        "risk_level",
                        "risk_tags",
                        "action_hint",
                        "scan_source",
                        "scan_stage",
                        "scan_score",
                        "ret_20_pct",
                        "volume_ratio",
                        "amount_ma20",
                        "price_position_120_pct",
                    ],
                )
            ],
            percent_cols=["next_ret", "ret_20_pct", "price_position_120_pct"],
        ),
        "",
        "## 下一轮调整",
        "",
        "- A3：保留趋势延续能力，但加高位拥挤、放量滞涨和风险公告过滤。",
        "- A2：用 3-5 日窗口复盘，避免用次日涨跌误判潜伏票。",
        "- B1/B2：作为观察补票池，不直接当作买点。",
        "- Miss：先剔除复权/除权/特殊事件疑似样本，再反推正常涨停票的主线补票条件。",
        "- 风险：所有补票样本先做公告、质押、减持、问询和流动性核验，不能只因次日大涨就追高。",
        "",
        "这份报告只做策略复盘，不构成买卖建议。",
    ]
    return "\n".join(lines)


def _snapshot_dates(snapshot_root: Path, *, since: str | None, until: str | None) -> list[str]:
    if not snapshot_root.exists():
        return []
    dates = [
        path.name
        for path in snapshot_root.iterdir()
        if path.is_dir() and (path / "research_candidates.csv").exists()
    ]
    if since:
        dates = [date for date in dates if date >= since]
    if until:
        dates = [date for date in dates if date <= until]
    return sorted(dates)


def _load_snapshot_candidates(path: Path, names: dict[str, str]) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": str})
    if frame.empty or "symbol" not in frame.columns or "research_tier" not in frame.columns:
        return pd.DataFrame()
    output = frame.copy()
    output["symbol"] = output["symbol"].astype(str).str.zfill(6)
    output["research_tier"] = output["research_tier"].fillna("").astype(str).replace({"밖뀁": "观察"})
    if "name" not in output.columns:
        output["name"] = ""
    output["name"] = output.apply(
        lambda row: _clean_text(row.get("name", "")) or names.get(row["symbol"], ""),
        axis=1,
    )
    if "research_score" not in output.columns:
        output["research_score"] = output.get("score", 0.0)
    output["research_score"] = pd.to_numeric(output["research_score"], errors="coerce").fillna(0.0)
    return output


def _load_snapshot_scan_index(snapshot_dir: Path) -> dict[str, dict]:
    scan_files = {
        "scan_base_breakout_setup.csv": "突破确认扫描",
        "scan_accumulation_setup.csv": "低位潜伏扫描",
        "scan_trend_pullback_setup.csv": "趋势回踩扫描",
    }
    rows: dict[str, dict] = {}
    for filename, source in scan_files.items():
        path = snapshot_dir / filename
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype={"symbol": str})
        except Exception:
            continue
        if frame.empty or "symbol" not in frame.columns:
            continue
        frame = frame.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
        if "score" not in frame.columns:
            frame["score"] = 0.0
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce").fillna(0.0)
        for _, row in frame.iterrows():
            symbol = row["symbol"]
            score = _number(row.get("score", 0.0))
            current = rows.get(symbol)
            if current and score <= current.get("scan_score", 0.0):
                continue
            rows[symbol] = {
                "scan_source": source,
                "scan_stage": _clean_text(row.get("stage", "")),
                "scan_phase": _clean_text(row.get("setup_phase", "")),
                "scan_score": score,
            }
    return rows


def _miss_context(
    symbol: str,
    signal_date: str,
    next_date: str,
    *,
    cache_dir: Path,
    daily_frames: dict[str, pd.DataFrame],
    scan_context: dict,
) -> dict:
    frame = _load_daily_frame(symbol, cache_dir=cache_dir, daily_frames=daily_frames)
    context = {
        "miss_reason": "形态未入池",
        "scan_source": scan_context.get("scan_source", ""),
        "scan_stage": scan_context.get("scan_stage", ""),
        "scan_phase": scan_context.get("scan_phase", ""),
        "scan_score": scan_context.get("scan_score", 0.0),
        "ret_20_pct": 0.0,
        "volume_ratio": 0.0,
        "amount_ma20": 0.0,
        "price_position_120_pct": 0.0,
        "listing_bars": 0,
        "risk_level": "中",
        "risk_tags": "未做公告风险核验",
        "action_hint": "先补情绪和公告核验，再决定是否纳入补票观察。",
    }
    if context["scan_source"]:
        context["miss_reason"] = "形态入池但未进入最终候选"
    if frame.empty:
        context["risk_level"] = "高"
        context["risk_tags"] = "行情缓存缺失；未做公告风险核验"
        context["action_hint"] = "剔除出策略复盘，先修复数据。"
        return context

    history = frame[frame["_date"] <= signal_date].copy()
    target = frame[frame["_date"] == next_date]
    if history.empty or target.empty:
        context["risk_level"] = "高"
        context["risk_tags"] = "信号日或次日行情缺失；未做公告风险核验"
        context["action_hint"] = "剔除出策略复盘，先修复数据。"
        return context

    close = history["close"].astype(float)
    volume = history["volume"].astype(float)
    amount = history["amount"].astype(float) if "amount" in history.columns else close * volume
    latest_close = _number(close.iloc[-1])
    next_close = _number(target.iloc[-1].get("close", 0.0))
    next_ret = next_close / latest_close - 1 if latest_close > 0 else 0.0
    ret_20 = latest_close / _number(close.iloc[-21], latest_close) - 1 if len(close) > 20 else 0.0
    volume_ma20 = _number(volume.tail(20).mean())
    volume_ratio = _number(volume.iloc[-1]) / volume_ma20 if volume_ma20 > 0 else 0.0
    amount_ma20 = _number(amount.tail(20).mean())
    tail = history.tail(120)
    high_120 = _number(tail["high"].max())
    low_120 = _number(tail["low"].min())
    price_position = (latest_close - low_120) / (high_120 - low_120) if high_120 > low_120 else 0.0

    context.update(
        {
            "ret_20_pct": round(ret_20, 4),
            "volume_ratio": round(volume_ratio, 4),
            "amount_ma20": round(amount_ma20, 2),
            "price_position_120_pct": round(price_position, 4),
            "listing_bars": int(len(history)),
        }
    )

    risk_tags = []
    limit_threshold = _daily_limit_threshold(symbol)
    if next_ret > limit_threshold + 0.03:
        risk_tags.append("次日涨幅超常规涨跌幅，疑似复权/除权/特殊事件")
    if ret_20 >= 0.25:
        risk_tags.append("前 20 日涨幅偏高")
    if price_position >= 0.85:
        risk_tags.append("120 日区间位置偏高")
    if volume_ratio >= 3.0:
        risk_tags.append("信号日放量过猛")
    if amount_ma20 and amount_ma20 < 100_000_000:
        risk_tags.append("20 日成交额偏低")
    if len(history) < 250:
        risk_tags.append("次新或历史样本不足")
    risk_tags.append("未做公告风险核验")

    context["risk_tags"] = "；".join(risk_tags)
    context["risk_level"] = _miss_risk_level(risk_tags)
    context["action_hint"] = _miss_action_hint(
        risk_tags=risk_tags,
        scan_source=context["scan_source"],
    )
    return context


def _daily_limit_threshold(symbol: str) -> float:
    if symbol.startswith(("300", "301", "688", "689")):
        return 0.20
    if symbol.startswith(("4", "8")):
        return 0.30
    return 0.10


def _miss_risk_level(risk_tags: list[str]) -> str:
    joined = "；".join(risk_tags)
    if "超常规涨跌幅" in joined or "成交额偏低" in joined or "次新" in joined:
        return "高"
    if "位置偏高" in joined or "放量过猛" in joined or "涨幅偏高" in joined:
        return "中高"
    return "中"


def _miss_action_hint(*, risk_tags: list[str], scan_source: str) -> str:
    joined = "；".join(risk_tags)
    if "超常规涨跌幅" in joined:
        return "剔除出策略归因，按复权/事件样本单独复核。"
    if "成交额偏低" in joined or "次新" in joined:
        return "只做事件观察，不纳入常规补票池。"
    if scan_source:
        return "复核为何未进入最终候选，优先检查情绪、主题和风险扣分。"
    return "纳入主线突发补票池反推，但追高前必须补情绪和公告核验。"


def _name_map(universe_file: Path | None) -> dict[str, str]:
    path = universe_file or DEFAULT_PATHS.root / "data" / "universe" / "a_stock.csv"
    if not path.exists():
        return {}
    frame = load_universe_file(path)
    return dict(zip(frame["symbol"].astype(str).str.zfill(6), frame["name"].fillna("").astype(str)))


def _trading_dates_from_cache(cache_dir: Path, *, min_count: int = 100) -> list[str]:
    daily_dir = cache_dir / "akshare" / "daily"
    counts: dict[str, int] = {}
    if not daily_dir.exists():
        return []
    for path in daily_dir.glob("*.csv"):
        try:
            frame = pd.read_csv(path, usecols=["timestamp"])
        except Exception:
            continue
        dates = pd.to_datetime(frame["timestamp"], errors="coerce").dropna().dt.date.astype(str).unique()
        for date in dates:
            counts[str(date)] = counts.get(str(date), 0) + 1
    return sorted(date for date, count in counts.items() if count >= min_count)


def _next_trade_date(date: str, dates: list[str]) -> str | None:
    later = [item for item in dates if item > date]
    return later[0] if later else None


def _forward_outcome(
    symbol: str,
    signal_date: str,
    trade_dates: list[str],
    *,
    cache_dir: Path,
    daily_frames: dict[str, pd.DataFrame],
    horizons: tuple[int, ...] = FORWARD_HORIZONS,
) -> dict | None:
    frame = _load_daily_frame(symbol, cache_dir=cache_dir, daily_frames=daily_frames)
    if frame.empty:
        return None
    d0 = frame[frame["_date"] == signal_date]
    later_dates = [item for item in trade_dates if item > signal_date]
    if d0.empty or not later_dates:
        return None
    prev_close = _number(d0.iloc[-1].get("close", 0.0))
    if prev_close <= 0:
        return None

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

    if "ret_1d" not in outcome:
        return None
    outcome["next_date"] = outcome.get("target_date_1d", "")
    outcome["next_ret"] = outcome["ret_1d"]
    outcome["next_high_ret"] = outcome["high_1d_ret"]
    outcome["next_low_ret"] = outcome["low_1d_ret"]
    return outcome


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


def _market_next_day_outcomes(
    signal_date: str,
    next_date: str,
    names: dict[str, str],
    *,
    cache_dir: Path,
    daily_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows = []
    for symbol in names:
        outcome = _forward_outcome(
            symbol,
            signal_date,
            [signal_date, next_date],
            cache_dir=cache_dir,
            daily_frames=daily_frames,
            horizons=(1,),
        )
        if not outcome:
            continue
        rows.append({"symbol": symbol, "name": names.get(symbol, ""), "next_ret": outcome["next_ret"]})
    return pd.DataFrame(rows)


def _aggregate(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return _aggregate_window(
        frame,
        group_cols,
        ret_col="next_ret",
        high_col="next_high_ret",
        low_col="next_low_ret",
    )


def _aggregate_horizons(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    frames = []
    for horizon in FORWARD_HORIZONS:
        prefix = f"{horizon}d"
        ret_col = f"ret_{prefix}"
        high_col = f"high_{prefix}_ret"
        low_col = f"low_{prefix}_ret"
        if ret_col not in frame.columns:
            continue
        subset = frame.dropna(subset=[ret_col])
        if subset.empty:
            continue
        aggregated = _aggregate_window(
            subset,
            group_cols,
            ret_col=ret_col,
            high_col=high_col,
            low_col=low_col,
        )
        aggregated.insert(len(group_cols), "horizon", prefix)
        frames.append(aggregated)
    if not frames:
        return pd.DataFrame(columns=group_cols + ["horizon"] + _aggregate_metric_columns())
    return pd.concat(frames, ignore_index=True, sort=False)


def _aggregate_window(
    frame: pd.DataFrame,
    group_cols: list[str],
    *,
    ret_col: str,
    high_col: str,
    low_col: str,
) -> pd.DataFrame:
    columns = group_cols + [
        *_aggregate_metric_columns(),
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        frame.groupby(group_cols, dropna=False)
        .agg(
            count=("symbol", "count"),
            avg_ret=(ret_col, "mean"),
            median_ret=(ret_col, "median"),
            win_rate=(ret_col, lambda values: float((values > 0).mean())),
            gt5_rate=(ret_col, lambda values: float((values >= 0.05).mean())),
            lt_minus5_rate=(ret_col, lambda values: float((values <= -0.05).mean())),
            avg_high=(high_col, "mean"),
            avg_low=(low_col, "mean"),
            max_ret=(ret_col, "max"),
            min_ret=(ret_col, "min"),
        )
        .reset_index()
    )
    return grouped[columns]


def _aggregate_metric_columns() -> list[str]:
    return [
        "count",
        "avg_ret",
        "median_ret",
        "win_rate",
        "gt5_rate",
        "lt_minus5_rate",
        "avg_high",
        "avg_low",
        "max_ret",
        "min_ret",
    ]


def _portfolio_summary(details: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if details.empty:
        return pd.DataFrame(columns=["bucket", "top_n", "count_days", "avg_ret", "win_rate", "max_ret", "min_ret"])
    for (signal_date, next_date), frame in details.groupby(["signal_date", "next_date"]):
        for tiers, bucket in ((ACTION_TIERS, "A/A1/A2/A3/B/B1"), (CORE_TIERS, "核心含B2")):
            subset = frame[frame["tier"].isin(tiers)].sort_values("score", ascending=False)
            for top_n in (5, 10, 20):
                picked = subset.head(top_n)
                if picked.empty:
                    continue
                rows.append(
                    {
                        "signal_date": signal_date,
                        "next_date": next_date,
                        "bucket": bucket,
                        "top_n": top_n,
                        "avg_ret": picked["next_ret"].mean(),
                        "win_rate": float((picked["next_ret"] > 0).mean()),
                        "max_ret": picked["next_ret"].max(),
                        "min_ret": picked["next_ret"].min(),
                    }
                )
    raw = pd.DataFrame(rows)
    if raw.empty:
        return pd.DataFrame(columns=["bucket", "top_n", "count_days", "avg_ret", "win_rate", "max_ret", "min_ret"])
    return (
        raw.groupby(["bucket", "top_n"])
        .agg(
            count_days=("signal_date", "count"),
            avg_ret=("avg_ret", "mean"),
            win_rate=("win_rate", "mean"),
            max_ret=("max_ret", "max"),
            min_ret=("min_ret", "min"),
        )
        .reset_index()
        .sort_values(["bucket", "top_n"])
    )


def _markdown_table(frame: pd.DataFrame, *, percent_cols: list[str] | None = None) -> str:
    if frame.empty:
        return "无"
    percent_set = set(percent_cols or [])
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in frame.iterrows():
        values = []
        for column in frame.columns:
            value = row.get(column, "")
            if column in percent_set and pd.notna(value):
                values.append(f"{float(value) * 100:.2f}%")
            elif isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(_clean_text(value).replace("|", "/"))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _existing(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in frame.columns]


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "none"}:
        return ""
    return text


def _number(value: object, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return default
    return float(parsed)
