from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from quant_a_stock.research import pipeline
from quant_a_stock.research.pipeline import ResearchPipelineConfig
from quant_a_stock.research.pipeline import run_research_pipeline


def test_run_research_pipeline_finalizes_structured_outputs(tmp_path: Path, monkeypatch) -> None:
    candidates = pd.DataFrame(
        [
            {
                "symbol": "002137",
                "name": "实益达",
                "research_tier": "A2",
                "action_bucket": "主攻-A2启动确认",
                "research_score": 72,
                "risk_level": "低",
            }
        ]
    )

    monkeypatch.setattr(
        pipeline,
        "_latest_research_reports",
        lambda target_date, reports_dir: {"research_candidates": tmp_path / "research_candidates.csv"},
    )
    monkeypatch.setattr(pipeline, "save_research_snapshot", lambda **kwargs: tmp_path / "snapshot")
    monkeypatch.setattr(
        pipeline,
        "build_daily_research_summary",
        lambda **kwargs: SimpleNamespace(candidates=candidates),
    )
    monkeypatch.setattr(pipeline, "save_daily_research_summary_markdown", lambda summary, top: tmp_path / "daily.md")
    monkeypatch.setattr(
        pipeline,
        "save_report",
        lambda rows, report_type, reports_dir=None, date_prefix=None: tmp_path / f"{report_type}.csv",
    )
    monkeypatch.setattr(pipeline, "load_candidates_for_decision_signals", lambda **kwargs: candidates)
    monkeypatch.setattr(pipeline, "load_holdings_file", lambda: pd.DataFrame())
    monkeypatch.setattr(
        pipeline,
        "save_fundamental_watchlist_context",
        lambda watchlist, target_date, plan_date: SimpleNamespace(path=tmp_path / "fundamental.json"),
    )
    monkeypatch.setattr(
        pipeline,
        "save_research_context_pack",
        lambda **kwargs: SimpleNamespace(path=tmp_path / "context.json"),
    )

    result = run_research_pipeline(
        ResearchPipelineConfig(
            target_date="2026-07-08",
            plan_date="2026-07-09",
            reports_dir=tmp_path,
        )
    )

    assert result.target_date == "2026-07-08"
    assert result.plan_date == "2026-07-09"
    assert result.artifacts["decision_signals"] == tmp_path / "decision_signals.csv"
    assert result.artifacts["fundamental_watchlist"] == tmp_path / "fundamental_watchlist.csv"
    assert result.artifacts["fundamental_watchlist_context"] == tmp_path / "fundamental.json"
    assert [step.name for step in result.steps] == [
        "snapshot",
        "daily_summary",
        "decision_signals",
        "fundamental_watchlist",
        "context_pack",
        "warehouse_ingest",
    ]
    assert result.steps[-1].status == "skipped"
