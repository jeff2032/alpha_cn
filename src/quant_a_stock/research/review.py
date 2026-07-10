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
FORWARD_HORIZONS = (1, 3, 5, 10, 15, 20, 30)
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
MODEL_BUCKET_ORDER = {
    "A1/A2_early_setup": 1,
    "A3_trend_follow": 2,
    "B2a_theme_spread": 3,
    "B_surge_replenish": 4,
    "B2b_theme_watch": 5,
    "B_watchlist": 6,
    "miss_learnable": 7,
    "miss_event_only": 8,
    "other": 9,
}
ACTION_BUCKET_ORDER = {
    "主攻-A2启动确认": 1,
    "主攻-A3趋势延续": 2,
    "观察-B2a主线扩散待升级": 3,
    "补票-B2a主线扩散": 3,
    "观察-B2s主线突发待确认": 4,
    "补票-主线突发": 4,
    "补票-B2强主题": 4,
    "观察-B2b主题待确认": 5,
    "观察-A1低位潜伏": 6,
    "观察-A3高波动": 7,
    "观察-B级候选": 8,
    "观察-低优先级": 9,
    "回避-风险优先": 9,
}
ACTION_BUCKETS = (
    "主攻-A2启动确认",
    "主攻-A3趋势延续",
    "观察-B2a主线扩散待升级",
    "观察-B2s主线突发待确认",
    "补票-B2a主线扩散",
    "补票-主线突发",
    "补票-B2强主题",
)


@dataclass(frozen=True)
class ResearchReview:
    snapshot_dates: list[str]
    closed_signal_dates: list[str]
    details: pd.DataFrame
    by_tier: pd.DataFrame
    by_tier_horizon: pd.DataFrame
    by_day_tier: pd.DataFrame
    by_model_bucket: pd.DataFrame
    by_model_bucket_horizon: pd.DataFrame
    by_action_bucket: pd.DataFrame
    by_action_bucket_horizon: pd.DataFrame
    by_stage: pd.DataFrame
    by_stage_horizon: pd.DataFrame
    loss_attribution: pd.DataFrame
    miss_learnability: pd.DataFrame
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
    benchmark_symbol: str = "510300",
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

        candidate_outcomes = {
            str(row["symbol"]): _forward_outcome(
                str(row["symbol"]),
                signal_date,
                trade_dates,
                cache_dir=cache_dir,
                daily_frames=daily_frames,
            )
            for _, row in candidates.iterrows()
        }
        benchmark_outcome = _forward_outcome(
            benchmark_symbol,
            signal_date,
            trade_dates,
            cache_dir=cache_dir,
            daily_frames=daily_frames,
        )
        industry_outcomes = _industry_peer_outcomes(candidates, candidate_outcomes)

        selected = candidates[candidates["research_tier"].isin(CORE_TIERS)].copy()
        for _, row in selected.iterrows():
            symbol = str(row["symbol"])
            outcome = candidate_outcomes.get(symbol)
            if not outcome:
                continue
            relative = _relative_outcome(
                outcome,
                benchmark=benchmark_outcome,
                industry=industry_outcomes.get(symbol),
            )
            outcome = {**outcome, **relative}
            action_bucket = _clean_text(row.get("action_bucket", "")) or _fallback_action_bucket(row["research_tier"])
            model_bucket = _model_bucket(row["research_tier"], action_bucket)
            preferred = _preferred_outcome(row["research_tier"], outcome)
            risk_tags = _merge_tags(_split_tags(row.get("risk_tags", "")), _candidate_risk_tags(row, outcome))
            risk_level = _merge_risk_level(row.get("risk_level", ""), _candidate_risk_level(risk_tags))
            detail_rows.append(
                {
                    "signal_date": signal_date,
                    "next_date": next_date,
                    "sample_type": "candidate",
                    "symbol": row["symbol"],
                    "name": row.get("name", "") or names.get(row["symbol"], ""),
                    "tier": row["research_tier"],
                    "model_bucket": model_bucket,
                    "action_bucket": action_bucket,
                    "evaluation_horizon": _evaluation_horizon(row["research_tier"]),
                    "preferred_horizon": preferred["horizon"],
                    "preferred_ret": preferred["ret"],
                    "preferred_high_ret": preferred["high_ret"],
                    "preferred_low_ret": preferred["low_ret"],
                    "preferred_benchmark_ret": _number(
                        outcome.get(f"benchmark_ret_{preferred['horizon']}", float("nan")), default=float("nan")
                    ),
                    "preferred_excess_ret": _number(
                        outcome.get(f"excess_ret_{preferred['horizon']}", float("nan")), default=float("nan")
                    ),
                    "preferred_industry_ret": _number(
                        outcome.get(f"industry_ret_{preferred['horizon']}", float("nan")), default=float("nan")
                    ),
                    "preferred_industry_excess_ret": _number(
                        outcome.get(f"industry_excess_ret_{preferred['horizon']}", float("nan")),
                        default=float("nan"),
                    ),
                    "outcome_label": _outcome_label(preferred),
                    "is_learnable": True,
                    "risk_level": risk_level,
                    "risk_tags": "；".join(risk_tags) if risk_tags else "无明显风险",
                    "primary_risk_tag": risk_tags[0] if risk_tags else "无明显风险",
                    "score": _number(row.get("research_score", row.get("score", 0.0))),
                    "setup_phase": row.get("setup_phase", ""),
                    "stage": row.get("stage", ""),
                    "industry": row.get("industry", ""),
                    "theme_cluster": row.get("theme_cluster", row.get("matched_theme", "")),
                    "benchmark_symbol": benchmark_symbol,
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
        if "action_bucket" in candidates.columns:
            action_symbols = set(candidates[candidates["action_bucket"].isin(ACTION_BUCKETS)]["symbol"])
        else:
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
                "benchmark_symbol": benchmark_symbol,
                "benchmark_next_ret": _number(
                    benchmark_outcome.get("next_ret"), default=float("nan")
                )
                if benchmark_outcome
                else float("nan"),
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
                    "sample_type": "miss",
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
    by_model_bucket = _aggregate(details, ["model_bucket"])
    if not by_model_bucket.empty:
        by_model_bucket["bucket_rank"] = by_model_bucket["model_bucket"].map(MODEL_BUCKET_ORDER).fillna(99)
        by_model_bucket = by_model_bucket.sort_values(["bucket_rank", "model_bucket"]).drop(columns=["bucket_rank"])

    by_model_bucket_horizon = _aggregate_horizons(details, ["model_bucket"])
    if not by_model_bucket_horizon.empty:
        by_model_bucket_horizon["bucket_rank"] = by_model_bucket_horizon["model_bucket"].map(MODEL_BUCKET_ORDER).fillna(99)
        by_model_bucket_horizon["horizon_rank"] = by_model_bucket_horizon["horizon"].str.replace("d", "").astype(int)
        by_model_bucket_horizon = by_model_bucket_horizon.sort_values(
            ["bucket_rank", "horizon_rank", "model_bucket"]
        ).drop(columns=["bucket_rank", "horizon_rank"])

    by_action_bucket = _aggregate(details, ["action_bucket"])
    if not by_action_bucket.empty:
        by_action_bucket["bucket_rank"] = by_action_bucket["action_bucket"].map(ACTION_BUCKET_ORDER).fillna(99)
        by_action_bucket = by_action_bucket.sort_values(["bucket_rank", "action_bucket"]).drop(columns=["bucket_rank"])

    by_action_bucket_horizon = _aggregate_horizons(details, ["action_bucket"])
    if not by_action_bucket_horizon.empty:
        by_action_bucket_horizon["bucket_rank"] = by_action_bucket_horizon["action_bucket"].map(ACTION_BUCKET_ORDER).fillna(99)
        by_action_bucket_horizon["horizon_rank"] = by_action_bucket_horizon["horizon"].str.replace("d", "").astype(int)
        by_action_bucket_horizon = by_action_bucket_horizon.sort_values(
            ["bucket_rank", "horizon_rank", "action_bucket"]
        ).drop(columns=["bucket_rank", "horizon_rank"])

    by_stage = _aggregate(details, ["stage"])
    by_stage_horizon = _aggregate_horizons(details, ["stage"])
    loss_attribution = _loss_attribution(details)
    portfolio = _portfolio_summary(details)
    market_capture = pd.DataFrame(capture_rows)
    missed_movers = pd.DataFrame(missed_rows)
    miss_learnability = _miss_learnability_summary(missed_movers)
    closed_dates = sorted(details["signal_date"].unique().tolist()) if not details.empty else []

    return ResearchReview(
        snapshot_dates=snapshot_dates,
        closed_signal_dates=closed_dates,
        details=details,
        by_tier=by_tier,
        by_tier_horizon=by_tier_horizon,
        by_day_tier=by_day_tier,
        by_model_bucket=by_model_bucket,
        by_model_bucket_horizon=by_model_bucket_horizon,
        by_action_bucket=by_action_bucket,
        by_action_bucket_horizon=by_action_bucket_horizon,
        by_stage=by_stage,
        by_stage_horizon=by_stage_horizon,
        loss_attribution=loss_attribution,
        miss_learnability=miss_learnability,
        portfolio=portfolio,
        market_capture=market_capture,
        missed_movers=missed_movers,
    )


def save_research_review_reports(review: ResearchReview, *, date_prefix: str | None = None) -> tuple[Path, Path, Path]:
    DEFAULT_PATHS.reports.mkdir(parents=True, exist_ok=True)
    if date_prefix:
        stamp = f"{date_prefix.replace('-', '')}_{datetime.now().strftime('%H%M%S')}"
    else:
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
        ("by_model_bucket", review.by_model_bucket),
        ("by_model_bucket_horizon", review.by_model_bucket_horizon),
        ("by_action_bucket", review.by_action_bucket),
        ("by_action_bucket_horizon", review.by_action_bucket_horizon),
        ("by_stage", review.by_stage),
        ("by_stage_horizon", review.by_stage_horizon),
        ("loss_attribution", review.loss_attribution),
        ("miss_learnability", review.miss_learnability),
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
        "- A2、A3、B2a/B2s/B2b 要分开评价：A2 看潜伏转强，A3 看趋势延续，B2a 看主线扩散后是否升级，B2s 看主线突发是否持续，B2b 看是否确认。",
        "- 如果 A3 和趋势回踩表现靠前，说明当前市场更奖励主线趋势；如果 A2/A1 短期滞后，要继续看 10/15/20/30 日窗口，避免误杀潜伏模型。",
        "- 市场强票捕获数偏低时，说明突发催化和 20cm 弹性没有被形态池提前覆盖，需要补“主线突发观察”，但不直接当买点。",
        "- 这版复盘同时看 1/3/5/10/15/20/30 个交易日：A3 看 1-10 日，A2 看 3-15 日，A1 看 10-30 日，B2a/B2b 重点看是否升级和兑现。",
        "- 基准超额默认相对 510300；行业超额使用信号日候选池内同一行业的其他标的等权收益，样本数不足时留空，不冒充完整行业指数。",
        "",
        "## 分层相对收益",
        "",
        _markdown_table(
            review.by_tier_horizon[
                _existing(
                    review.by_tier_horizon,
                    [
                        "tier",
                        "horizon",
                        "count",
                        "avg_ret",
                        "avg_benchmark_ret",
                        "avg_excess_ret",
                        "excess_win_rate",
                        "avg_industry_ret",
                        "avg_industry_excess_ret",
                    ],
                )
            ],
            percent_cols=[
                "avg_ret",
                "avg_benchmark_ret",
                "avg_excess_ret",
                "excess_win_rate",
                "avg_industry_ret",
                "avg_industry_excess_ret",
            ],
        ),
        "",
        "## 模型桶评价口径",
        "",
        "| model_bucket | 中文口径 | 评价窗口 | 用途 |",
        "| --- | --- | --- | --- |",
        "| A1/A2_early_setup | 早期潜伏/启动确认 | A1 看 10-30 日，A2 看 3-15 日 | 看是否从低位或临界突破转强 |",
        "| A3_trend_follow | 主线趋势延续 | 1-3 日 | 看主线强趋势是否延续，重点防追高 |",
        "| B2a_theme_spread | 主线扩散升级观察 | 1-10 日 | 看主题扩散后能否升级到主攻或兑现 |",
        "| B_surge_replenish | 主线突发待确认 | 1-5 日 | 反推明显 miss 的正常形态观察条件，不直接当买点 |",
        "| B2b_theme_watch | 主题待确认观察 | 1-5 日 | 看是否升级，不直接当买点 |",
        "| B_watchlist | 普通观察池 | 1-3 日 | 只评估是否值得升级，不直接当买点 |",
        "| miss_learnable | 可学习 miss | 1 日 | 反推突发主线观察条件 |",
        "| miss_event_only | 不可归因 miss | 1 日 | 复权、事件、低流动性、次新等剔除出策略归因 |",
        "",
        "## 模型桶多周期表现",
        "",
        _markdown_table(
            review.by_model_bucket_horizon,
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
        "## 模型桶首日表现",
        "",
        _markdown_table(
            review.by_model_bucket,
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
        "## 动作分组多周期表现",
        "",
        _markdown_table(
            review.by_action_bucket_horizon,
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
        "## 动作分组首日表现",
        "",
        _markdown_table(
            review.by_action_bucket,
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
        "## 分层多周期表现",
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
        "## 阶段多周期表现",
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
                        "action_bucket",
                        "score",
                        "setup_phase",
                        "stage",
                        "risk_level",
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
                        "action_bucket",
                        "score",
                        "setup_phase",
                        "stage",
                        "risk_level",
                        "risk_tags",
                        "next_ret",
                        "next_low_ret",
                    ],
                )
            ],
            percent_cols=["next_ret", "next_low_ret"],
        ),
        "",
        "## 亏损样本归因",
        "",
        _markdown_table(
            review.loss_attribution,
            percent_cols=["avg_preferred_ret", "min_preferred_ret", "avg_low_ret"],
        ),
        "",
        "## Miss 样本可学习性",
        "",
        _markdown_table(review.miss_learnability, percent_cols=["avg_next_ret"]),
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
                        "model_bucket",
                        "is_learnable",
                        "miss_reason",
                        "risk_level",
                        "risk_tags",
                        "primary_risk_tag",
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
        "- A2：用 3-15 日窗口复盘；A1 用 10-30 日窗口复盘，避免用次日涨跌误判潜伏票。",
        "- B2a：作为主线扩散升级观察池复盘；B2s：作为主线突发待确认池复盘；B2b：作为主题待确认观察池，不直接当作买点。",
        "- Miss：先剔除复权/除权/特殊事件疑似样本，再反推正常涨停票的主线观察条件。",
        "- 风险：所有升级观察样本先做公告、质押、减持、问询和流动性核验，不能只因次日大涨就追高。",
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


def _model_bucket(tier: object, action_bucket: object = "") -> str:
    value = str(tier)
    bucket = _clean_text(action_bucket)
    if value in {"A", "A1", "A2"}:
        return "A1/A2_early_setup"
    if value == "A3":
        return "A3_trend_follow"
    if "B2a" in bucket:
        return "B2a_theme_spread"
    if "主线突发" in bucket:
        return "B_surge_replenish"
    if "B2b" in bucket:
        return "B2b_theme_watch"
    if value in {"B", "B1", "B2"}:
        return "B_watchlist"
    return "other"


def _fallback_action_bucket(tier: object) -> str:
    value = str(tier)
    if value in {"A", "A2"}:
        return "主攻-A2启动确认"
    if value == "A3":
        return "主攻-A3趋势延续"
    if value == "A1":
        return "观察-A1低位潜伏"
    if value in {"B", "B1", "B2"}:
        return "观察-B级候选"
    return "观察-低优先级"


def _split_tags(value: object) -> list[str]:
    text = _clean_text(value)
    if not text or text == "无明显风险":
        return []
    return [item.strip() for item in text.split("；") if item.strip()]


def _merge_tags(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for item in group:
            if not item or item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _merge_risk_level(*levels: object) -> str:
    order = {"低": 1, "中": 2, "中高": 3, "高": 4}
    clean = [_clean_text(level) for level in levels if _clean_text(level)]
    if not clean:
        return "低"
    return max(clean, key=lambda level: order.get(level, 0))


def _evaluation_horizon(tier: object) -> str:
    value = str(tier)
    if value == "A1":
        return "10d_20d_30d"
    if value in {"A", "A2"}:
        return "3d_5d_10d_15d"
    if value == "A3":
        return "1d_3d_5d_10d"
    if value in {"B", "B1", "B2"}:
        return "observe_1d_3d_5d_10d"
    return "1d"


def _preferred_outcome(tier: object, outcome: dict) -> dict:
    value = str(tier)
    if value == "A1":
        horizons = (30, 20, 15, 10, 5, 3, 1)
    elif value in {"A", "A2"}:
        horizons = (15, 10, 5, 3, 1)
    elif value == "A3":
        horizons = (10, 5, 3, 1)
    elif value in {"B", "B1", "B2"}:
        horizons = (10, 5, 3, 1)
    else:
        horizons = (1,)
    for horizon in horizons:
        prefix = f"{horizon}d"
        ret_key = f"ret_{prefix}"
        if ret_key not in outcome:
            continue
        return {
            "horizon": prefix,
            "ret": _number(outcome.get(ret_key, 0.0)),
            "high_ret": _number(outcome.get(f"high_{prefix}_ret", 0.0)),
            "low_ret": _number(outcome.get(f"low_{prefix}_ret", 0.0)),
        }
    return {
        "horizon": "1d",
        "ret": _number(outcome.get("next_ret", 0.0)),
        "high_ret": _number(outcome.get("next_high_ret", 0.0)),
        "low_ret": _number(outcome.get("next_low_ret", 0.0)),
    }


def _outcome_label(preferred: dict) -> str:
    ret = _number(preferred.get("ret", 0.0))
    high_ret = _number(preferred.get("high_ret", 0.0))
    low_ret = _number(preferred.get("low_ret", 0.0))
    if ret >= 0.05:
        return "hit"
    if ret <= -0.05:
        return "loss"
    if high_ret >= 0.05 and ret <= 0:
        return "intraday_fade"
    if low_ret <= -0.05 and ret > 0:
        return "volatile_win"
    return "neutral"


def _candidate_risk_tags(row: pd.Series, outcome: dict) -> list[str]:
    tags: list[str] = []
    if _number(row.get("risk_notice_count", 0.0)) > 0:
        tags.append("公告风险命中")
    if _number(row.get("total_penalty", 0.0)) >= 15:
        tags.append("总扣分偏高")
    if _number(row.get("ret_20_pct", row.get("ret_20", 0.0))) >= 0.25:
        tags.append("前20日涨幅偏高")
    if _number(row.get("ret_60_pct", row.get("ret_60", 0.0))) >= 0.80:
        tags.append("60日涨幅过高")
    if _number(row.get("monthly_position_pct", 0.0)) >= 0.80:
        tags.append("月线位置偏高")
    if _number(row.get("price_position_120_pct", row.get("price_position_120", 0.0))) >= 0.85:
        tags.append("120日位置偏高")
    if _number(row.get("volume_ratio", 0.0)) >= 3.0:
        tags.append("放量过猛")
    amount_ma20 = _number(row.get("amount_ma20", 0.0))
    if amount_ma20 and amount_ma20 < 100_000_000:
        tags.append("成交额偏低")
    if _number(outcome.get("next_low_ret", 0.0)) <= -0.05:
        tags.append("次日回撤超5%")
    if _number(outcome.get("next_high_ret", 0.0)) >= 0.05 and _number(outcome.get("next_ret", 0.0)) <= 0:
        tags.append("冲高回落")
    return tags


def _candidate_risk_level(tags: list[str]) -> str:
    joined = "；".join(tags)
    if any(key in joined for key in ("公告风险", "成交额偏低", "次日回撤超5%")):
        return "高"
    if any(key in joined for key in ("总扣分偏高", "涨幅偏高", "位置偏高", "放量过猛", "冲高回落")):
        return "中高"
    if tags:
        return "中"
    return "低"


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
        "model_bucket": "miss_learnable",
        "evaluation_horizon": "1d",
        "is_learnable": True,
        "risk_level": "中",
        "risk_tags": "未做公告风险核验",
        "primary_risk_tag": "未做公告风险核验",
        "action_hint": "先补情绪和公告核验，再决定是否纳入补票观察。",
    }
    if context["scan_source"]:
        context["miss_reason"] = "形态入池但未进入最终候选"
    if frame.empty:
        context["risk_level"] = "高"
        context["risk_tags"] = "行情缓存缺失；未做公告风险核验"
        context["primary_risk_tag"] = "行情缓存缺失"
        context["model_bucket"] = "miss_event_only"
        context["is_learnable"] = False
        context["action_hint"] = "剔除出策略复盘，先修复数据。"
        return context

    history = frame[frame["_date"] <= signal_date].copy()
    target = frame[frame["_date"] == next_date]
    if history.empty or target.empty:
        context["risk_level"] = "高"
        context["risk_tags"] = "信号日或次日行情缺失；未做公告风险核验"
        context["primary_risk_tag"] = "信号日或次日行情缺失"
        context["model_bucket"] = "miss_event_only"
        context["is_learnable"] = False
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
    context["primary_risk_tag"] = risk_tags[0] if risk_tags else "无明显风险"
    context["action_hint"] = _miss_action_hint(
        risk_tags=risk_tags,
        scan_source=context["scan_source"],
    )
    context["is_learnable"] = _miss_is_learnable(risk_tags)
    context["model_bucket"] = "miss_learnable" if context["is_learnable"] else "miss_event_only"
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
        return "只做事件观察，不纳入常规升级观察池。"
    if scan_source:
        return "复核为何未进入最终候选，优先检查情绪、主题和风险扣分。"
    return "纳入主线突发观察池反推，但追高前必须补情绪和公告核验。"


def _miss_is_learnable(risk_tags: list[str]) -> bool:
    joined = "；".join(risk_tags)
    blocked = ("超常规涨跌幅", "成交额偏低", "次新", "行情缓存缺失", "行情缺失")
    return not any(tag in joined for tag in blocked)


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


def _industry_peer_outcomes(
    candidates: pd.DataFrame,
    outcomes: dict[str, dict | None],
) -> dict[str, dict[str, float | int]]:
    if "industry" not in candidates.columns:
        return {}
    working = candidates[["symbol", "industry"]].copy()
    working["industry"] = working["industry"].fillna("").astype(str).str.strip()
    working = working[working["industry"] != ""]
    result: dict[str, dict[str, float | int]] = {}
    for _, group in working.groupby("industry"):
        symbols = group["symbol"].astype(str).tolist()
        for symbol in symbols:
            peers = [outcomes.get(peer) for peer in symbols if peer != symbol and outcomes.get(peer)]
            values: dict[str, float | int] = {}
            for horizon in FORWARD_HORIZONS:
                key = f"ret_{horizon}d"
                returns = [_number(item.get(key), default=float("nan")) for item in peers if item and key in item]
                returns = [value for value in returns if not pd.isna(value)]
                if returns:
                    values[f"industry_ret_{horizon}d"] = float(pd.Series(returns).mean())
                    values[f"industry_peer_count_{horizon}d"] = len(returns)
            if values:
                values["industry_next_ret"] = values.get("industry_ret_1d", float("nan"))
                values["industry_peer_count"] = values.get("industry_peer_count_1d", 0)
                result[symbol] = values
    return result


def _relative_outcome(
    outcome: dict,
    *,
    benchmark: dict | None,
    industry: dict | None,
) -> dict[str, float | int]:
    result: dict[str, float | int] = {}
    for horizon in FORWARD_HORIZONS:
        suffix = f"{horizon}d"
        stock_key = f"ret_{suffix}"
        if stock_key not in outcome:
            continue
        stock_ret = _number(outcome.get(stock_key), default=float("nan"))
        if benchmark and stock_key in benchmark:
            benchmark_ret = _number(benchmark.get(stock_key), default=float("nan"))
            result[f"benchmark_ret_{suffix}"] = benchmark_ret
            result[f"excess_ret_{suffix}"] = stock_ret - benchmark_ret
        industry_key = f"industry_ret_{suffix}"
        if industry and industry_key in industry:
            industry_ret = _number(industry.get(industry_key), default=float("nan"))
            result[industry_key] = industry_ret
            result[f"industry_excess_ret_{suffix}"] = stock_ret - industry_ret
            result[f"industry_peer_count_{suffix}"] = int(industry.get(f"industry_peer_count_{suffix}", 0))
    result["benchmark_next_ret"] = result.get("benchmark_ret_1d", float("nan"))
    result["excess_next_ret"] = result.get("excess_ret_1d", float("nan"))
    result["industry_next_ret"] = result.get("industry_ret_1d", float("nan"))
    result["industry_excess_next_ret"] = result.get("industry_excess_ret_1d", float("nan"))
    result["industry_peer_count"] = result.get("industry_peer_count_1d", 0)
    return result


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
    suffix = "next" if ret_col == "next_ret" else ret_col.removeprefix("ret_")
    benchmark_col = "benchmark_next_ret" if suffix == "next" else f"benchmark_ret_{suffix}"
    excess_col = "excess_next_ret" if suffix == "next" else f"excess_ret_{suffix}"
    industry_col = "industry_next_ret" if suffix == "next" else f"industry_ret_{suffix}"
    industry_excess_col = (
        "industry_excess_next_ret" if suffix == "next" else f"industry_excess_ret_{suffix}"
    )
    working = frame.copy()
    for column in (benchmark_col, excess_col, industry_col, industry_excess_col):
        if column not in working.columns:
            working[column] = float("nan")
    grouped = (
        working.groupby(group_cols, dropna=False)
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
            avg_benchmark_ret=(benchmark_col, "mean"),
            avg_excess_ret=(excess_col, "mean"),
            excess_win_rate=(excess_col, lambda values: float((values.dropna() > 0).mean()) if values.notna().any() else float("nan")),
            avg_industry_ret=(industry_col, "mean"),
            avg_industry_excess_ret=(industry_excess_col, "mean"),
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
        "avg_benchmark_ret",
        "avg_excess_ret",
        "excess_win_rate",
        "avg_industry_ret",
        "avg_industry_excess_ret",
    ]


def _loss_attribution(details: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "model_bucket",
        "primary_risk_tag",
        "count",
        "avg_preferred_ret",
        "min_preferred_ret",
        "avg_low_ret",
        "loss_rate",
    ]
    if details.empty or "preferred_ret" not in details.columns:
        return pd.DataFrame(columns=columns)
    losses = details[details["preferred_ret"] <= -0.05].copy()
    if losses.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        losses.groupby(["model_bucket", "primary_risk_tag"], dropna=False)
        .agg(
            count=("symbol", "count"),
            avg_preferred_ret=("preferred_ret", "mean"),
            min_preferred_ret=("preferred_ret", "min"),
            avg_low_ret=("preferred_low_ret", "mean"),
        )
        .reset_index()
    )
    totals = details.groupby("model_bucket")["symbol"].count().to_dict()
    grouped["loss_rate"] = grouped.apply(
        lambda row: row["count"] / totals.get(row["model_bucket"], row["count"]),
        axis=1,
    )
    return grouped.sort_values(["count", "avg_preferred_ret"], ascending=[False, True])[columns]


def _miss_learnability_summary(missed: pd.DataFrame) -> pd.DataFrame:
    columns = ["model_bucket", "risk_level", "miss_reason", "count", "avg_next_ret"]
    if missed.empty:
        return pd.DataFrame(columns=columns)
    output = missed.copy()
    if "model_bucket" not in output.columns:
        output["model_bucket"] = "miss_learnable"
    if "risk_level" not in output.columns:
        output["risk_level"] = ""
    if "miss_reason" not in output.columns:
        output["miss_reason"] = ""
    grouped = (
        output.groupby(["model_bucket", "risk_level", "miss_reason"], dropna=False)
        .agg(
            count=("symbol", "count"),
            avg_next_ret=("next_ret", "mean"),
        )
        .reset_index()
    )
    grouped["bucket_rank"] = grouped["model_bucket"].map(MODEL_BUCKET_ORDER).fillna(99)
    return grouped.sort_values(["bucket_rank", "count"], ascending=[True, False]).drop(columns=["bucket_rank"])[columns]


def _portfolio_summary(details: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if details.empty:
        return pd.DataFrame(columns=["bucket", "top_n", "count_days", "avg_ret", "win_rate", "max_ret", "min_ret"])
    for (signal_date, next_date), frame in details.groupby(["signal_date", "next_date"]):
        if "action_bucket" in frame.columns:
            for buckets, bucket in (
                (("主攻-A2启动确认", "主攻-A3趋势延续"), "主攻池"),
                (
                    (
                        "主攻-A2启动确认",
                        "主攻-A3趋势延续",
                        "观察-B2a主线扩散待升级",
                        "观察-B2s主线突发待确认",
                        "补票-B2a主线扩散",
                        "补票-主线突发",
                        "补票-B2强主题",
                    ),
                    "主攻+B2升级观察",
                ),
                (("观察-A1低位潜伏", "观察-A3高波动", "观察-B2b主题待确认", "观察-B级候选"), "观察池"),
            ):
                subset = frame[frame["action_bucket"].isin(buckets)].sort_values("score", ascending=False)
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
