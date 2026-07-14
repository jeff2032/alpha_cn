from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_a_stock.research import snapshot


def test_canonical_snapshot_is_immutable_and_metadata_is_not_rewritten(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "SNAPSHOT_ROOT", tmp_path / "snapshots")
    source = tmp_path / "research_candidates.csv"
    source.write_text("symbol,score\n002137,70\n", encoding="utf-8")

    snapshot_dir = snapshot.save_research_snapshot(
        target_date="2026-07-14",
        reports={"research_candidates": source},
    )
    metadata_path = snapshot_dir / "metadata.json"
    original_metadata = metadata_path.read_text(encoding="utf-8")

    snapshot.save_research_snapshot(
        target_date="2026-07-14",
        reports={"research_candidates": source},
    )
    assert metadata_path.read_text(encoding="utf-8") == original_metadata

    source.write_text("symbol,score\n002137,80\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="不可覆盖"):
        snapshot.save_research_snapshot(
            target_date="2026-07-14",
            reports={"research_candidates": source},
        )

    rebuild_dir = snapshot.save_research_snapshot(
        target_date="2026-07-14",
        reports={"research_candidates": source},
        rebuild_run_id="rule-v2",
    )
    metadata = json.loads((rebuild_dir / "metadata.json").read_text(encoding="utf-8"))
    assert rebuild_dir == tmp_path / "snapshots" / "rebuilds" / "2026-07-14" / "rule-v2"
    assert metadata["snapshot_mode"] == "rebuild"
    assert metadata["rebuild_run_id"] == "rule-v2"

