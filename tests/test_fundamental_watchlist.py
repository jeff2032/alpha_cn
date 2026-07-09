from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.research.fundamental_watchlist import build_fundamental_watchlist
from quant_a_stock.research.fundamental_watchlist import save_fundamental_watchlist_context


def test_build_fundamental_watchlist_prioritizes_core_and_holdings() -> None:
    signals = pd.DataFrame(
        [
            {
                "symbol": "002137",
                "name": "实益达",
                "signal_type": "buy_watch",
                "decision_bucket": "主攻",
                "action_bucket": "主攻-A2启动确认",
                "confidence": "high",
                "expected_horizon": "3-15d",
                "research_score": 72.5,
                "risk_level": "低",
                "matched_theme": "半导体",
                "theme_cluster": "半导体链",
            },
            {
                "symbol": "600999",
                "name": "招商证券",
                "signal_type": "upgrade_watch",
                "decision_bucket": "升级观察",
                "action_bucket": "观察-B2a主线扩散待升级",
                "confidence": "medium",
                "expected_horizon": "3-10d",
                "research_score": 61.0,
                "risk_level": "中",
            },
            {
                "symbol": "300999",
                "name": "高风险样本",
                "signal_type": "avoid",
                "decision_bucket": "风险回避",
                "action_bucket": "回避-风险优先",
                "confidence": "low",
                "research_score": 75.0,
                "risk_level": "高",
            },
            {
                "symbol": "300750",
                "name": "持仓样本",
                "signal_type": "watch",
                "decision_bucket": "观察",
                "action_bucket": "观察-A1低位潜伏",
                "confidence": "low",
                "expected_horizon": "10-30d",
                "research_score": 54.0,
                "risk_level": "中",
            },
        ]
    )
    holdings = pd.DataFrame([{"symbol": "300750"}])

    result = build_fundamental_watchlist(
        signals,
        target_date="2026-07-08",
        plan_date="2026-07-09",
        top=10,
        holdings=holdings,
    )

    assert "300999" not in set(result["symbol"])
    assert result.loc[0, "symbol"] == "002137"
    assert result.loc[result["symbol"] == "002137", "research_priority"].iloc[0] == "high"
    assert result.loc[result["symbol"] == "002137", "suggested_ai_berkshire_skill"].iloc[0] == "investment-checklist"
    holding = result[result["symbol"] == "300750"].iloc[0]
    assert holding["research_priority"] == "medium"
    assert holding["suggested_ai_berkshire_skill"] == "thesis-tracker"
    assert bool(holding["is_holding"]) is True


def test_save_fundamental_watchlist_context_exports_json(tmp_path: Path) -> None:
    watchlist = pd.DataFrame(
        [
            {
                "target_date": "2026-07-08",
                "plan_date": "2026-07-09",
                "symbol": "002137",
                "name": "实益达",
                "research_priority": "high",
                "suggested_ai_berkshire_skill": "investment-checklist",
                "handoff_reason": "优先级:high",
                "ai_berkshire_questions": "是否具备基本面支撑",
                "source_signal_type": "buy_watch",
            }
        ]
    )

    result = save_fundamental_watchlist_context(
        watchlist,
        target_date="2026-07-08",
        plan_date="2026-07-09",
        output_root=tmp_path / "context",
    )

    assert result.path.exists()
    assert result.path.name == "ai_berkshire_plan_2026-07-09.json"
    assert result.payload["summary"]["total"] == 1
    assert result.payload["watchlist"][0]["symbol"] == "002137"
