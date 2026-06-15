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
    theme_bonus_max: float = 8.0
    co_rise_bonus_max: float = 5.0
    risk_notice_penalty_per_hit: float = 5.0
    risk_notice_penalty_max: float = 20.0
    ret20_hot_threshold: float = 0.20
    ret20_extreme_threshold: float = 0.30
    volume_hot_threshold: float = 2.50
    volume_extreme_threshold: float = 4.00
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
    sentiment_frame = normalize_symbol_column(sentiment)

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
            "risk_notice_count",
            "cache_age_days",
        ],
    )
    for column in ["listing_date", "cache_first_date", "industry", "risk_notice_titles"]:
        output = _ensure_text_column(output, column)

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
        }
    ).fillna(0.0)
    output["volume_overheat_penalty"] = output["volume_ratio"].map(
        lambda value: _volume_overheat_penalty(value, config)
    )
    output["ret20_overheat_penalty"] = output["ret_20_pct"].map(
        lambda value: _ret20_overheat_penalty(value, config)
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
    output["research_tier"] = output["research_score"].map(_tier)

    return output.sort_values(
        ["research_score", "score", "sentiment_score"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def _ensure_numeric_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    output = frame.copy()
    for column in columns:
        if column not in output.columns:
            output[column] = 0.0
        output[column] = pd.to_numeric(output[column], errors="coerce").fillna(0.0)
    return output


def _ensure_text_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    output = frame.copy()
    if column not in output.columns:
        output[column] = ""
    output[column] = output[column].fillna("").astype(str)
    return output


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


def _tier(score: float) -> str:
    if score >= 65:
        return "A"
    if score >= 55:
        return "B"
    if score >= 45:
        return "C"
    return "观察"
