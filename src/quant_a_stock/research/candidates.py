from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_a_stock.data.cache import daily_cache_path
from quant_a_stock.data.universe import normalize_symbol


RISK_NOTICE_KEYWORDS = [
    "处罚",
    "监管函",
    "问询",
    "立案",
    "调查",
    "诉讼",
    "仲裁",
    "减持",
    "质押",
    "冻结",
    "违规",
    "风险警示",
    "退市",
    "预亏",
    "亏损",
    "更正",
    "会计差错",
    "保留意见",
    "非标",
    "担保逾期",
]


@dataclass(frozen=True)
class ResearchCandidateConfig:
    shape_weight: float = 0.65
    sentiment_weight: float = 0.35
    accumulation_bonus: float = 3.0
    pre_breakout_bonus: float = 1.0
    near_breakout_bonus: float = 2.0
    breakout_bonus: float = 1.0
    trend_pullback_bonus: float = 1.5
    trend_resume_bonus: float = 2.5
    theme_bonus_max: float = 8.0
    co_rise_bonus_max: float = 5.0
    risk_notice_penalty_per_hit: float = 5.0
    risk_notice_penalty_max: float = 20.0
    ret20_hot_threshold: float = 0.15
    ret20_extreme_threshold: float = 0.30
    volume_hot_threshold: float = 2.20
    volume_extreme_threshold: float = 4.00
    monthly_high_position_threshold: float = 0.70
    price_high_position_threshold: float = 0.78
    new_stock_days: int = 250
    recent_stock_days: int = 500


def normalize_symbol_column(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if "symbol" not in output.columns:
        if "代码" in output.columns:
            output = output.rename(columns={"代码": "symbol"})
        else:
            raise ValueError("数据缺少 symbol/代码 列")
    output["symbol"] = output["symbol"].map(normalize_symbol)
    return output


def load_report(path: Path) -> pd.DataFrame:
    return normalize_symbol_column(pd.read_csv(path, dtype={"symbol": str, "代码": str}))


def load_cache_listing_info(symbols: list[str], *, target_date: str | None = None) -> pd.DataFrame:
    target = pd.Timestamp(target_date).normalize() if target_date else pd.Timestamp.now().normalize()
    rows = []
    for symbol in symbols:
        code = normalize_symbol(symbol)
        path = daily_cache_path(code)
        if not path.exists():
            rows.append({"symbol": code, "cache_bars": 0, "cache_first_date": ""})
            continue
        frame = pd.read_csv(path, usecols=["timestamp"])
        timestamps = pd.to_datetime(frame["timestamp"], errors="coerce").dropna()
        if timestamps.empty:
            rows.append({"symbol": code, "cache_bars": 0, "cache_first_date": ""})
            continue
        first_date = timestamps.min().normalize()
        rows.append(
            {
                "symbol": code,
                "cache_bars": int(len(timestamps)),
                "cache_first_date": first_date.date().isoformat(),
                "cache_age_days": int((target - first_date).days + 1),
            }
        )
    return pd.DataFrame(rows)


def fetch_company_profiles(symbols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    import akshare as ak

    rows = []
    errors: list[str] = []
    for symbol in symbols:
        code = normalize_symbol(symbol)
        try:
            frame = ak.stock_profile_cninfo(symbol=code)
        except Exception as exc:  # pragma: no cover - depends on provider/network state
            errors.append(f"{code} 公司资料: {type(exc).__name__}: {exc}")
            continue
        if frame.empty:
            rows.append({"symbol": code, "industry": "", "listing_date": ""})
            continue
        item = frame.iloc[0]
        rows.append(
            {
                "symbol": code,
                "industry": str(item.get("所属行业", "")),
                "listing_date": _date_text(item.get("上市日期", "")),
            }
        )
    return pd.DataFrame(rows), errors


def fetch_risk_notices(
    symbols: list[str],
    *,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, list[str]]:
    import akshare as ak

    rows = []
    errors: list[str] = []
    for symbol in symbols:
        code = normalize_symbol(symbol)
        try:
            frame = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=code,
                market="沪深京",
                keyword="",
                category="",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
        except Exception as exc:  # pragma: no cover - depends on provider/network state
            errors.append(f"{code} 公告: {type(exc).__name__}: {exc}")
            rows.append({"symbol": code, "risk_notice_count": 0, "risk_notice_titles": ""})
            continue

        titles = []
        if not frame.empty and "公告标题" in frame.columns:
            for title in frame["公告标题"].fillna("").astype(str):
                if any(keyword in title for keyword in RISK_NOTICE_KEYWORDS):
                    titles.append(title)
        rows.append(
            {
                "symbol": code,
                "risk_notice_count": len(titles),
                "risk_notice_titles": "；".join(titles[:5]),
            }
        )
    return pd.DataFrame(rows), errors


def build_research_candidates(
    scan: pd.DataFrame,
    sentiment: pd.DataFrame,
    *,
    theme: pd.DataFrame | None = None,
    profiles: pd.DataFrame | None = None,
    cache_info: pd.DataFrame | None = None,
    risk_notices: pd.DataFrame | None = None,
    target_date: str | None = None,
    config: ResearchCandidateConfig = ResearchCandidateConfig(),
) -> pd.DataFrame:
    scan_frame = normalize_symbol_column(scan)
    scan_frame = scan_frame[scan_frame["symbol"].map(_is_stock_like_symbol)].copy()
    sentiment_frame = normalize_symbol_column(sentiment)
    sentiment_frame = sentiment_frame[sentiment_frame["symbol"].map(_is_stock_like_symbol)].copy()

    if "name" not in sentiment_frame.columns and "名称" in sentiment_frame.columns:
        sentiment_frame = sentiment_frame.rename(columns={"名称": "name"})
    if "name" not in sentiment_frame.columns:
        sentiment_frame["name"] = ""

    output = scan_frame.merge(
        sentiment_frame,
        on="symbol",
        how="left",
        suffixes=("", "_sentiment"),
    )

    if "name" not in output.columns:
        output["name"] = output.get("name_sentiment", "")
    output["name"] = output["name"].fillna(output.get("name_sentiment", "")).fillna("")

    for frame in (profiles, cache_info, risk_notices):
        if frame is not None and not frame.empty:
            output = output.merge(normalize_symbol_column(frame), on="symbol", how="left")

    output = _ensure_numeric_columns(
        output,
        [
            "score",
            "sentiment_score",
            "volume_ratio",
            "ret_20_pct",
            "amount_ma20",
            "trend_slope_20_pct",
            "distance_to_high_pct",
            "price_position_pct",
            "monthly_position_pct",
            "weekly_trend_slope_pct",
            "close_vs_trend_pct",
            "close_vs_cost_pct",
            "ret_60_pct",
            "ret_120_pct",
            "ret_5_pct",
            "mtf_score",
            "daily_score",
            "weekly_score",
            "monthly_score",
            "early_trigger_score",
            "trend_score",
            "pullback_score",
            "resume_score",
            "close_vs_fast_pct",
            "fast_slope_10_pct",
            "drawdown_from_high_pct",
            "pullback_depth_pct",
            "range_position_60_pct",
            "risk_notice_count",
            "cache_age_days",
        ],
    )
    for column in [
        "listing_date",
        "cache_first_date",
        "industry",
        "risk_notice_titles",
        "stage",
        "setup_phase",
        "scan_source",
    ]:
        output = _ensure_text_column(output, column)
    output["setup_phase"] = output.apply(_fill_setup_phase, axis=1)

    target = _target_date_from_frame(output, target_date)
    output["listing_date_final"] = output.apply(
        lambda row: row["listing_date"] or row["cache_first_date"],
        axis=1,
    )
    output["listing_days"] = output["listing_date_final"].map(
        lambda value: _days_since(value, target)
    )
    output["listing_source"] = output.apply(
        lambda row: "cninfo" if row["listing_date"] else ("cache" if row["cache_first_date"] else ""),
        axis=1,
    )
    output["age_bucket"] = output["listing_days"].map(lambda days: _age_bucket(days, config))

    top_themes = _top_themes(theme)
    matches = output.apply(lambda row: _match_theme(row, top_themes), axis=1)
    output["matched_theme"] = [item[0] for item in matches]
    output["theme_rank"] = [item[1] for item in matches]
    output["theme_bonus"] = output["theme_rank"].map(lambda rank: _theme_bonus(rank, config))

    output["industry_candidate_count"] = _group_count(output["industry"])
    output["theme_candidate_count"] = _group_count(output["matched_theme"])
    output["co_rise_count"] = output[["industry_candidate_count", "theme_candidate_count"]].max(axis=1)
    output["co_rise_bonus"] = output["co_rise_count"].map(
        lambda count: min(config.co_rise_bonus_max, max(0, count - 1) * 1.5)
    )

    output["stage_bonus"] = output["stage"].map(
        {
            "accumulation": config.accumulation_bonus,
            "pre_breakout": config.pre_breakout_bonus,
            "near_breakout": config.near_breakout_bonus,
            "breakout": config.breakout_bonus,
            "trend_pullback": config.trend_pullback_bonus,
            "trend_resume": config.trend_resume_bonus,
        }
    ).fillna(0.0)
    output["volume_overheat_penalty"] = output["volume_ratio"].map(
        lambda value: _volume_overheat_penalty(value, config)
    )
    output["ret20_overheat_penalty"] = output["ret_20_pct"].map(
        lambda value: _ret20_overheat_penalty(value, config)
    )
    output["combined_overheat_penalty"] = output.apply(
        lambda row: _combined_overheat_penalty(row["ret_20_pct"], row["volume_ratio"]),
        axis=1,
    )
    output["position_overhead_penalty"] = output.apply(
        lambda row: _position_overhead_penalty(row, config),
        axis=1,
    )
    output["new_stock_penalty"] = output["listing_days"].map(
        lambda days: 5.0 if days and days < config.new_stock_days else 0.0
    )
    output["risk_notice_penalty"] = output["risk_notice_count"].map(
        lambda count: min(config.risk_notice_penalty_max, count * config.risk_notice_penalty_per_hit)
    )
    output["total_penalty"] = (
        output["volume_overheat_penalty"]
        + output["ret20_overheat_penalty"]
        + output["combined_overheat_penalty"]
        + output["position_overhead_penalty"]
        + output["new_stock_penalty"]
        + output["risk_notice_penalty"]
    )
    output["research_score"] = (
        output["score"] * config.shape_weight
        + output["sentiment_score"] * config.sentiment_weight
        + output["stage_bonus"]
        + output["theme_bonus"]
        + output["co_rise_bonus"]
        - output["total_penalty"]
    ).clip(lower=0, upper=100).round(2)
    output["research_tier"] = output.apply(_tier, axis=1)
    output["research_tier_rank"] = output["research_tier"].map(_tier_rank)
    output["risk_tags"] = output.apply(lambda row: "；".join(_risk_tags(row, config)), axis=1)
    output["risk_level"] = output.apply(lambda row: _risk_level(row, config), axis=1)
    output["is_risk_clean"] = output["risk_level"].isin(["低", "中"]) & (output["total_penalty"] <= 10)
    output["is_strong_theme_candidate"] = output.apply(_is_strong_theme_candidate, axis=1)
    output["action_bucket"] = output.apply(_action_bucket, axis=1)
    output["action_rank"] = output["action_bucket"].map(_action_rank)
    output["upgrade_hint"] = output.apply(_upgrade_hint, axis=1)

    return output.sort_values(
        ["action_rank", "research_tier_rank", "research_score", "score", "sentiment_score"],
        ascending=[True, True, False, False, False],
    ).reset_index(drop=True)


def _ensure_numeric_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    output = frame.copy()
    for column in columns:
        if column not in output.columns:
            output[column] = 0.0
        output[column] = pd.to_numeric(output[column], errors="coerce").fillna(0.0)
    return output


def _is_stock_like_symbol(symbol: str) -> bool:
    code = normalize_symbol(symbol)
    return code.startswith(
        (
            "000",
            "001",
            "002",
            "003",
            "300",
            "301",
            "600",
            "601",
            "603",
            "605",
            "688",
            "689",
            "4",
            "8",
        )
    )


def _ensure_text_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    output = frame.copy()
    if column not in output.columns:
        output[column] = ""
    output[column] = output[column].fillna("").astype(str)
    output[column] = output[column].replace({"nan": "", "NaN": "", "None": ""})
    return output


def _fill_setup_phase(row: pd.Series) -> str:
    phase = str(row.get("setup_phase", "") or "").strip()
    if phase:
        return phase
    stage = str(row.get("stage", "") or "")
    if stage == "near_breakout":
        return "接近突破确认"
    if stage == "breakout":
        return "突破确认"
    if stage == "watch":
        return "突破观察"
    if stage == "pre_breakout":
        return "接近突破确认"
    if stage == "trend_pullback":
        return "强趋势回踩"
    if stage == "trend_resume":
        return "强趋势再启动"
    return ""


def _target_date_from_frame(frame: pd.DataFrame, target_date: str | None) -> pd.Timestamp:
    if target_date:
        return pd.Timestamp(target_date).normalize()
    if "timestamp" in frame.columns and frame["timestamp"].notna().any():
        return pd.to_datetime(frame["timestamp"], errors="coerce").dropna().max().normalize()
    return pd.Timestamp.now().normalize()


def _top_themes(theme: pd.DataFrame | None, limit: int = 10) -> list[str]:
    if theme is None or theme.empty or "theme" not in theme.columns:
        return []
    return theme.sort_values("theme_score", ascending=False).head(limit)["theme"].astype(str).tolist()


def _match_theme(row: pd.Series, themes: list[str]) -> tuple[str, int]:
    text = " ".join(
        [
            str(row.get("industry", "")),
            str(row.get("top_keywords", "")),
            str(row.get("latest_core_news", "")),
            str(row.get("latest_news", "")),
            str(row.get("latest_report", "")),
            str(row.get("name", "")),
        ]
    )
    for index, theme in enumerate(themes, start=1):
        if theme and theme in text:
            return theme, index
    return "", 0


def _theme_bonus(rank: int, config: ResearchCandidateConfig) -> float:
    if rank <= 0:
        return 0.0
    return round(max(2.0, config.theme_bonus_max - (rank - 1) * 0.75), 2)


def _group_count(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str)
    counts = values[values != ""].value_counts()
    return values.map(counts).fillna(0).astype(int)


def _volume_overheat_penalty(value: float, config: ResearchCandidateConfig) -> float:
    if value >= config.volume_extreme_threshold:
        return 8.0
    if value >= config.volume_hot_threshold:
        return 3.0
    return 0.0


def _ret20_overheat_penalty(value: float, config: ResearchCandidateConfig) -> float:
    if value >= config.ret20_extreme_threshold:
        return 10.0
    if value >= config.ret20_hot_threshold:
        return 5.0
    return 0.0


def _combined_overheat_penalty(ret20: float, volume_ratio: float) -> float:
    if ret20 > 0.20 and volume_ratio > 2.50:
        return 8.0
    if ret20 > 0.15 and volume_ratio > 2.20:
        return 4.0
    return 0.0


def _position_overhead_penalty(row: pd.Series, config: ResearchCandidateConfig) -> float:
    penalty = 0.0
    monthly_position = float(row.get("monthly_position_pct", 0.0) or 0.0)
    price_position = float(row.get("price_position_pct", 0.0) or 0.0)
    if monthly_position > config.monthly_high_position_threshold:
        penalty += min(8.0, (monthly_position - config.monthly_high_position_threshold) / 0.18 * 8)
    if price_position > config.price_high_position_threshold:
        penalty += min(6.0, (price_position - config.price_high_position_threshold) / 0.16 * 6)
    return round(penalty, 2)


def _has_mainline_confirmation(row: pd.Series) -> bool:
    return bool(str(row.get("matched_theme", "") or "").strip()) or int(
        _safe_number(row.get("co_rise_count", 0))
    ) >= 2


def _has_any_confirmation(row: pd.Series) -> bool:
    return _has_mainline_confirmation(row) or int(_safe_number(row.get("core_news_count", 0))) > 0


def _is_early_accumulation(row: pd.Series) -> bool:
    if str(row.get("stage", "")) != "accumulation":
        return False
    price_position = _safe_number(row.get("price_position_pct", 0.0))
    ret20 = _safe_number(row.get("ret_20_pct", 0.0))
    volume_ratio = _safe_number(row.get("volume_ratio", 0.0))
    return 0.35 <= price_position <= 0.72 and ret20 <= 0.16 and volume_ratio <= 2.25


def _is_launch_confirmation(row: pd.Series) -> bool:
    stage = str(row.get("stage", ""))
    phase = str(row.get("setup_phase", "") or "")
    return stage in {"pre_breakout", "near_breakout", "breakout"} or phase in {
        "接近突破确认",
        "周线右侧启动",
        "日线触发观察",
    }


def _is_trend_pullback(row: pd.Series) -> bool:
    stage = str(row.get("stage", ""))
    ret60 = _safe_number(row.get("ret_60_pct", 0.0))
    ret20 = _safe_number(row.get("ret_20_pct", 0.0))
    drawdown = _safe_number(row.get("drawdown_from_high_pct", 0.0))
    close_vs_trend = _safe_number(row.get("close_vs_trend_pct", 0.0))
    volume_ratio = _safe_number(row.get("volume_ratio", 0.0))
    return (
        stage in {"trend_pullback", "trend_resume"}
        and ret60 >= 0.18
        and ret20 <= 0.24
        and drawdown >= -0.35
        and close_vs_trend <= 0.70
        and volume_ratio <= 3.30
    )


def _tier(row: pd.Series) -> str:
    score = _safe_number(row.get("research_score", 0.0))
    total_penalty = _safe_number(row.get("total_penalty", 0.0))
    ret20 = _safe_number(row.get("ret_20_pct", 0.0))

    early = _is_early_accumulation(row)
    launch = _is_launch_confirmation(row)
    trend_pullback = _is_trend_pullback(row)
    mainline_confirmed = _has_mainline_confirmation(row)
    any_confirmed = _has_any_confirmation(row)

    if score >= 60 and early and mainline_confirmed and total_penalty <= 8:
        return "A1"
    if score >= 60 and launch and any_confirmed and ret20 <= 0.24 and total_penalty <= 10:
        return "A2"
    if score >= 60 and trend_pullback and any_confirmed and total_penalty <= 10:
        return "A3"
    if score >= 55 and total_penalty <= 10:
        return "B1"
    if score >= 50:
        return "B2"
    if score >= 45:
        return "C"
    return "观察"


def _tier_rank(tier: str) -> int:
    return {
        "A1": 1,
        "A2": 2,
        "A3": 3,
        "B1": 4,
        "B2": 5,
        "C": 6,
        "观察": 7,
    }.get(tier, 9)


def _risk_tags(row: pd.Series, config: ResearchCandidateConfig) -> list[str]:
    tags: list[str] = []
    risk_count = _safe_number(row.get("risk_notice_count", 0.0))
    total_penalty = _safe_number(row.get("total_penalty", 0.0))
    ret20 = _safe_number(row.get("ret_20_pct", 0.0))
    volume_ratio = _safe_number(row.get("volume_ratio", 0.0))
    monthly_position = _safe_number(row.get("monthly_position_pct", 0.0))
    price_position = _safe_number(row.get("price_position_pct", 0.0))
    amount_ma20 = _safe_number(row.get("amount_ma20", 0.0))
    listing_days = _safe_number(row.get("listing_days", 0.0))

    if risk_count >= 2:
        tags.append("公告风险多项命中")
    elif risk_count >= 1:
        tags.append("公告风险命中")
    if total_penalty >= 15:
        tags.append("总扣分偏高")
    if ret20 >= config.ret20_extreme_threshold:
        tags.append("20日涨幅过热")
    elif ret20 >= config.ret20_hot_threshold:
        tags.append("20日涨幅偏热")
    if volume_ratio >= config.volume_extreme_threshold:
        tags.append("量能极端放大")
    elif volume_ratio >= config.volume_hot_threshold:
        tags.append("量能偏热")
    if _safe_number(row.get("combined_overheat_penalty", 0.0)) > 0:
        tags.append("量价共振过热")
    if monthly_position > config.monthly_high_position_threshold:
        tags.append("月线位置偏高")
    if price_position > config.price_high_position_threshold:
        tags.append("区间位置偏高")
    if listing_days and listing_days < config.new_stock_days:
        tags.append("次新样本不足")
    if amount_ma20 and amount_ma20 < 100_000_000:
        tags.append("成交额偏低")
    return tags


def _risk_level(row: pd.Series, config: ResearchCandidateConfig) -> str:
    tags = _risk_tags(row, config)
    joined = "；".join(tags)
    if any(key in joined for key in ("公告风险多项命中", "次新样本不足", "成交额偏低")):
        return "高"
    if any(key in joined for key in ("公告风险命中", "总扣分偏高", "20日涨幅过热", "量能极端放大")):
        return "中高"
    if any(key in joined for key in ("偏热", "位置偏高", "量价共振过热")):
        return "中"
    return "低"


def _is_risk_clean(row: pd.Series) -> bool:
    return str(row.get("risk_level", "")) in {"低", "中"} and _safe_number(row.get("total_penalty", 0.0)) <= 10


def _is_strong_theme_candidate(row: pd.Series) -> bool:
    matched_theme = bool(str(row.get("matched_theme", "") or "").strip())
    co_rise_count = _safe_number(row.get("co_rise_count", 0.0))
    core_news_count = _safe_number(row.get("core_news_count", 0.0))
    research_report_count = _safe_number(row.get("research_report_count", 0.0))
    sentiment_score = _safe_number(row.get("sentiment_score", 0.0))
    return matched_theme or co_rise_count >= 20 or core_news_count > 0 or research_report_count >= 2 or sentiment_score >= 70


def _is_b2_upgrade_watch(row: pd.Series) -> bool:
    tier = str(row.get("research_tier", ""))
    if tier not in {"B1", "B2"}:
        return False
    if not _is_risk_clean(row):
        return False
    stage = str(row.get("stage", "") or "")
    ret20 = _safe_number(row.get("ret_20_pct", 0.0))
    volume_ratio = _safe_number(row.get("volume_ratio", 0.0))
    amount_ma20 = _safe_number(row.get("amount_ma20", 0.0))
    return (
        _is_strong_theme_candidate(row)
        and stage in {"near_breakout", "breakout", "trend_pullback", "trend_resume", "pre_breakout"}
        and ret20 <= 0.25
        and volume_ratio <= 3.0
        and (amount_ma20 == 0 or amount_ma20 >= 100_000_000)
    )


def _action_bucket(row: pd.Series) -> str:
    tier = str(row.get("research_tier", ""))
    risk_level = str(row.get("risk_level", ""))
    total_penalty = _safe_number(row.get("total_penalty", 0.0))
    if risk_level == "高" or total_penalty >= 18:
        return "回避-风险优先"
    if tier == "A2" and _is_risk_clean(row):
        return "主攻-A2启动确认"
    if tier == "A3" and _is_risk_clean(row):
        return "主攻-A3趋势延续"
    if _is_b2_upgrade_watch(row):
        return "补票-B2强主题"
    if tier == "A1":
        return "观察-A1低位潜伏"
    if tier == "A3":
        return "观察-A3高波动"
    if tier in {"B1", "B2"}:
        return "观察-B级候选"
    return "观察-低优先级"


def _action_rank(bucket: str) -> int:
    return {
        "主攻-A2启动确认": 1,
        "主攻-A3趋势延续": 2,
        "补票-B2强主题": 3,
        "观察-A1低位潜伏": 4,
        "观察-A3高波动": 5,
        "观察-B级候选": 6,
        "观察-低优先级": 7,
        "回避-风险优先": 8,
    }.get(str(bucket), 9)


def _upgrade_hint(row: pd.Series) -> str:
    bucket = str(row.get("action_bucket", ""))
    risk_tags = str(row.get("risk_tags", "") or "无明显风险")
    if bucket == "主攻-A2启动确认":
        return "启动确认主攻：看突破后承接、回踩不破和量能不过热。"
    if bucket == "主攻-A3趋势延续":
        return "趋势主攻：只看分歧低吸或强承接，不追高开加速。"
    if bucket == "补票-B2强主题":
        return "强主题补票：先补公告和盘中承接核验，符合再升级。"
    if bucket == "观察-A1低位潜伏":
        return "低位潜伏观察：等主题、量能和短线资金进一步确认。"
    if bucket == "观察-A3高波动":
        return "趋势高波动观察：先处理过热/高位风险，再考虑低吸。"
    if bucket == "回避-风险优先":
        return f"风险优先回避：{risk_tags}。"
    return "观察为主：等待主线、量能或情绪进一步确认。"


def _safe_number(value: object, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return default
    return float(parsed)


def _age_bucket(days: int, config: ResearchCandidateConfig) -> str:
    if days <= 0:
        return ""
    if days < config.new_stock_days:
        return "次新"
    if days < config.recent_stock_days:
        return "近端上市"
    return "成熟样本"


def _days_since(value: str, target: pd.Timestamp) -> int:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return 0
    return int((target - parsed.normalize()).days + 1)


def _date_text(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.date().isoformat()
