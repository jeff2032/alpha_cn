from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from shutil import copy2

from quant_a_stock.config import DEFAULT_PATHS


SNAPSHOT_ROOT = DEFAULT_PATHS.root / "data" / "snapshots" / "research"


def save_research_snapshot(
    *,
    target_date: str,
    reports: dict[str, Path | None],
) -> Path:
    snapshot_dir = SNAPSHOT_ROOT / target_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    copied: dict[str, str] = {}
    for name, source in reports.items():
        if source is None:
            continue
        source_path = Path(source)
        if not source_path.exists():
            continue
        suffix = source_path.suffix.lower() or ".csv"
        target_path = snapshot_dir / f"{name}{suffix}"
        copy2(source_path, target_path)
        copied[name] = str(source_path)

    metadata = {
        "target_date": target_date,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_reports": copied,
    }
    (snapshot_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return snapshot_dir
