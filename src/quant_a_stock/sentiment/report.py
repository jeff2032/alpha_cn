from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS


def _report_path(prefix: str, suffix: str = "md") -> Path:
    DEFAULT_PATHS.reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_PATHS.reports / f"{prefix}_{stamp}.{suffix}"


def save_sentiment_markdown(scores: pd.DataFrame, meta: dict, *, title: str = "候选股情绪面报告") -> Path:
    path = _report_path("sentiment_watchlist")
    lines = [
        f"# {title}",
        "",
        f"- 目标日期：{meta.get('target_date', '')}",
        f"- 标的数量：{len(scores)}",
        "",
        "## 候选排序",
        "",
    ]

    if scores.empty:
        lines.append("没有可展示的候选。")
    else:
        for _, row in scores.iterrows():
            lines.extend(
                [
                    f"### {row['symbol']} {row.get('name', '')}",
                    "",
                    f"- 情绪分：{row['sentiment_score']}",
                    f"- 人气排名：{row['hot_rank'] if row['hot_rank'] != '' else '未进入榜单'}",
                    f"- 近端新闻数：{row['news_count']}，核心新闻 {row.get('core_news_count', 0)}，泛消息 {row.get('generic_news_count', 0)}",
                    f"- 正向关键词命中：{row['positive_hits']}，核心正向 {row.get('core_positive_hits', 0)}",
                    f"- 风险关键词命中：{row['risk_hits']}，核心风险 {row.get('core_risk_hits', 0)}",
                    f"- 近 90 天研报：{row.get('research_report_count', 0)}，买入/增持类 {row.get('buy_rating_count', 0)}",
                    f"- 最新评级：{row.get('latest_rating', '') or '无'}",
                    f"- 热门关键词：{row['top_keywords'] or '无'}",
                    f"- 是否在涨停池：{'是' if row['in_limit_pool'] else '否'}",
                    f"- 是否在强势股池：{'是' if row['in_strong_pool'] else '否'}",
                    f"- 核心新闻：{row.get('latest_core_news', '') or '无'}",
                    f"- 最新新闻：{row['latest_news'] or '无'}",
                    f"- 最新研报：{row.get('latest_report', '') or '无'}",
                    "",
                ]
            )

    errors = meta.get("errors") or []
    provider_errors = [
        value
        for key, value in meta.items()
        if key.endswith("_error") and value
    ]
    if errors or provider_errors:
        lines.extend(["## 数据源提示", ""])
        for error in provider_errors + errors[:20]:
            lines.append(f"- {error}")
        if len(errors) > 20:
            lines.append(f"- 还有 {len(errors) - 20} 条个股接口错误未展开。")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def save_market_theme_markdown(theme: pd.DataFrame, meta: dict) -> Path:
    path = _report_path("market_theme")
    lines = [
        "# 市场主线观察报告",
        "",
        f"- 目标日期：{meta.get('target_date', '')}",
        "",
        "## 涨停/强势行业方向",
        "",
    ]

    if theme.empty:
        lines.append("没有可展示的行业方向。")
    else:
        for _, row in theme.head(20).iterrows():
            lines.append(
                f"- {row['theme']}：主线分 {row['theme_score']}，"
                f"涨停 {row['limit_count']}，强势 {row['strong_count']}，"
                f"合计标的 {row['stock_count']}"
            )

    hot_top = meta.get("hot_top") or []
    lines.extend(["", "## 东财人气榜前 20", ""])
    if not hot_top:
        lines.append("人气榜暂不可用。")
    else:
        for item in hot_top:
            rank = item.get("当前排名", "")
            code = item.get("代码", "")
            name = item.get("股票名称", "")
            pct = item.get("涨跌幅", "")
            lines.append(f"- 第 {rank} 名：{code} {name}，涨跌幅 {pct}")

    provider_errors = [
        value
        for key, value in meta.items()
        if key.endswith("_error") and value
    ]
    if provider_errors:
        lines.extend(["", "## 数据源提示", ""])
        for error in provider_errors:
            lines.append(f"- {error}")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
