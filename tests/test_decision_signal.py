from __future__ import annotations

import pandas as pd

from quant_a_stock.research.decision_signal import DECISION_SIGNAL_VERSION
from quant_a_stock.research.decision_signal import build_decision_signals


def test_build_decision_signals_maps_core_and_watch_buckets() -> None:
    candidates = pd.DataFrame(
        [
            {
                "symbol": "2137",
                "name": "实益达",
                "research_tier": "A2",
                "action_bucket": "主攻-A2启动确认",
                "research_score": 72.0,
                "risk_level": "低",
                "total_penalty": 0,
                "matched_theme": "半导体",
                "stage": "near_breakout",
                "setup_phase": "接近突破确认",
                "core_news_count": 1,
            },
            {
                "symbol": "600999",
                "name": "招商证券",
                "research_tier": "B2",
                "action_bucket": "观察-B2s主线突发待确认",
                "research_score": 56.0,
                "risk_level": "中",
                "total_penalty": 0,
                "matched_theme": "证券",
                "stage": "accumulation",
            },
            {
                "symbol": "300000",
                "name": "风险样本",
                "research_tier": "C",
                "action_bucket": "回避-风险优先",
                "research_score": 40.0,
                "risk_level": "高",
                "risk_tags": "公告风险",
            },
        ]
    )

    signals = build_decision_signals(candidates, target_date="2026-07-08", plan_date="2026-07-09")

    assert signals.loc[0, "symbol"] == "002137"
    assert signals.loc[0, "signal_type"] == "buy_watch"
    assert signals.loc[0, "confidence"] == "high"
    assert signals.loc[0, "expected_horizon"] == "3-15d"
    assert signals.loc[1, "signal_type"] == "upgrade_watch"
    assert signals.loc[1, "expected_horizon"] == "1-5d"
    assert signals.loc[2, "signal_type"] == "avoid"
    assert signals.loc[2, "decision_signal_version"] == DECISION_SIGNAL_VERSION
