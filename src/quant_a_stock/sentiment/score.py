from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_a_stock.data.universe import normalize_symbol
from quant_a_stock.sentiment.provider import fetch_hot_keywords
from quant_a_stock.sentiment.provider import fetch_hot_rank
from quant_a_stock.sentiment.provider import fetch_hot_rank_latest
from quant_a_stock.sentiment.provider import fetch_limit_pool
from quant_a_stock.sentiment.provider import fetch_research_reports
from quant_a_stock.sentiment.provider import fetch_stock_news
from quant_a_stock.sentiment.provider import fetch_strong_pool


POSITIVE_KEYWORDS = [
    "涨停",
    "突破",
    "创新高",
    "订单",
    "中标",
    "增持",
    "回购",
    "盈利",
    "业绩增长",
    "超预期",
    "机构调研",
    "龙头",
    "国产替代",
]

RISK_KEYWORDS = [
    "减持",
    "亏损",
    "立案",
    "处罚",
    "问询",
    "监管",
    "退市",
    "诉讼",
    "质押",
    "解禁",
    "风险",
]


@dataclass(frozen=True)
class SentimentConfig:
    news_days: int = 7
    research_days: int = 90
    hot_rank_top: int = 500
    target_date: str | None = None


def latest_weekday(value: str | None = None) -> pd.Timestamp:
    day = pd.Timestamp(value).normalize() if value else pd.Timestamp.now().normalize()
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)
    return day


def load_symbols_from_watchlist(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": str, "代码": str})
    if "symbol" not in frame.columns:
        if "代码" in frame.columns:
            frame = frame.rename(columns={"代码": "symbol"})
        else:
            raise ValueError(f"观察池文件缺少 symbol/代码 列: {path}")
    if "name" not in frame.columns and "名称" in frame.columns:
        frame = frame.rename(columns={"名称": "name"})
    if "name" not in frame.columns:
        frame["name"] = ""
    frame["symbol"] = frame["symbol"].map(normalize_symbol)
    return frame.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)


def _count_keywords(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _score_from_hot_rank(rank: int | None, top: int) -> float:
    if rank is None or rank <= 0:
        return 0.0
    if rank > top:
        return 0.0
    return max(0.0, (top - rank + 1) / top * 30)


def _score_from_count(count: int, scale: int, max_score: float) -> float:
    if count <= 0:
        return 0.0
    return min(max_score, count / scale * max_score)


def _to_date(value) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.normalize()


def _recent_news_stats(
    news: pd.DataFrame,
    *,
    symbol: str,
    name: str,
    target_date: pd.Timestamp,
    days: int,
) -> dict:
    if news.empty or "发布时间" not in news.columns:
        return {
            "news_count": 0,
            "core_news_count": 0,
            "generic_news_count": 0,
            "positive_hits": 0,
            "risk_hits": 0,
            "core_positive_hits": 0,
            "core_risk_hits": 0,
            "latest_news": "",
            "latest_core_news": "",
        }

    frame = news.copy()
    frame["date"] = pd.to_datetime(frame["发布时间"], errors="coerce").dt.normalize()
    start_date = target_date - pd.Timedelta(days=days)
    frame = frame[(frame["date"] >= start_date) & (frame["date"] <= target_date)]
    if frame.empty:
        return {
            "news_count": 0,
            "core_news_count": 0,
            "generic_news_count": 0,
            "positive_hits": 0,
            "risk_hits": 0,
            "core_positive_hits": 0,
            "core_risk_hits": 0,
            "latest_news": "",
            "latest_core_news": "",
        }

    title = frame.get("新闻标题", pd.Series(dtype=str)).fillna("").astype(str)
    name_text = str(name).strip()
    symbol_text = normalize_symbol(symbol)
    core_mask = title.str.contains(symbol_text, regex=False)
    if name_text:
        core_mask = core_mask | title.str.contains(name_text, regex=False)

    text = (
        title
        + " "
        + frame.get("新闻内容", pd.Series(dtype=str)).fillna("").astype(str)
    )
    combined = " ".join(text.tolist())
    core_titles = title[core_mask]
    core_combined = " ".join(title[core_mask].tolist())
    latest_title = str(frame.sort_values("date", ascending=False).iloc[0].get("新闻标题", ""))
    latest_core_title = str(core_titles.iloc[0]) if not core_titles.empty else ""
    return {
        "news_count": int(len(frame)),
        "core_news_count": int(core_mask.sum()),
        "generic_news_count": int((~core_mask).sum()),
        "positive_hits": _count_keywords(combined, POSITIVE_KEYWORDS),
        "risk_hits": _count_keywords(combined, RISK_KEYWORDS),
        "core_positive_hits": _count_keywords(core_combined, POSITIVE_KEYWORDS),
        "core_risk_hits": _count_keywords(core_combined, RISK_KEYWORDS),
        "latest_news": latest_title[:80],
        "latest_core_news": latest_core_title[:80],
    }


def _keyword_stats(keywords: pd.DataFrame) -> dict:
    if keywords.empty:
        return {
            "keyword_count": 0,
            "top_keywords": "",
            "keyword_heat": 0.0,
        }
    frame = keywords.copy()
    heat_col = "热度" if "热度" in frame.columns else None
    if heat_col:
        frame[heat_col] = pd.to_numeric(frame[heat_col], errors="coerce").fillna(0)
        frame = frame.sort_values(heat_col, ascending=False)
        heat = float(frame[heat_col].sum())
    else:
        heat = 0.0
    name_col = "概念名称" if "概念名称" in frame.columns else frame.columns[0]
    top_keywords = "、".join(frame[name_col].astype(str).head(5).tolist())
    return {
        "keyword_count": int(len(frame)),
        "top_keywords": top_keywords,
        "keyword_heat": heat,
    }


def _latest_rank_value(frame: pd.DataFrame) -> int | None:
    if frame.empty or not {"item", "value"}.issubset(frame.columns):
        return None
    rank_rows = frame.loc[frame["item"].astype(str) == "rank", "value"]
    if rank_rows.empty:
        return None
    try:
        return int(rank_rows.iloc[0])
    except Exception:
        return None


def _research_report_stats(reports: pd.DataFrame, *, target_date: pd.Timestamp, days: int) -> dict:
    if reports.empty or "日期" not in reports.columns:
        return {
            "research_report_count": 0,
            "buy_rating_count": 0,
            "latest_rating": "",
            "latest_report": "",
        }
    frame = reports.copy()
    frame["date"] = pd.to_datetime(frame["日期"], errors="coerce").dt.normalize()
    start_date = target_date - pd.Timedelta(days=days)
    frame = frame[(frame["date"] >= start_date) & (frame["date"] <= target_date)]
    if frame.empty:
        return {
            "research_report_count": 0,
            "buy_rating_count": 0,
            "latest_rating": "",
            "latest_report": "",
        }
    rating = frame.get("东财评级", pd.Series(dtype=str)).fillna("").astype(str)
    buy_mask = rating.str.contains("买入|增持|推荐|强烈推荐", regex=True)
    latest = frame.sort_values("date", ascending=False).iloc[0]
    return {
        "research_report_count": int(len(frame)),
        "buy_rating_count": int(buy_mask.sum()),
        "latest_rating": str(latest.get("东财评级", "")),
        "latest_report": str(latest.get("报告名称", ""))[:80],
    }


def _pool_symbols(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "代码" not in frame.columns:
        return set()
    return {normalize_symbol(value) for value in frame["代码"].astype(str)}


def build_sentiment_scores(
    watchlist: pd.DataFrame,
    *,
    config: SentimentConfig = SentimentConfig(),
) -> tuple[pd.DataFrame, dict]:
    target_date = latest_weekday(config.target_date)
    date_compact = target_date.strftime("%Y%m%d")

    hot_rank_result = fetch_hot_rank()
    hot_rank = hot_rank_result.frame
    rank_map: dict[str, int] = {}
    if not hot_rank.empty and {"symbol", "当前排名"}.issubset(hot_rank.columns):
        for _, row in hot_rank.iterrows():
            try:
                rank_map[str(row["symbol"])] = int(row["当前排名"])
            except Exception:
                continue

    limit_pool_result = fetch_limit_pool(date_compact)
    strong_pool_result = fetch_strong_pool(date_compact)
    limit_symbols = _pool_symbols(limit_pool_result.frame)
    strong_symbols = _pool_symbols(strong_pool_result.frame)

    rows = []
    errors: list[str] = []
    for _, item in watchlist.iterrows():
        symbol = normalize_symbol(item["symbol"])
        name = str(item.get("name", ""))

        news_result = fetch_stock_news(symbol)
        research_result = fetch_research_reports(symbol)
        keyword_result = fetch_hot_keywords(symbol)
        latest_rank_result = fetch_hot_rank_latest(symbol)

        if news_result.error:
            errors.append(f"{symbol} 新闻: {news_result.error}")
        if research_result.error:
            errors.append(f"{symbol} 研报: {research_result.error}")
        if keyword_result.error:
            errors.append(f"{symbol} 热门关键词: {keyword_result.error}")
        if latest_rank_result.error:
            errors.append(f"{symbol} 最新排名: {latest_rank_result.error}")

        news_stats = _recent_news_stats(
            news_result.frame,
            symbol=symbol,
            name=name,
            target_date=target_date,
            days=config.news_days,
        )
        research_stats = _research_report_stats(
            research_result.frame,
            target_date=target_date,
            days=config.research_days,
        )
        keyword_stats = _keyword_stats(keyword_result.frame)
        hot_rank_value = rank_map.get(symbol) or _latest_rank_value(latest_rank_result.frame)

        score = 0.0
        score += _score_from_hot_rank(hot_rank_value, config.hot_rank_top)
        score += _score_from_count(news_stats["core_news_count"], 3, 14)
        score += _score_from_count(news_stats["generic_news_count"], 6, 4)
        score += _score_from_count(news_stats["core_positive_hits"], 2, 12)
        score += _score_from_count(news_stats["positive_hits"], 4, 4)
        score += _score_from_count(research_stats["research_report_count"], 3, 8)
        score += _score_from_count(research_stats["buy_rating_count"], 2, 5)
        score += _score_from_count(keyword_stats["keyword_count"], 3, 15)
        score += min(10.0, keyword_stats["keyword_heat"] / 1000 * 10)
        score += 10.0 if symbol in limit_symbols else 0.0
        score += 8.0 if symbol in strong_symbols else 0.0
        score -= _score_from_count(news_stats["core_risk_hits"], 1, 20)
        score -= _score_from_count(news_stats["risk_hits"], 3, 10)
        score = round(max(0.0, min(100.0, score)), 2)

        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "date": target_date.date().isoformat(),
                "sentiment_score": score,
                "hot_rank": hot_rank_value or "",
                "news_count": news_stats["news_count"],
                "core_news_count": news_stats["core_news_count"],
                "generic_news_count": news_stats["generic_news_count"],
                "positive_hits": news_stats["positive_hits"],
                "risk_hits": news_stats["risk_hits"],
                "core_positive_hits": news_stats["core_positive_hits"],
                "core_risk_hits": news_stats["core_risk_hits"],
                "keyword_count": keyword_stats["keyword_count"],
                "keyword_heat": round(keyword_stats["keyword_heat"], 2),
                "top_keywords": keyword_stats["top_keywords"],
                "research_report_count": research_stats["research_report_count"],
                "buy_rating_count": research_stats["buy_rating_count"],
                "latest_rating": research_stats["latest_rating"],
                "latest_report": research_stats["latest_report"],
                "in_limit_pool": symbol in limit_symbols,
                "in_strong_pool": symbol in strong_symbols,
                "latest_news": news_stats["latest_news"],
                "latest_core_news": news_stats["latest_core_news"],
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            ["sentiment_score", "news_count", "keyword_heat"],
            ascending=[False, False, False],
        ).reset_index(drop=True)

    meta = {
        "target_date": target_date.date().isoformat(),
        "hot_rank_error": hot_rank_result.error,
        "limit_pool_error": limit_pool_result.error,
        "strong_pool_error": strong_pool_result.error,
        "errors": errors,
    }
    return result, meta


def build_market_theme(date: str | None = None) -> tuple[pd.DataFrame, dict]:
    target_date = latest_weekday(date)
    date_compact = target_date.strftime("%Y%m%d")
    limit_result = fetch_limit_pool(date_compact)
    strong_result = fetch_strong_pool(date_compact)
    hot_result = fetch_hot_rank()

    frames = []
    for label, frame in (("涨停池", limit_result.frame), ("强势股池", strong_result.frame)):
        if frame.empty or "所属行业" not in frame.columns:
            continue
        data = frame.copy()
        data["来源"] = label
        frames.append(data)

    if frames:
        merged = pd.concat(frames, ignore_index=True)
        amount_col = "成交额" if "成交额" in merged.columns else None
        if amount_col:
            merged[amount_col] = pd.to_numeric(merged[amount_col], errors="coerce").fillna(0)
        grouped = merged.groupby("所属行业").agg(
            stock_count=("代码", "count"),
            limit_count=("来源", lambda values: int((values == "涨停池").sum())),
            strong_count=("来源", lambda values: int((values == "强势股池").sum())),
            amount=(amount_col, "sum") if amount_col else ("代码", "count"),
        )
        theme = grouped.reset_index().rename(columns={"所属行业": "theme"})
        theme["theme_score"] = (
            theme["limit_count"] * 3
            + theme["strong_count"] * 2
            + (theme["amount"] / max(theme["amount"].max(), 1) * 5)
        ).round(2)
        theme = theme.sort_values(
            ["theme_score", "stock_count"],
            ascending=[False, False],
        ).reset_index(drop=True)
    else:
        theme = pd.DataFrame(
            columns=["theme", "stock_count", "limit_count", "strong_count", "amount", "theme_score"]
        )

    hot_top = []
    if not hot_result.frame.empty:
        cols = [col for col in ["当前排名", "代码", "股票名称", "涨跌幅"] if col in hot_result.frame.columns]
        hot_top = hot_result.frame.loc[:, cols].head(20).to_dict("records")

    meta = {
        "target_date": target_date.date().isoformat(),
        "limit_pool_error": limit_result.error,
        "strong_pool_error": strong_result.error,
        "hot_rank_error": hot_result.error,
        "hot_top": hot_top,
    }
    return theme, meta
