from __future__ import annotations

import pandas as pd

from quant_a_stock.research.candidates import build_research_candidates


def test_build_research_candidates_adds_theme_and_penalties() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "600160",
                "timestamp": "2026-06-12",
                "stage": "near_breakout",
                "score": 60.0,
                "volume_ratio": 1.5,
                "ret_20_pct": 0.10,
                "amount_ma20": 1_000_000_000,
                "trend_slope_20_pct": 0.01,
                "distance_to_high_pct": -0.01,
            },
            {
                "symbol": "300001",
                "timestamp": "2026-06-12",
                "stage": "watch",
                "score": 62.0,
                "volume_ratio": 4.2,
                "ret_20_pct": 0.35,
                "amount_ma20": 300_000_000,
                "trend_slope_20_pct": 0.02,
                "distance_to_high_pct": -0.03,
            },
            {
                "symbol": "510300",
                "timestamp": "2026-06-12",
                "stage": "near_breakout",
                "score": 99.0,
                "volume_ratio": 1.1,
                "ret_20_pct": 0.02,
                "amount_ma20": 5_000_000_000,
            },
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "600160",
                "name": "巨化股份",
                "sentiment_score": 70.0,
                "hot_rank": 80,
                "top_keywords": "半导体概念、液冷概念、化工原料",
            },
            {
                "symbol": "300001",
                "name": "测试股份",
                "sentiment_score": 60.0,
                "hot_rank": 100,
                "top_keywords": "其他概念",
            },
            {
                "symbol": "510300",
                "name": "沪深300ETF",
                "sentiment_score": 99.0,
                "hot_rank": 1,
                "top_keywords": "ETF",
            },
        ]
    )
    theme = pd.DataFrame(
        [
            {"theme": "半导体", "theme_score": 50.0},
            {"theme": "化学制品", "theme_score": 40.0},
        ]
    )
    profiles = pd.DataFrame(
        [
            {"symbol": "600160", "industry": "化学原料和化学制品制造业", "listing_date": "1998-06-26"},
            {"symbol": "300001", "industry": "测试行业", "listing_date": "2026-01-01"},
        ]
    )
    risk_notices = pd.DataFrame(
        [
            {"symbol": "600160", "risk_notice_count": 0, "risk_notice_titles": ""},
            {"symbol": "300001", "risk_notice_count": 2, "risk_notice_titles": "问询函；减持公告"},
        ]
    )

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        risk_notices=risk_notices,
        target_date="2026-06-12",
    )

    leader = result.iloc[0]
    laggard = result[result["symbol"] == "300001"].iloc[0]

    assert leader["symbol"] == "600160"
    assert "510300" not in set(result["symbol"])
    assert leader["matched_theme"] == "半导体"
    assert leader["theme_bonus"] > 0
    assert leader["action_bucket"] == "主攻-A2启动确认"
    assert leader["risk_level"] == "低"
    assert laggard["volume_overheat_penalty"] == 8.0
    assert laggard["ret20_overheat_penalty"] == 10.0
    assert laggard["risk_notice_penalty"] == 10.0
    assert laggard["new_stock_penalty"] == 5.0
    assert laggard["risk_level"] == "高"
    assert laggard["action_bucket"] == "回避-风险优先"


def test_build_research_candidates_classifies_trend_pullback_as_a3() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "300548",
                "timestamp": "2026-06-12",
                "stage": "trend_resume",
                "setup_phase": "强趋势再启动",
                "score": 72.0,
                "volume_ratio": 1.4,
                "ret_20_pct": 0.08,
                "ret_60_pct": 0.42,
                "drawdown_from_high_pct": -0.12,
                "close_vs_trend_pct": 0.22,
                "amount_ma20": 1_000_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "300548",
                "name": "长芯博创",
                "sentiment_score": 70.0,
                "core_news_count": 1,
                "top_keywords": "光通信、半导体",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 60.0}])
    profiles = pd.DataFrame(
        [{"symbol": "300548", "industry": "计算机、通信和其他电子设备制造业", "listing_date": "2016-08-12"}]
    )

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        target_date="2026-06-12",
    )

    leader = result.iloc[0]
    assert leader["research_tier"] == "A3"
    assert leader["action_bucket"] == "主攻-A3趋势延续"
    assert leader["setup_phase"] == "强趋势再启动"
    assert leader["stage_bonus"] > 0


def test_build_research_candidates_marks_strong_theme_b2_as_replenish_watch() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "688001",
                "timestamp": "2026-06-12",
                "stage": "trend_pullback",
                "setup_phase": "强趋势回踩",
                "score": 48.0,
                "volume_ratio": 1.2,
                "ret_20_pct": 0.08,
                "ret_60_pct": 0.10,
                "drawdown_from_high_pct": -0.08,
                "close_vs_trend_pct": 0.20,
                "amount_ma20": 300_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "688001",
                "name": "强芯科技",
                "sentiment_score": 40.0,
                "top_keywords": "半导体、存储芯片",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 120.0}])
    profiles = pd.DataFrame(
        [{"symbol": "688001", "industry": "计算机、通信和其他电子设备制造业", "listing_date": "2020-01-01"}]
    )

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        target_date="2026-06-12",
    )

    row = result.iloc[0]
    assert row["research_tier"] == "B2"
    assert bool(row["is_strong_theme_candidate"]) is True
    assert row["b2_subtype"] == "B2a"
    assert row["action_bucket"] == "补票-B2a主线扩散"
    assert "主线扩散补涨" in row["upgrade_hint"]


def test_build_research_candidates_splits_b2b_theme_watch() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "688002",
                "timestamp": "2026-06-12",
                "stage": "pre_breakout",
                "setup_phase": "低位潜伏观察",
                "score": 48.0,
                "volume_ratio": 0.8,
                "ret_20_pct": 0.08,
                "ret_60_pct": 0.10,
                "drawdown_from_high_pct": -0.08,
                "close_vs_trend_pct": 0.08,
                "amount_ma20": 300_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "688002",
                "name": "待确认科技",
                "sentiment_score": 40.0,
                "top_keywords": "半导体、存储芯片",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 120.0}])
    profiles = pd.DataFrame(
        [{"symbol": "688002", "industry": "计算机、通信和其他电子设备制造业", "listing_date": "2020-01-01"}]
    )

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        target_date="2026-06-12",
    )

    row = result.iloc[0]
    assert row["research_tier"] == "B2"
    assert row["b2_subtype"] == "B2b"
    assert row["action_bucket"] == "观察-B2b主题待确认"
    assert "主题待确认" in row["upgrade_hint"]
