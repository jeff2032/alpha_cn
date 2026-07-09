from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.research import context_pack
from quant_a_stock.research.context_pack import save_research_context_pack
from quant_a_stock.research.summary import DailyResearchSummary


def test_save_research_context_pack_exports_structured_json(tmp_path: Path, monkeypatch) -> None:
    def fake_summary(*, target_date: str, snapshot_dir: Path | None = None) -> DailyResearchSummary:
        candidates = pd.DataFrame(
            [
                {
                    "symbol": "002137",
                    "name": "实益达",
                    "research_tier": "A2",
                    "action_bucket": "主攻-A2启动确认",
                    "research_score": 72.5,
                    "stage": "near_breakout",
                    "matched_theme": "半导体",
                    "theme_cluster": "半导体链",
                    "risk_level": "低",
                    "risk_tags": "",
                },
                {
                    "symbol": "600999",
                    "name": "招商证券",
                    "research_tier": "B2",
                    "action_bucket": "观察-B2b主题待确认",
                    "research_score": 55.0,
                    "stage": "watch",
                    "matched_theme": "证券",
                    "theme_cluster": "金融",
                    "risk_level": "中",
                    "risk_tags": "位置偏高",
                },
            ]
        )
        return DailyResearchSummary(
            target_date=target_date,
            snapshot_dir=tmp_path / "snapshot",
            market={"score": 71.5, "regime": "震荡偏强", "advice": "先看主线承接"},
            market_components=pd.DataFrame([{"symbol": "510300", "score": 70.0}]),
            theme=pd.DataFrame([{"theme": "半导体", "candidate_count": 10, "theme_score": 88.0}]),
            candidates=candidates,
        )

    monkeypatch.setattr(context_pack, "build_daily_research_summary", fake_summary)
    pd.DataFrame(
        [
            {
                "table": "by_tier",
                "tier": "A2",
                "count": 3,
                "avg_ret": 0.05,
                "win_rate": 0.67,
            }
        ]
    ).to_csv(tmp_path / "research_review_summary_20260708_080000.csv", index=False)

    result = save_research_context_pack(
        target_date="2026-07-08",
        plan_date="2026-07-09",
        reports_dir=tmp_path,
        output_root=tmp_path / "context",
    )

    assert result.path.exists()
    assert result.path.name == "plan_2026-07-09.json"
    assert result.pack["metadata"]["target_date"] == "2026-07-08"
    assert result.pack["metadata"]["plan_date"] == "2026-07-09"
    assert result.pack["candidate_context"]["total"] == 2
    assert result.pack["candidate_context"]["core_candidates"][0]["symbol"] == "002137"
    assert result.pack["decision_signal_context"]["signals"][0]["signal_type"] == "buy_watch"
    assert result.pack["fundamental_watchlist_context"]["watchlist"][0]["symbol"] == "002137"
    assert result.pack["fundamental_watchlist_context"]["watchlist"][0]["suggested_ai_berkshire_skill"] == (
        "investment-checklist"
    )
    assert result.pack["review_context"]["summary"][0]["tier"] == "A2"
