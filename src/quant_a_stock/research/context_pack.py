from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.research.decision_signal import build_decision_signals
from quant_a_stock.research.fundamental_watchlist import build_fundamental_watchlist
from quant_a_stock.research.snapshot import SNAPSHOT_ROOT
from quant_a_stock.research.summary import build_daily_research_summary
from quant_a_stock.research.version import CANDIDATE_MODEL_VERSION


CONTEXT_PACK_SCHEMA_VERSION = "research_context_pack_v2026_07_09"
CONTEXT_ROOT = DEFAULT_PATHS.root / "data" / "context" / "research"


@dataclass(frozen=True)
class ContextPackResult:
    target_date: str
    plan_date: str
    path: Path
    pack: dict[str, Any]


def save_research_context_pack(
    *,
    target_date: str,
    plan_date: str | None = None,
    top: int = 30,
    snapshot_dir: Path | None = None,
    reports_dir: Path | None = None,
    output_root: Path | None = None,
) -> ContextPackResult:
    resolved_plan_date = plan_date or target_date
    pack = build_research_context_pack(
        target_date=target_date,
        plan_date=resolved_plan_date,
        top=top,
        snapshot_dir=snapshot_dir,
        reports_dir=reports_dir,
    )
    root = output_root or CONTEXT_ROOT
    output_dir = root / target_date
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"plan_{resolved_plan_date}.json"
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return ContextPackResult(target_date=target_date, plan_date=resolved_plan_date, path=path, pack=pack)


def build_research_context_pack(
    *,
    target_date: str,
    plan_date: str,
    top: int = 30,
    snapshot_dir: Path | None = None,
    reports_dir: Path | None = None,
) -> dict[str, Any]:
    reports_root = reports_dir or DEFAULT_PATHS.reports
    snapshot = snapshot_dir or SNAPSHOT_ROOT / target_date
    summary = build_daily_research_summary(target_date=target_date, snapshot_dir=snapshot)
    candidates = summary.candidates.copy()
    decision_signals = build_decision_signals(
        candidates,
        target_date=target_date,
        plan_date=plan_date,
        top=top,
    )
    fundamental_watchlist = build_fundamental_watchlist(
        decision_signals,
        target_date=target_date,
        plan_date=plan_date,
        top=min(top, 20),
    )

    pack = {
        "metadata": {
            "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
            "candidate_model_version": CANDIDATE_MODEL_VERSION,
            "target_date": target_date,
            "plan_date": plan_date,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_snapshot": str(snapshot),
            "source_files": _source_files(target_date=target_date, snapshot_dir=snapshot, reports_dir=reports_root),
        },
        "market_context": {
            "market": summary.market,
            "components": _records(summary.market_components, limit=20),
            "themes": _records(_select_columns(summary.theme, THEME_COLUMNS), limit=min(top, 20)),
            "theme_clusters": _theme_cluster_records(candidates, top=12),
        },
        "candidate_context": {
            "total": int(len(candidates)),
            "tier_counts": _value_counts(candidates, "research_tier"),
            "action_bucket_counts": _value_counts(candidates, "action_bucket"),
            "risk_level_counts": _value_counts(candidates, "risk_level"),
            "core_candidates": _records(_core_candidates(candidates), limit=top),
            "watch_candidates": _records(_watch_candidates(candidates), limit=top),
            "risk_candidates": _records(_risk_candidates(candidates), limit=top),
        },
        "decision_signal_context": {
            "total": int(len(decision_signals)),
            "signal_type_counts": _value_counts(decision_signals, "signal_type"),
            "decision_bucket_counts": _value_counts(decision_signals, "decision_bucket"),
            "signals": _records(decision_signals, limit=top),
        },
        "fundamental_watchlist_context": {
            "total": int(len(fundamental_watchlist)),
            "priority_counts": _value_counts(fundamental_watchlist, "research_priority"),
            "skill_counts": _value_counts(fundamental_watchlist, "suggested_ai_berkshire_skill"),
            "watchlist": _records(fundamental_watchlist, limit=min(top, 20)),
        },
        "review_context": _review_context(target_date=target_date, reports_dir=reports_root, top=top),
        "lifecycle_context": _lifecycle_context(target_date=target_date, reports_dir=reports_root, top=top),
        "portfolio_context": _portfolio_context(candidates=candidates),
    }
    return _json_ready(pack)


THEME_COLUMNS = [
    "theme",
    "candidate_count",
    "limit_up_count",
    "strong_count",
    "theme_score",
    "top_symbols",
]

CANDIDATE_COLUMNS = [
    "symbol",
    "name",
    "research_tier",
    "action_bucket",
    "research_score",
    "stage",
    "setup_phase",
    "score",
    "sentiment_score",
    "matched_theme",
    "theme_cluster",
    "industry",
    "co_rise_count",
    "risk_level",
    "risk_tags",
    "upgrade_hint",
    "top_keywords",
    "latest_core_news",
    "latest_news",
    "monthly_position_pct",
    "weekly_trend_slope_pct",
    "ret_20_pct",
    "ret_60_pct",
    "volume_ratio",
    "money_flow_score",
    "risk_event_score",
    "iwencai_score",
]

REVIEW_COLUMNS = [
    "table",
    "tier",
    "action_bucket",
    "horizon",
    "count",
    "avg_ret",
    "median_ret",
    "win_rate",
    "gt5_rate",
    "lt_minus5_rate",
    "avg_high",
    "avg_low",
    "model_bucket",
    "primary_risk_tag",
]

MISSED_COLUMNS = [
    "symbol",
    "name",
    "target_date",
    "next_date",
    "next_ret",
    "next_high_ret",
    "miss_reason",
    "risk_level",
    "risk_tags",
    "action_hint",
    "is_learnable",
    "scan_source",
    "scan_stage",
]

LIFECYCLE_COLUMNS = [
    "symbol",
    "name",
    "target_date",
    "first_entry_date",
    "day_status",
    "action_bucket",
    "research_tier",
    "research_score",
    "risk_level",
    "risk_tags",
    "days_since_entry",
    "since_entry_ret",
    "since_entry_high_ret",
    "since_entry_low_ret",
]


def _source_files(*, target_date: str, snapshot_dir: Path, reports_dir: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    for name in [
        "metadata.json",
        "research_candidates.csv",
        "market_theme.csv",
        "sentiment_watchlist.csv",
    ]:
        path = snapshot_dir / name
        if path.exists():
            sources[f"snapshot_{path.stem}"] = str(path)

    for key, pattern in {
        "daily_research_summary": "daily_research_summary_*.md",
        "research_review_summary": "research_review_summary_*.csv",
        "research_review_missed": "research_review_missed_*.csv",
        "candidate_lifecycle_daily": "candidate_lifecycle_daily_*.csv",
        "fundamental_watchlist": "fundamental_watchlist_*.csv",
    }.items():
        path = _latest_file_for_date(reports_dir, pattern, target_date)
        if path is not None:
            sources[key] = str(path)
    return sources


def _theme_cluster_records(candidates: pd.DataFrame, *, top: int) -> list[dict[str, Any]]:
    if candidates.empty or "theme_cluster" not in candidates.columns:
        return []
    score_col = "research_score" if "research_score" in candidates.columns else None
    grouped = candidates.groupby("theme_cluster", dropna=False).agg(
        candidate_count=("symbol", "count"),
        core_count=("action_bucket", lambda x: int(x.astype(str).str.startswith("主攻").sum())),
    )
    if score_col:
        grouped["avg_research_score"] = candidates.groupby("theme_cluster", dropna=False)[score_col].mean()
    grouped = grouped.reset_index().sort_values(["core_count", "candidate_count"], ascending=[False, False])
    return _records(grouped, limit=top)


def _core_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    if "action_bucket" in candidates.columns:
        frame = candidates[candidates["action_bucket"].astype(str).str.startswith("主攻")].copy()
    else:
        frame = candidates[candidates["research_tier"].isin(["A2", "A3"])].copy()
    return _candidate_projection(frame)


def _watch_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    if "action_bucket" in candidates.columns:
        mask = candidates["action_bucket"].astype(str).str.contains("观察|补票", regex=True)
        frame = candidates[mask].copy()
    else:
        frame = candidates[~candidates["research_tier"].isin(["A2", "A3"])].copy()
    return _candidate_projection(frame)


def _risk_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    mask = pd.Series(False, index=candidates.index)
    if "risk_level" in candidates.columns:
        mask = mask | candidates["risk_level"].astype(str).isin(["中", "中高", "高"])
    if "total_penalty" in candidates.columns:
        mask = mask | (pd.to_numeric(candidates["total_penalty"], errors="coerce").fillna(0) > 0)
    return _candidate_projection(candidates[mask].copy())


def _candidate_projection(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return _select_columns(frame, CANDIDATE_COLUMNS)


def _review_context(*, target_date: str, reports_dir: Path, top: int) -> dict[str, Any]:
    summary_path = _latest_file_for_date(reports_dir, "research_review_summary_*.csv", target_date)
    missed_path = _latest_file_for_date(reports_dir, "research_review_missed_*.csv", target_date)
    summary = _read_csv(summary_path)
    missed = _read_csv(missed_path)
    if not summary.empty and "table" in summary.columns:
        summary = summary[summary["table"].isin(["by_tier", "by_action_bucket", "by_model_bucket", "by_horizon"])]
    return {
        "summary": _records(_select_columns(summary, REVIEW_COLUMNS), limit=top),
        "missed_opportunities": _records(_select_columns(missed, MISSED_COLUMNS), limit=top),
    }


def _lifecycle_context(*, target_date: str, reports_dir: Path, top: int) -> dict[str, Any]:
    path = _latest_file_for_date(reports_dir, "candidate_lifecycle_daily_*.csv", target_date)
    lifecycle = _read_csv(path)
    if not lifecycle.empty and "target_date" in lifecycle.columns:
        lifecycle = lifecycle[lifecycle["target_date"].astype(str) <= target_date]
    if not lifecycle.empty and "since_entry_high_ret" in lifecycle.columns:
        lifecycle = lifecycle.sort_values("since_entry_high_ret", ascending=False)
    return {
        "tracked_count": int(len(lifecycle)),
        "strong_hits": _records(_select_columns(lifecycle, LIFECYCLE_COLUMNS), limit=top),
    }


def _portfolio_context(*, candidates: pd.DataFrame) -> dict[str, Any]:
    holdings_path = DEFAULT_PATHS.root / "data" / "manual" / "holdings.csv"
    holdings = _read_csv(holdings_path)
    if holdings.empty:
        return {"source": str(holdings_path), "holdings": [], "matched_candidates": []}
    if "symbol" in holdings.columns:
        holdings["symbol"] = holdings["symbol"].astype(str).str.zfill(6)
    matched = pd.DataFrame()
    if "symbol" in holdings.columns and "symbol" in candidates.columns:
        matched = holdings[["symbol"]].merge(_candidate_projection(candidates), on="symbol", how="inner")
    return {
        "source": str(holdings_path),
        "holdings": _records(holdings, limit=100),
        "matched_candidates": _records(matched, limit=100),
    }


def _latest_file_for_date(root: Path, pattern: str, target_date: str) -> Path | None:
    if not root.exists():
        return None
    compact = target_date.replace("-", "")
    matches = [path for path in root.glob(pattern) if compact in path.name or target_date in path.name]
    if not matches:
        return None
    return sorted(matches, key=lambda path: path.stat().st_mtime)[-1]


def _read_csv(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"symbol": str})


def _select_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[column for column in columns if column in frame.columns])
    existing = [column for column in columns if column in frame.columns]
    return frame.loc[:, existing].copy()


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    counts = frame[column].fillna("未标注").astype(str).value_counts()
    return {str(key): int(value) for key, value in counts.items()}


def _records(frame: pd.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [_json_ready(record) for record in frame.head(limit).to_dict("records")]


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value
