from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.research.external_data import classify_risk_event
from quant_a_stock.research.external_data import money_flow_success_rate
from quant_a_stock.research.external_data import normalize_iwencai_export
from quant_a_stock.research.external_data import normalize_money_flow_frame
from quant_a_stock.research.external_data import normalize_ths_money_flow_rank
from quant_a_stock.research.external_data import read_csv_flexible
from quant_a_stock.research.external_data import summarize_risk_events


def test_classify_and_summarize_cninfo_risk_events() -> None:
    event_type, severity, score = classify_risk_event("关于收到监管问询函的公告")

    assert event_type == "监管问询"
    assert severity == "中高"
    assert score == 5.0

    events = pd.DataFrame(
        [
            {
                "symbol": "2137",
                "title": "关于收到监管问询函的公告",
                "event_type": "监管问询",
                "severity": "中高",
                "severity_score": 5,
            },
            {
                "symbol": "002137",
                "title": "关于股东减持计划的公告",
                "event_type": "减持解禁",
                "severity": "中",
                "severity_score": 3,
            },
        ]
    )

    summary = summarize_risk_events(events)

    row = summary.iloc[0]
    assert row["symbol"] == "002137"
    assert row["risk_notice_count"] == 2
    assert row["risk_event_score"] == 8
    assert row["high_risk_event_count"] == 0
    assert "监管问询" in row["risk_event_types"]


def test_risk_event_classification_requires_explicit_adverse_context() -> None:
    assert classify_risk_event("关于在充分尽职调查和内核基础上出具的承诺函") == ("", "", 0.0)

    event_type, severity, score = classify_risk_event("关于收到中国证监会立案告知书的公告")

    assert event_type == "立案处罚"
    assert severity == "高"
    assert score == 8.0


def test_risk_event_summary_deduplicates_and_decays_old_events() -> None:
    events = pd.DataFrame(
        [
            {"symbol": "002137", "date": "2026-07-09", "title": "关于收到监管问询函的公告"},
            {"symbol": "002137", "date": "2026-07-09", "title": "关于收到监管问询函的公告"},
            {"symbol": "002137", "date": "2026-05-12", "title": "关于股东减持计划的公告"},
        ]
    )

    row = summarize_risk_events(events, as_of_date="2026-07-10", half_life_days=30).iloc[0]

    assert row["risk_notice_count"] == 2
    assert row["risk_event_score"] == 5.65
    assert row["high_risk_event_count"] == 0
    assert row["risk_event_age_days"] == 1


def test_normalize_money_flow_frame_scores_recent_positive_flow() -> None:
    frame = pd.DataFrame(
        [
            {"日期": "2026-07-06", "主力净流入-净额": "1.2亿", "主力净流入-净占比": "5.5%"},
            {"日期": "2026-07-07", "主力净流入-净额": "8000万", "主力净流入-净占比": "3.0%"},
            {"日期": "2026-07-08", "主力净流入-净额": "-1000万", "主力净流入-净占比": "-0.5%"},
        ]
    )

    row = normalize_money_flow_frame(frame, symbol="2137", target_date="2026-07-08")

    assert row["symbol"] == "002137"
    assert row["date"] == "2026-07-08"
    assert row["main_net_inflow_3d"] == 190_000_000
    assert row["positive_flow_days_5"] == 2
    assert row["money_flow_score"] > 0


def test_money_flow_success_rate_counts_rows_without_errors() -> None:
    frame = pd.DataFrame(
        [
            {"symbol": "002137", "error": ""},
            {"symbol": "600999", "error": None},
            {"symbol": "600160", "error": "ConnectionError"},
        ]
    )

    assert money_flow_success_rate(frame) == 2 / 3


def test_normalize_ths_money_flow_rank_builds_same_day_fallback() -> None:
    current = pd.DataFrame(
        [
            {"股票代码": "002137", "净额": "1.2亿", "成交额": "6亿"},
            {"股票代码": "600999", "净额": "-2000万", "成交额": "4亿"},
        ]
    )
    flow_3d = pd.DataFrame(
        [
            {"股票代码": "002137", "资金流入净额": "2亿"},
            {"股票代码": "600999", "资金流入净额": "-3000万"},
        ]
    )
    flow_5d = pd.DataFrame(
        [
            {"股票代码": "002137", "资金流入净额": "3亿"},
            {"股票代码": "600999", "资金流入净额": "-5000万"},
        ]
    )

    result = normalize_ths_money_flow_rank(
        current,
        flow_3d=flow_3d,
        flow_5d=flow_5d,
        symbols=["2137"],
        target_date="2026-07-23",
    )

    row = result.iloc[0]
    assert row["symbol"] == "002137"
    assert row["main_net_inflow_pct"] == 20.0
    assert row["main_net_inflow_3d"] == 200_000_000
    assert row["main_net_inflow_5d"] == 300_000_000
    assert row["source"] == "10jqka_market_rank"
    assert row["error"] == ""


def test_normalize_iwencai_export_and_flexible_csv(tmp_path: Path) -> None:
    source = tmp_path / "iwencai.csv"
    pd.DataFrame(
        [
            {"股票代码": "2137", "股票简称": "实益达", "综合评分": "88", "概念": "半导体"},
            {"股票代码": "600999", "股票简称": "招商证券", "综合评分": "66", "概念": "证券"},
        ]
    ).to_csv(source, index=False, encoding="utf-8-sig")

    raw = read_csv_flexible(source)
    result = normalize_iwencai_export(
        raw,
        target_date="2026-07-08",
        query="低位放量 半导体",
        source=str(source),
    )

    assert result["symbol"].tolist() == ["002137", "600999"]
    assert result.loc[0, "iwencai_hit"] == 1
    assert result.loc[0, "iwencai_score"] == 88
    assert result.loc[0, "iwencai_query"] == "低位放量 半导体"
