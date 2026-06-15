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
    assert leader["matched_theme"] == "半导体"
    assert leader["theme_bonus"] > 0
    assert laggard["volume_overheat_penalty"] == 8.0
    assert laggard["ret20_overheat_penalty"] == 10.0
    assert laggard["risk_notice_penalty"] == 10.0
    assert laggard["new_stock_penalty"] == 5.0
