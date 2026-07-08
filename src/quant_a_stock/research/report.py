from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS


def save_research_candidates_markdown(
    candidates: pd.DataFrame,
    *,
    meta: dict | None = None,
) -> Path:
    DEFAULT_PATHS.reports.mkdir(parents=True, exist_ok=True)
    meta = meta or {}
    date_prefix = str(meta.get("target_date", "")) or None
    if date_prefix:
        stamp = f"{date_prefix.replace('-', '')}_{datetime.now().strftime('%H%M%S')}"
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DEFAULT_PATHS.reports / f"research_candidates_{stamp}.md"

    lines = [
        "# 全市场潜力股研究候选池",
        "",
        f"- 目标日期：{meta.get('target_date', '')}",
        f"- 形态报告：{meta.get('scan_report', '')}",
        f"- 情绪报告：{meta.get('sentiment_report', '')}",
        f"- 市场主线报告：{meta.get('theme_report', '')}",
        f"- 候选数量：{len(candidates)}",
        "",
        "## 评分口径",
        "",
        "研究分 = 形态分 * 0.65 + 情绪分 * 0.35 + 阶段加分 + 主线加分 + 行业同涨加分 - 扣分项。",
        "",
        "分层含义：A1=早期潜伏，A2=启动确认，A3=强趋势回踩/再启动，B1=观察主池，B2/C=备选观察。新增 action_bucket 用来区分主攻、补票、观察和风险回避。",
        "",
        "当前研究口径：主攻 A2 启动确认和主线仍强、风险干净、不拥挤的 A3 趋势延续；A1 低位潜伏先观察；B2 拆成 B2a 主线扩散待升级、B2s 低位主线突发待确认和 B2b 主题待确认。",
        "",
        "扣分项包括近 20 日涨幅过热、量能过热、量价同时过热、月线/区间位置偏高、次新样本不足和风险公告命中。risk_level 和 risk_tags 要优先看。",
        "",
        "## 候选分层",
        "",
    ]

    if candidates.empty:
        lines.append("没有可展示的候选。")
    else:
        display_cols = [
            "symbol",
            "name",
            "research_tier",
            "b2_subtype",
            "action_bucket",
            "research_score",
            "stage",
            "setup_phase",
            "score",
            "mtf_score",
            "monthly_position_pct",
            "weekly_trend_slope_pct",
            "sentiment_score",
            "matched_theme",
            "co_rise_count",
            "total_penalty",
            "risk_level",
            "risk_tags",
        ]
        existing_cols = [column for column in display_cols if column in candidates.columns]
        lines.extend(
            [
                _markdown_table(candidates.loc[:, existing_cols].head(50)),
                "",
            ]
        )

        for title, bucket_names in [
            ("主攻池", ["主攻-A2启动确认", "主攻-A3趋势延续"]),
            ("B2a 主线扩散升级观察池", ["观察-B2a主线扩散待升级", "补票-B2a主线扩散", "补票-B2强主题"]),
            ("B2s 低位主线突发待确认池", ["观察-B2s主线突发待确认", "补票-主线突发"]),
            ("B2b 主题待确认观察池", ["观察-B2b主题待确认"]),
            ("低位和高波动观察池", ["观察-A1低位潜伏", "观察-A3高波动", "观察-B级候选"]),
            ("风险优先回避池", ["回避-风险优先"]),
        ]:
            if "action_bucket" not in candidates.columns:
                continue
            subset = candidates[candidates["action_bucket"].isin(bucket_names)]
            if subset.empty:
                continue
            lines.extend([f"## {title}", ""])
            lines.append(_markdown_table(subset.loc[:, existing_cols].head(30)))
            lines.append("")

        for tier in ["A1", "A2", "A3", "B1", "B2", "C", "观察"]:
            subset = candidates[candidates["research_tier"] == tier]
            if subset.empty:
                continue
            lines.extend([f"## {tier} 级候选", ""])
            for _, row in subset.head(20).iterrows():
                lines.extend(_candidate_lines(row))

    errors = meta.get("errors") or []
    if errors:
        lines.extend(["## 数据源提示", ""])
        for error in errors[:30]:
            lines.append(f"- {error}")
        if len(errors) > 30:
            lines.append(f"- 还有 {len(errors) - 30} 条提示未展开。")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _candidate_lines(row: pd.Series) -> list[str]:
    symbol = row.get("symbol", "")
    name = row.get("name", "")
    lines = [
        f"### {symbol} {name}",
        "",
        f"- 研究分：{row.get('research_score', '')}",
        f"- 动作分组：{row.get('action_bucket', '') or '未分组'}，风险等级 {row.get('risk_level', '') or '未标注'}",
        f"- 动作提示：{row.get('upgrade_hint', '') or '观察为主'}",
        f"- 形态：{row.get('stage', '')}，节奏 {row.get('setup_phase', '') or '未标注'}，形态分 {row.get('score', '')}",
        f"- 多周期：月线位置 {row.get('monthly_position_pct', '')}，"
        f"周线趋势 {row.get('weekly_trend_slope_pct', '')}，"
        f"多周期分 {row.get('mtf_score', '')}",
        f"- 情绪分：{row.get('sentiment_score', '')}，人气排名 {row.get('hot_rank', '')}",
        f"- 主线命中：{row.get('matched_theme', '') or '未命中'}，主线加分 {row.get('theme_bonus', '')}",
        f"- 行业同涨：{row.get('co_rise_count', 0)}，同涨加分 {row.get('co_rise_bonus', '')}",
        f"- 上市天数：{row.get('listing_days', '')}，样本类型 {row.get('age_bucket', '') or '未知'}",
        f"- 扣分：总扣分 {row.get('total_penalty', '')}，"
        f"量能过热 {row.get('volume_overheat_penalty', '')}，"
        f"涨幅过热 {row.get('ret20_overheat_penalty', '')}，"
        f"量价共振过热 {row.get('combined_overheat_penalty', '')}，"
        f"位置偏高 {row.get('position_overhead_penalty', '')}，"
        f"公告风险 {row.get('risk_notice_penalty', '')}",
        f"- 风险标签：{row.get('risk_tags', '') or '无明显风险'}",
        f"- 热门关键词：{row.get('top_keywords', '') or '无'}",
    ]
    if str(row.get("stage", "")) in {"trend_pullback", "trend_resume"}:
        lines.append(
            f"- 趋势回踩：60 日涨幅 {row.get('ret_60_pct', '')}，"
            f"离 60 日高点 {row.get('drawdown_from_high_pct', '')}，"
            f"趋势/回踩/再启动分 {row.get('trend_score', '')}/"
            f"{row.get('pullback_score', '')}/{row.get('resume_score', '')}"
        )
    risk_titles = str(row.get("risk_notice_titles", "") or "")
    if risk_titles:
        lines.append(f"- 风险公告命中：{risk_titles}")
    lines.append("")
    return lines


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in frame.iterrows():
        values = [str(row.get(column, "")).replace("|", "/") for column in frame.columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
