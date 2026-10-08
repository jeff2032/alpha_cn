from __future__ import annotations

import pandas as pd

from quant_a_stock.research.berkshire_handoff import build_long_cycle_berkshire_handoff


def test_long_cycle_handoff_requires_repeated_clean_a1_certification() -> None:
    signals = pd.DataFrame(
        [
            {
                "symbol": "000001",
                "name": "合格样本",
                "research_tier": "A1",
                "action_bucket": "观察-A1低位潜伏",
                "signal_type": "watch",
                "risk_level": "低",
                "deep_research_eligible": True,
                "research_horizon": "10-60d",
                "plan_date": "2026-08-03",
            },
            {
                "symbol": "000002",
                "name": "首日样本",
                "research_tier": "A1",
                "action_bucket": "观察-A1低位潜伏",
                "signal_type": "watch",
                "risk_level": "低",
                "deep_research_eligible": True,
            },
        ]
    )
    lifecycles = pd.DataFrame(
        [
            {
                "symbol": "000001",
                "name": "合格样本",
                "status": "active",
                "current_tier": "A1",
                "days_observed": 5,
                "days_since_entry": 8,
                "current_score": 66,
                "score_delta": 3,
                "has_downgrade": False,
                "tracking_window_days": 60,
                "last_evaluated_date": "2026-07-31",
                "risk_level": "低",
            },
            {
                "symbol": "000002",
                "name": "首日样本",
                "status": "active",
                "current_tier": "A1",
                "days_observed": 1,
                "days_since_entry": 1,
                "current_score": 70,
                "score_delta": 0,
                "has_downgrade": False,
                "tracking_window_days": 60,
                "last_evaluated_date": "2026-07-31",
                "risk_level": "低",
            },
        ]
    )

    handoff = build_long_cycle_berkshire_handoff(
        signals,
        lifecycles,
        target_date="2026-07-31",
        plan_date="2026-08-03",
    )

    assert list(handoff["symbol"]) == ["000001"]
    assert handoff.iloc[0]["primary_skill"] == "investment-research"
    assert "deep-company-series" in handoff.iloc[0]["skill_chain"]
