from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.data_lifecycle import _build_checks


def test_closed_loop_marks_empty_tables_and_missing_obsidian_outputs(tmp_path: Path) -> None:
    status = pd.DataFrame(
        [
            {"table": "research_candidates", "rows": 0, "last_target_date": ""},
            {"table": "money_flow", "rows": 0, "last_target_date": ""},
        ]
    )

    checks = _build_checks(
        status=status,
        target_date="2026-07-09",
        plan_date="2026-07-10",
        obsidian_root=tmp_path,
    )

    candidate = checks[checks["check"] == "warehouse_table:research_candidates"].iloc[0]
    money_flow = checks[checks["check"] == "warehouse_table:money_flow"].iloc[0]
    digest = checks[checks["check"] == "obsidian_review_digest"].iloc[0]
    assert candidate["status"] == "FAIL"
    assert money_flow["status"] == "WARN"
    assert digest["status"] == "WARN"
    assert "缺失" in digest["detail"]


def test_closed_loop_distinguishes_optional_and_deferred_tables(tmp_path: Path) -> None:
    status = pd.DataFrame(
        [
            {"table": "iwencai_import", "rows": 0, "last_target_date": ""},
            {"table": "research_outcome_daily", "rows": 12, "last_target_date": "2026-07-22"},
        ]
    )

    checks = _build_checks(
        status=status,
        target_date="2026-07-23",
        plan_date=None,
        obsidian_root=tmp_path,
    )

    iwencai = checks[checks["check"] == "warehouse_table:iwencai_import"].iloc[0]
    outcome = checks[checks["check"] == "warehouse_table:research_outcome_daily"].iloc[0]
    assert iwencai["status"] == "OPTIONAL"
    assert outcome["status"] == "PENDING"
    assert "下一交易日" in outcome["detail"]
