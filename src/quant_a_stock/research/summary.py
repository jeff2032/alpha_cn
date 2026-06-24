from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.cache import load_daily_cache
from quant_a_stock.research.snapshot import SNAPSHOT_ROOT


THEME_CLUSTERS: dict[str, list[str]] = {
    "半导体链": [
        "半导体",
        "芯片",
        "先进封装",
        "PCB",
        "覆铜板",
        "电子化学",
        "电子材料",
        "存储芯片",
        "功率半导体",
        "中芯",
        "存储",
        "集成电路",
        "光刻",
        "MiniLED",
    ],
    "AI硬件": ["液冷", "算力", "服务器", "CPO", "光模块", "人工智能", "数据中心", "高速连接"],
    "消费电子": ["消费电子", "手机", "平板", "智能穿戴", "摄像头", "声学", "光学光电", "元件", "面板"],
    "电池链": ["电池", "锂电", "固态电池", "刀片电池", "储能", "新能源"],
    "化工材料": ["化工", "氟化工", "化学", "新材料", "工业气体", "制冷剂", "橡胶", "塑料"],
    "水利基建": ["地下管网", "水利", "海绵城市", "新型城镇化", "管业", "管网"],
    "环保公用": ["节能环保", "环保", "生态保护", "环境治理", "水务"],
    "建材材料": ["非金属矿物", "建材", "玻璃", "水泥", "新材"],
    "煤炭资源": ["煤炭", "焦煤", "煤化工"],
    "军工航天": ["军工", "商业航天", "航空", "航天", "卫星", "船舶", "海工装备", "航母"],
    "交通运输": ["铁路", "高速", "公路", "道路运输", "铁路运输", "铁路基建"],
    "通信设备": ["通信", "信创", "国产软件", "网络", "计算机", "电子设备制造"],
    "机器人设备": ["机器人", "通用设备", "自动化", "工业母机", "机床"],
    "汽车链": ["汽车", "汽车零部件", "无人驾驶", "智能驾驶", "车联网", "新能源汽车"],
    "低空经济": ["低空经济", "无人机", "eVTOL", "飞行汽车", "航空器"],
    "金融": ["银行", "证券", "券商", "互联金融", "保险", "金租", "货币金融", "金融服务", "融资租赁"],
    "地产链": ["房地产", "装修", "装饰", "家居", "物业", "建筑装饰"],
    "消费": ["啤酒", "食品", "饮料", "家电", "超级品牌", "体育产业", "旅游", "零售"],
    "医药": ["创新药", "医药", "医疗器械", "流感", "生物", "中药", "化学制药", "CXO"],
    "电力能源": ["核电", "电力", "风能", "光伏", "中特估", "水电", "绿色电力", "能源"],
    "港口航运": ["港口", "航运", "物流", "水上运输", "港"],
}

GENERIC_THEME_WORDS = {
    "机构重仓",
    "国企改革",
    "MSCI中国",
    "证金持股",
    "转债标的",
    "专精特新",
    "股权激励",
    "AH股",
    "中字头",
}


@dataclass(frozen=True)
class DailyResearchSummary:
    target_date: str
    snapshot_dir: Path
    market: dict
    market_components: pd.DataFrame
    theme: pd.DataFrame
    candidates: pd.DataFrame


def classify_theme_cluster(row: pd.Series) -> str:
    text = " ".join(
        [
            _clean_text(row.get("matched_theme", "")),
            _clean_text(row.get("industry", "")),
            _clean_text(row.get("top_keywords", "")),
            _clean_text(row.get("latest_core_news", "")),
            _clean_text(row.get("latest_news", "")),
            _clean_text(row.get("latest_report", "")),
            _clean_text(row.get("name", "")),
        ]
    )
    for cluster, keywords in THEME_CLUSTERS.items():
        if any(keyword in text for keyword in keywords):
            return cluster
    return _fallback_theme_cluster(row)


def build_market_temperature(
    *,
    target_date: str,
    symbols: tuple[str, ...] = ("510300", "510500", "159915"),
) -> tuple[dict, pd.DataFrame]:
    rows = []
    for symbol in symbols:
        try:
            candles = load_daily_cache(symbol)
        except Exception:
            continue
        frame = candles.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame[frame["timestamp"] <= pd.Timestamp(target_date)].sort_values("timestamp")
        if len(frame) < 60:
            continue
        close = frame["close"]
        latest = frame.iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ret20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) > 20 else 0.0
        ret60 = close.iloc[-1] / close.iloc[-61] - 1 if len(close) > 60 else 0.0
        high60 = frame["high"].rolling(60).max().iloc[-1]
        drawdown60 = close.iloc[-1] / high60 - 1
        score = _market_symbol_score(
            close=float(close.iloc[-1]),
            ma20=float(ma20),
            ma60=float(ma60),
            ret20=float(ret20),
            ret60=float(ret60),
            drawdown60=float(drawdown60),
        )
        rows.append(
            {
                "symbol": symbol,
                "date": pd.Timestamp(latest["timestamp"]).date().isoformat(),
                "close": round(float(close.iloc[-1]), 4),
                "ma20": round(float(ma20), 4),
                "ma60": round(float(ma60), 4),
                "ret20": round(float(ret20), 4),
                "ret60": round(float(ret60), 4),
                "drawdown60": round(float(drawdown60), 4),
                "score": round(score, 2),
            }
        )

    components = pd.DataFrame(rows)
    if components.empty:
        return {"score": 0.0, "regime": "未知", "advice": "指数缓存不足，先按防守口径复盘。"}, components

    score = float(components["score"].mean())
    regime = _market_regime(score)
    advice = _market_advice(regime)
    return {"score": round(score, 2), "regime": regime, "advice": advice}, components


def build_daily_research_summary(
    *,
    target_date: str,
    snapshot_dir: Path | None = None,
) -> DailyResearchSummary:
    snapshot = snapshot_dir or SNAPSHOT_ROOT / target_date
    candidates = pd.read_csv(snapshot / "research_candidates.csv", dtype={"symbol": str})
    theme = pd.read_csv(snapshot / "market_theme.csv")
    candidates["symbol"] = candidates["symbol"].astype(str).str.zfill(6)
    candidates["theme_cluster"] = candidates.apply(classify_theme_cluster, axis=1)
    lifecycle = build_candidate_lifecycle(candidates, target_date=target_date)
    if not lifecycle.empty:
        candidates = candidates.merge(lifecycle, on="symbol", how="left")
    if "research_tier_rank" not in candidates.columns:
        candidates["research_tier_rank"] = candidates["research_tier"].map(_tier_rank)
    if "action_rank" not in candidates.columns:
        candidates["action_rank"] = candidates["research_tier_rank"]
    if "action_bucket" not in candidates.columns:
        candidates["action_bucket"] = candidates["research_tier"].map(_fallback_action_bucket)
    candidates = candidates.sort_values(
        ["action_rank", "research_tier_rank", "research_score", "score", "sentiment_score"],
        ascending=[True, True, False, False, False],
    ).reset_index(drop=True)
    market, components = build_market_temperature(target_date=target_date)
    return DailyResearchSummary(
        target_date=target_date,
        snapshot_dir=snapshot,
        market=market,
        market_components=components,
        theme=theme,
        candidates=candidates,
    )


def build_candidate_lifecycle(
    current: pd.DataFrame,
    *,
    target_date: str,
    snapshot_root: Path = SNAPSHOT_ROOT,
) -> pd.DataFrame:
    dates = [
        path.name
        for path in snapshot_root.iterdir()
        if path.is_dir() and (path / "research_candidates.csv").exists() and path.name <= target_date
    ]
    dates = sorted(dates)
    if not dates:
        return pd.DataFrame()

    history: dict[str, list[dict]] = {}
    for date in dates:
        frame = pd.read_csv(snapshot_root / date / "research_candidates.csv", dtype={"symbol": str})
        frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
        for _, row in frame.iterrows():
            history.setdefault(row["symbol"], []).append(
                {
                    "date": date,
                    "research_tier": row.get("research_tier", ""),
                    "research_score": float(row.get("research_score", 0) or 0),
                }
            )

    rows = []
    for symbol in current["symbol"].astype(str).str.zfill(6):
        events = history.get(symbol, [])
        if not events:
            continue
        current_event = events[-1]
        previous = events[-2] if len(events) >= 2 else None
        rows.append(
            {
                "symbol": symbol,
                "first_seen_date": events[0]["date"],
                "days_seen": len(events),
                "consecutive_days": _consecutive_days(events, dates),
                "previous_tier": previous["research_tier"] if previous else "",
                "previous_score": previous["research_score"] if previous else 0.0,
                "score_delta": round(
                    current_event["research_score"] - (previous["research_score"] if previous else current_event["research_score"]),
                    2,
                ),
                "is_new_today": len(events) == 1,
            }
        )
    return pd.DataFrame(rows)


def save_daily_research_summary_markdown(summary: DailyResearchSummary, *, top: int = 30) -> Path:
    DEFAULT_PATHS.reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DEFAULT_PATHS.reports / f"daily_research_summary_{stamp}.md"
    candidates = summary.candidates.copy()
    for column in ["core_news_count", "research_report_count", "total_penalty"]:
        if column not in candidates.columns:
            candidates[column] = 0

    lines = [
        "# 每日市场选股复盘",
        "",
        f"- 目标日期：{summary.target_date}",
        f"- 快照目录：{summary.snapshot_dir}",
        f"- 市场温度：{summary.market['regime']}，温度分 {summary.market['score']}",
        f"- 操作口径：{summary.market['advice']}",
        "",
        "## 指数温度",
        "",
    ]
    lines.append(_markdown_table(summary.market_components))
    lines.extend(["", "## 今日主线", ""])
    lines.append(_markdown_table(summary.theme.head(12)))

    cluster = (
        candidates.groupby("theme_cluster")
        .agg(
            candidate_count=("symbol", "count"),
            avg_score=("research_score", "mean"),
            a_b_count=(
                "research_tier",
                lambda values: int(values.isin(["A1", "A2", "A3", "B1", "B2"]).sum()),
            ),
        )
        .reset_index()
        .sort_values(["a_b_count", "avg_score"], ascending=[False, False])
    )
    cluster["avg_score"] = cluster["avg_score"].round(2)
    lines.extend(["", "## 主题簇强度", "", _markdown_table(cluster), ""])

    display_cols = [
        "symbol",
        "name",
        "research_tier",
        "action_bucket",
        "research_score",
        "theme_cluster",
        "stage",
        "setup_phase",
        "score",
        "mtf_score",
        "monthly_position_pct",
        "weekly_trend_slope_pct",
        "ret_60_pct",
        "drawdown_from_high_pct",
        "sentiment_score",
        "core_news_count",
        "research_report_count",
        "total_penalty",
        "risk_level",
        "risk_tags",
        "days_seen",
        "score_delta",
    ]
    action_core = candidates[
        candidates["action_bucket"].isin(["主攻-A2启动确认", "主攻-A3趋势延续", "补票-B2强主题"])
    ].head(top)
    if action_core.empty:
        action_core = candidates[candidates["research_tier"].isin(["A2", "A3", "B1", "B2"])].head(top)
    lines.extend(["## 主攻与补票候选", "", _markdown_table(action_core[_existing(action_core, display_cols)]), ""])

    for title, note, frame in _candidate_bucket_sections(candidates, top=top):
        lines.extend([f"## {title}", "", note, "", _markdown_table(frame[_existing(frame, display_cols)]), ""])

    lines.extend(["## 核心候选解读", ""])
    if action_core.empty:
        lines.append("今天没有主攻或补票候选。")
    else:
        for _, row in action_core.iterrows():
            lines.extend(_candidate_reason_lines(row))

    core_buckets = ["主攻-A2启动确认", "主攻-A3趋势延续", "补票-B2强主题"]
    watch = candidates[
        (~candidates["action_bucket"].isin(core_buckets))
        | (candidates["total_penalty"].fillna(0) > 0)
        | (candidates["core_news_count"].fillna(0) == 0)
    ].head(12)
    lines.extend(["## 观察和风险提醒", "", _markdown_table(watch[_existing(watch, display_cols)]), ""])
    lines.append("这份报告只做研究辅助，不构成买卖建议。")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _candidate_bucket_sections(candidates: pd.DataFrame, *, top: int) -> list[tuple[str, str, pd.DataFrame]]:
    early = candidates[candidates["action_bucket"].isin(["观察-A1低位潜伏", "主攻-A2启动确认"])].head(top)
    trend = candidates[candidates["action_bucket"].isin(["主攻-A3趋势延续", "观察-A3高波动"])].head(top)
    watch = candidates[candidates["action_bucket"].isin(["补票-B2强主题", "观察-B级候选"])].head(top)
    return [
        (
            "A1/A2 低位潜伏与启动池",
            "A2 是主攻，A1 先观察；看 3-5 日是否转强，不用单日涨跌评价潜伏模型。",
            early,
        ),
        (
            "A3 主线趋势延续池",
            "风险干净的 A3 才是主攻；高波动 A3 只看分歧承接，避免高开过热追买。",
            trend,
        ),
        (
            "B1/B2 观察补票池",
            "只有强主题、风险干净、成交额足够的 B2 才进入补票观察，不直接当作买点。",
            watch,
        ),
    ]


def _market_symbol_score(
    *,
    close: float,
    ma20: float,
    ma60: float,
    ret20: float,
    ret60: float,
    drawdown60: float,
) -> float:
    score = 0.0
    score += 20 if close > ma20 else 0
    score += 20 if ma20 > ma60 else 0
    score += max(0.0, min(20.0, (ret20 + 0.08) / 0.16 * 20))
    score += max(0.0, min(20.0, (ret60 + 0.12) / 0.24 * 20))
    score += max(0.0, min(20.0, (drawdown60 + 0.20) / 0.20 * 20))
    return score


def _market_regime(score: float) -> str:
    if score >= 72:
        return "强势"
    if score >= 58:
        return "震荡偏强"
    if score >= 42:
        return "震荡"
    return "防守"


def _market_advice(regime: str) -> str:
    if regime == "强势":
        return "可以积极复盘 A/B 级候选，但仍避免追高。"
    if regime == "震荡偏强":
        return "优先看主线内 A 级和低扣分 B 级。"
    if regime == "震荡":
        return "控制候选数量，优先等待突破确认。"
    return "偏防守，只观察极强主线和核心催化票。"


def _consecutive_days(events: list[dict], all_dates: list[str]) -> int:
    event_dates = {event["date"] for event in events}
    count = 0
    for date in reversed(all_dates):
        if date in event_dates:
            count += 1
        elif count > 0:
            break
    return count


def _candidate_reason_lines(row: pd.Series) -> list[str]:
    reasons = []
    matched_theme = _clean_text(row.get("matched_theme", ""))
    latest_core_news = _clean_text(row.get("latest_core_news", ""))
    latest_report = _clean_text(row.get("latest_report", ""))
    if matched_theme:
        reasons.append(f"命中主线 {matched_theme}")
    if row.get("core_news_count", 0) > 0:
        reasons.append(f"有核心新闻 {int(row.get('core_news_count', 0))} 条")
    if row.get("research_report_count", 0) > 0:
        reasons.append(f"近端研报 {int(row.get('research_report_count', 0))} 篇")
    if row.get("co_rise_count", 0) > 1:
        reasons.append(f"同主题/行业候选 {int(row.get('co_rise_count', 0))} 只")
    if row.get("total_penalty", 0) > 0:
        reasons.append(f"扣分 {row.get('total_penalty')}")
    action_bucket = _clean_text(row.get("action_bucket", ""))
    risk_level = _clean_text(row.get("risk_level", ""))
    risk_tags = _clean_text(row.get("risk_tags", ""))
    upgrade_hint = _clean_text(row.get("upgrade_hint", ""))
    trend_line = ""
    if str(row.get("stage", "")) in {"trend_pullback", "trend_resume"}:
        trend_line = (
            f"- 趋势回踩：60 日涨幅 {row.get('ret_60_pct', '')}，"
            f"离 60 日高点 {row.get('drawdown_from_high_pct', '')}，"
            f"趋势/回踩/再启动分 {row.get('trend_score', '')}/"
            f"{row.get('pullback_score', '')}/{row.get('resume_score', '')}"
        )
    reason_text = "；".join(reasons) if reasons else "形态和分层靠前，但缺少额外消息确认"
    lines = [
        f"### {row.get('symbol')} {row.get('name')}",
        "",
        f"- 分层：{row.get('research_tier')}，研究分 {row.get('research_score')}",
        f"- 动作分组：{action_bucket or '未分组'}，风险等级 {risk_level or '未标注'}",
        f"- 主题簇：{row.get('theme_cluster')}，阶段 {row.get('stage')}，节奏 {row.get('setup_phase', '') or '未标注'}",
        f"- 多周期：月线位置 {row.get('monthly_position_pct', '')}，周线趋势 {row.get('weekly_trend_slope_pct', '')}，多周期分 {row.get('mtf_score', '')}",
        f"- 理由：{reason_text}",
        f"- 动作提示：{upgrade_hint or '观察为主'}",
        f"- 风险标签：{risk_tags or '无明显风险'}",
        f"- 核心新闻：{latest_core_news or '无'}",
        f"- 最新研报：{latest_report or '无'}",
        "",
    ]
    if trend_line:
        lines.insert(5, trend_line)
    return lines


def _tier_rank(tier: str) -> int:
    return {
        "A1": 1,
        "A2": 2,
        "A3": 3,
        "B1": 4,
        "B2": 5,
        "C": 6,
        "观察": 7,
    }.get(str(tier), 9)


def _fallback_action_bucket(tier: object) -> str:
    value = str(tier)
    if value == "A2":
        return "主攻-A2启动确认"
    if value == "A3":
        return "主攻-A3趋势延续"
    if value == "A1":
        return "观察-A1低位潜伏"
    if value in {"B1", "B2"}:
        return "观察-B级候选"
    return "观察-低优先级"


def _existing(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in frame.columns]


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "无"
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in frame.iterrows():
        values = [_clean_text(row.get(column, "")).replace("|", "/") for column in frame.columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "none"}:
        return ""
    return text


def _fallback_theme_cluster(row: pd.Series) -> str:
    matched_theme = _clean_text(row.get("matched_theme", ""))
    if matched_theme:
        return matched_theme

    top_keywords = _clean_text(row.get("top_keywords", ""))
    for keyword in re.split(r"[、,，;；/ ]+", top_keywords):
        keyword = keyword.strip()
        if keyword and keyword not in GENERIC_THEME_WORDS:
            return keyword

    industry = _clean_text(row.get("industry", ""))
    if industry:
        return _compact_industry_name(industry)

    name = _clean_text(row.get("name", ""))
    if name:
        return f"{name}相关"
    return "待命名板块"


def _compact_industry_name(industry: str) -> str:
    replacements = {
        "计算机、通信和其他电子设备制造业": "通信电子",
        "生态保护和环境治理业": "环保公用",
        "非金属矿物制品业": "建材材料",
        "橡胶和塑料制品业": "化工材料",
        "煤炭开采和洗选业": "煤炭资源",
        "货币金融服务": "金融",
        "水上运输业": "港口航运",
        "铁路运输业": "交通运输",
        "道路运输业": "交通运输",
    }
    if industry in replacements:
        return replacements[industry]
    return industry.removesuffix("业").removesuffix("服务").strip() or "待命名板块"
