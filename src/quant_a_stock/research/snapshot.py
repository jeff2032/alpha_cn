from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.io_utils import atomic_copy
from quant_a_stock.io_utils import atomic_write_text


SNAPSHOT_ROOT = DEFAULT_PATHS.root / "data" / "snapshots" / "research"


def save_research_snapshot(
    *,
    target_date: str,
    reports: dict[str, Path | None],
    rebuild_run_id: str | None = None,
) -> Path:
    snapshot_dir = SNAPSHOT_ROOT / target_date
    if rebuild_run_id:
        snapshot_dir = SNAPSHOT_ROOT / "rebuilds" / target_date / rebuild_run_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = snapshot_dir / "metadata.json"

    if metadata_path.exists():
        _verify_existing_snapshot(snapshot_dir, reports)
        return snapshot_dir

    copied: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for name, source in reports.items():
        if source is None:
            continue
        source_path = Path(source)
        if not source_path.exists():
            continue
        suffix = source_path.suffix.lower() or ".csv"
        target_path = snapshot_dir / f"{name}{suffix}"
        source_hash = _file_sha256(source_path)
        if target_path.exists():
            target_hash = _file_sha256(target_path)
            if source_hash != target_hash:
                raise RuntimeError(
                    f"研究快照不可覆盖: {target_path} 已存在且内容不同。"
                    "如需保留重建结果，请传入 rebuild_run_id。"
                )
        else:
            atomic_copy(source_path, target_path)
        copied[name] = str(source_path)
        hashes[name] = source_hash

    metadata = {
        "target_date": target_date,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_reports": copied,
        "source_sha256": hashes,
        "snapshot_mode": "rebuild" if rebuild_run_id else "canonical",
        "rebuild_run_id": rebuild_run_id or "",
    }
    atomic_write_text(
        metadata_path,
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return snapshot_dir


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_existing_snapshot(snapshot_dir: Path, reports: dict[str, Path | None]) -> None:
    for name, source in reports.items():
        if source is None:
            continue
        source_path = Path(source)
        if not source_path.exists():
            continue
        suffix = source_path.suffix.lower() or ".csv"
        target_path = snapshot_dir / f"{name}{suffix}"
        if not target_path.exists() or _file_sha256(source_path) != _file_sha256(target_path):
            raise RuntimeError(
                f"研究快照不可覆盖: {snapshot_dir} 已冻结，且 {name} 与现有内容不同。"
                "如需保留重建结果，请传入 rebuild_run_id。"
            )
