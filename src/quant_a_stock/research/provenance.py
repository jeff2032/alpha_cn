from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.research.candidates import ResearchCandidateConfig
from quant_a_stock.research.version import CANDIDATE_MODEL_VERSION
from quant_a_stock.research.version import DECISION_SIGNAL_VERSION
from quant_a_stock.research.version import FACTOR_SCHEMA_VERSION
from quant_a_stock.research.version import FUNDAMENTAL_WATCHLIST_VERSION
from quant_a_stock.research.version import WAREHOUSE_SCHEMA_VERSION


def build_run_provenance(
    report_index: pd.DataFrame,
    *,
    run_parameters: dict | None = None,
) -> dict[str, object]:
    parameters = run_parameters or default_research_parameters()
    parameter_json = canonical_json(parameters)
    source_rows = []
    for _, row in report_index.iterrows():
        path_text = str(row.get("source_path", "") or "")
        source_rows.append(
            {
                "report_type": str(row.get("report_type", "") or ""),
                "status": str(row.get("status", "") or ""),
                "row_count": int(pd.to_numeric(pd.Series([row.get("row_count", 0)]), errors="coerce").fillna(0).iloc[0]),
                "source_sha256": file_sha256(Path(path_text)) if path_text else "",
            }
        )
    source_json = canonical_json(source_rows)
    commit, dirty = git_revision(DEFAULT_PATHS.root)
    ready = sum(item["status"] in {"ingested", "indexed", "derived"} for item in source_rows)
    return {
        "code_commit": commit,
        "code_dirty": dirty,
        "parameters_json": parameter_json,
        "parameter_hash": text_sha256(parameter_json),
        "source_coverage_json": source_json,
        "source_fingerprint": text_sha256(source_json),
        "source_ready": ready,
        "source_total": len(source_rows),
    }


def default_research_parameters() -> dict[str, object]:
    return {
        "candidate_config": asdict(ResearchCandidateConfig()),
        "candidate_model_version": CANDIDATE_MODEL_VERSION,
        "factor_schema_version": FACTOR_SCHEMA_VERSION,
        "decision_signal_version": DECISION_SIGNAL_VERSION,
        "fundamental_watchlist_version": FUNDAMENTAL_WATCHLIST_VERSION,
        "warehouse_schema_version": WAREHOUSE_SCHEMA_VERSION,
    }


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision(root: Path) -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        )
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return "unknown", False
