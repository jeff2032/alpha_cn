from __future__ import annotations

import pandas as pd

from quant_a_stock.research.candidates import build_research_candidates
from quant_a_stock.research.version import CANDIDATE_MODEL_VERSION
from quant_a_stock.research.version import FACTOR_SCHEMA_VERSION


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
    assert laggard["risk_notice_penalty"] == 2.0
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
    assert leader["action_bucket"] == "短线-A3一三日确认"
    assert leader["setup_phase"] == "强趋势再启动"
    assert leader["stage_bonus"] > 0


def test_build_research_candidates_demotes_crowded_a3_to_watch() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "300549",
                "timestamp": "2026-06-12",
                "stage": "trend_resume",
                "setup_phase": "强趋势再启动",
                "score": 72.0,
                "volume_ratio": 1.4,
                "ret_20_pct": 0.08,
                "ret_60_pct": 0.50,
                "drawdown_from_high_pct": -0.08,
                "close_vs_trend_pct": 0.22,
                "monthly_position_pct": 0.79,
                "price_position_pct": 0.70,
                "amount_ma20": 1_000_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "300549",
                "name": "高位趋势",
                "sentiment_score": 70.0,
                "core_news_count": 1,
                "top_keywords": "光通信、半导体",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 60.0}])
    profiles = pd.DataFrame(
        [{"symbol": "300549", "industry": "计算机、通信和其他电子设备制造业", "listing_date": "2016-08-12"}]
    )

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        target_date="2026-06-12",
    )

    row = result.iloc[0]
    assert row["research_tier"] == "A3"
    assert row["action_bucket"] == "观察-A3高波动"
    assert "趋势高位拥挤" in row["risk_tags"]


def test_build_research_candidates_keeps_hot_a3_out_of_main_attack() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "300550",
                "timestamp": "2026-06-12",
                "stage": "trend_resume",
                "setup_phase": "强趋势再启动",
                "score": 72.0,
                "volume_ratio": 1.5,
                "ret_20_pct": 0.16,
                "ret_60_pct": 0.42,
                "drawdown_from_high_pct": -0.08,
                "close_vs_trend_pct": 0.22,
                "monthly_position_pct": 0.55,
                "price_position_pct": 0.60,
                "amount_ma20": 1_000_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "300550",
                "name": "偏热趋势",
                "sentiment_score": 70.0,
                "core_news_count": 1,
                "top_keywords": "光通信、半导体",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 60.0}])
    profiles = pd.DataFrame(
        [{"symbol": "300550", "industry": "计算机、通信和其他电子设备制造业", "listing_date": "2016-08-12"}]
    )

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        target_date="2026-06-12",
    )

    row = result.iloc[0]
    assert row["research_tier"] == "A3"
    assert row["risk_level"] == "中"
    assert row["action_bucket"] == "观察-A3高波动"
    assert "20日涨幅偏热" in row["risk_tags"]


def test_build_research_candidates_demotes_a3_without_active_mainline() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "300551",
                "timestamp": "2026-07-08",
                "stage": "trend_resume",
                "setup_phase": "强趋势再启动",
                "score": 72.0,
                "volume_ratio": 1.3,
                "ret_20_pct": 0.08,
                "ret_60_pct": 0.38,
                "drawdown_from_high_pct": -0.08,
                "close_vs_trend_pct": 0.20,
                "monthly_position_pct": 0.45,
                "price_position_pct": 0.55,
                "amount_ma20": 1_000_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "300551",
                "name": "弱主题趋势",
                "sentiment_score": 48.0,
                "core_news_count": 1,
                "top_keywords": "普通制造",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 80.0}])
    profiles = pd.DataFrame([{"symbol": "300551", "industry": "通用设备", "listing_date": "2016-08-12"}])

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        target_date="2026-07-08",
    )

    row = result.iloc[0]
    assert row["research_tier"] == "A3"
    assert row["risk_level"] == "低"
    assert row["action_bucket"] == "观察-A3高波动"


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
                "core_news_count": 1,
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
    assert row["action_bucket"] == "升级-B2三五日观察"
    assert "升级观察" in row["upgrade_hint"]


def test_build_research_candidates_marks_mainline_surge_replenish() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "688003",
                "timestamp": "2026-06-12",
                "stage": "near_breakout",
                "setup_phase": "接近突破确认",
                "score": 36.0,
                "volume_ratio": 2.7,
                "ret_20_pct": 0.14,
                "ret_60_pct": 0.12,
                "drawdown_from_high_pct": -0.08,
                "close_vs_trend_pct": 0.10,
                "price_position_pct": 0.72,
                "amount_ma20": 300_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "688003",
                "name": "突发科技",
                "sentiment_score": 58.0,
                "top_keywords": "半导体、存储芯片",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 120.0}])
    profiles = pd.DataFrame(
        [{"symbol": "688003", "industry": "计算机、通信和其他电子设备制造业", "listing_date": "2020-01-01"}]
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
    assert row["b2_subtype"] == "B2s"
    assert row["action_bucket"] == "升级-B2三五日观察"
    assert "升级观察" in row["upgrade_hint"]


def test_build_research_candidates_marks_low_position_mainline_alert_as_b2s() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "688281",
                "timestamp": "2026-07-06",
                "stage": "watch",
                "setup_phase": "主线低位突发观察",
                "score": 40.0,
                "volume_ratio": 0.95,
                "ret_20_pct": 0.05,
                "ret_60_pct": 0.08,
                "price_position_pct": 0.38,
                "monthly_position_pct": 0.42,
                "amount_ma20": 120_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "688281",
                "name": "东微半导",
                "sentiment_score": 58.0,
                "top_keywords": "半导体、功率半导体、芯片",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 120.0}])
    profiles = pd.DataFrame(
        [{"symbol": "688281", "industry": "计算机、通信和其他电子设备制造业", "listing_date": "2022-02-10"}]
    )

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        target_date="2026-07-06",
    )

    row = result.iloc[0]
    assert row["research_tier"] == "B2"
    assert row["b2_subtype"] == "B2s"
    assert row["action_bucket"] == "升级-B2三五日观察"
    assert row["risk_level"] == "低"


def test_build_research_candidates_marks_deep_low_software_mainline_alert_as_b2s() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "300369",
                "timestamp": "2026-07-08",
                "stage": "watch",
                "setup_phase": "低位主线突发观察",
                "score": 40.0,
                "volume_ratio": 0.38,
                "ret_20_pct": -0.11,
                "ret_60_pct": -0.08,
                "price_position_pct": 0.02,
                "monthly_position_pct": 0.20,
                "amount_ma20": 120_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "300369",
                "name": "绿盟科技",
                "sentiment_score": 58.0,
                "top_keywords": "网络安全、信创、软件开发",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "软件开发", "theme_score": 120.0}])
    profiles = pd.DataFrame([{"symbol": "300369", "industry": "软件开发", "listing_date": "2014-01-29"}])

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        target_date="2026-07-08",
    )

    row = result.iloc[0]
    assert row["research_tier"] == "B2"
    assert row["b2_subtype"] == "B2s"
    assert row["action_bucket"] == "升级-B2三五日观察"
    assert row["risk_level"] == "低"


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


def test_build_research_candidates_uses_external_money_and_risk_factors() -> None:
    scan = pd.DataFrame(
        [
            {
                "symbol": "002137",
                "timestamp": "2026-07-08",
                "stage": "near_breakout",
                "setup_phase": "接近突破确认",
                "score": 60.0,
                "volume_ratio": 1.2,
                "ret_20_pct": 0.05,
                "ret_60_pct": 0.10,
                "price_position_pct": 0.45,
                "monthly_position_pct": 0.40,
                "amount_ma20": 300_000_000,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [
            {
                "symbol": "002137",
                "name": "实益达",
                "sentiment_score": 60.0,
                "core_news_count": 1,
                "top_keywords": "半导体",
            }
        ]
    )
    theme = pd.DataFrame([{"theme": "半导体", "theme_score": 100.0}])
    money_flow = pd.DataFrame(
        [
            {
                "symbol": "002137",
                "money_flow_score": 80.0,
                "main_net_inflow_3d": 250_000_000,
                "positive_flow_days_5": 4,
            }
        ]
    )
    external_screen = pd.DataFrame(
        [
            {
                "symbol": "002137",
                "iwencai_hit": 1,
                "iwencai_score": 30.0,
                "iwencai_rank": 1,
                "iwencai_tags": "半导体",
            }
        ]
    )

    result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        money_flow=money_flow,
        external_screen=external_screen,
        target_date="2026-07-08",
    )

    row = result.iloc[0]
    assert row["money_flow_bonus"] > 0
    assert row["external_screen_bonus"] > 0
    assert row["candidate_model_version"] == CANDIDATE_MODEL_VERSION
    assert row["factor_schema_version"] == FACTOR_SCHEMA_VERSION
    assert row["research_tier"] in {"A2", "B1"}
    assert row["risk_level"] == "低"

    risk_result = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        money_flow=money_flow,
        external_screen=external_screen,
        risk_notices=pd.DataFrame(
            [
                {
                    "symbol": "002137",
                    "risk_notice_count": 1,
                    "risk_notice_titles": "关于收到监管问询函的公告",
                    "risk_event_score": 8,
                    "high_risk_event_count": 1,
                    "risk_event_types": "监管问询",
                }
            ]
        ),
        target_date="2026-07-08",
    )

    risk_row = risk_result.iloc[0]
    assert risk_row["risk_event_penalty"] == 6
    assert "巨潮高风险事件" in risk_row["risk_tags"]
    assert risk_row["risk_level"] == "高"
