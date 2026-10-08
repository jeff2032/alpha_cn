from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS


BERKSHIRE_HANDOFF_VERSION = "berkshire_handoff_v2026_08_02_long_cycle_a1"
BERKSHIRE_CONTEXT_ROOT = DEFAULT_PATHS.root / "data" / "context" / "berkshire_long_cycle"

BERKSHIRE_HANDOFF_COLUMNS = [
    "target_date",
    "plan_date",
    "symbol",
    "name",
    "handoff_priority",
    "handoff_score",
    "research_tier",
    "action_bucket",
    "days_observed",
    "days_since_entry",
    "current_score",
    "score_delta",
    "research_horizon",
    "tracking_window_days",
    "risk_level",
    "risk_tags",
    "reason_tags",
    "theme",
    "primary_skill",
    "skill_chain",
    "deep_research_reason",
    "deep_research_questions",
    "handoff_status",
    "berkshire_handoff_version",
]


def build_long_cycle_berkshire_handoff(
    decision_signals: pd.DataFrame,
    lifecycles: pd.DataFrame,
    *,
    target_date: str,
    plan_date: str | None = None,
    top: int = 5,
    min_days_observed: int = 3,
    min_score: float = 58.0,
) -> pd.DataFrame:
    if decision_signals.empty or lifecycles.empty:
        return pd.DataFrame(columns=BERKSHIRE_HANDOFF_COLUMNS)

    signals = decision_signals.copy()
    signals["symbol"] = signals["symbol"].astype(str).str.zfill(6)
    for column, default in {
        "research_tier": "",
        "risk_level": "",
        "signal_type": "",
        "deep_research_eligible": False,
    }.items():
        if column not in signals.columns:
            signals[column] = default
    eligible = (
        signals["research_tier"].eq("A1")
        & signals["risk_level"].eq("低")
        & ~signals["signal_type"].eq("avoid")
    )
    if "deep_research_eligible" in signals.columns:
        eligible &= signals["deep_research_eligible"].map(_as_bool)
    signals = signals[eligible].copy()
    if signals.empty:
        return pd.DataFrame(columns=BERKSHIRE_HANDOFF_COLUMNS)

    life = lifecycles.copy()
    life["symbol"] = life["symbol"].astype(str).str.zfill(6)
    for column, default in {
        "status": "",
        "current_tier": "",
        "days_observed": 0,
        "days_since_entry": 0,
        "current_score": 0.0,
        "score_delta": 0.0,
        "has_downgrade": False,
        "risk_level": "",
    }.items():
        if column not in life.columns:
            life[column] = default
    life = life.sort_values(["symbol", "last_evaluated_date"], ascending=[True, False]).drop_duplicates("symbol")
    life = life[
        life["status"].eq("active")
        & life["current_tier"].eq("A1")
        & (pd.to_numeric(life["days_observed"], errors="coerce").fillna(0) >= min_days_observed)
        & (pd.to_numeric(life["current_score"], errors="coerce").fillna(0) >= min_score)
        & ~life["has_downgrade"].map(_as_bool)
    ].copy()
    if life.empty:
        return pd.DataFrame(columns=BERKSHIRE_HANDOFF_COLUMNS)

    merged = signals.merge(life, on="symbol", how="inner", suffixes=("_signal", "_life"))
    if merged.empty:
        return pd.DataFrame(columns=BERKSHIRE_HANDOFF_COLUMNS)
    merged["_handoff_score"] = merged.apply(_handoff_score, axis=1)
    merged = merged.sort_values(["_handoff_score", "current_score"], ascending=[False, False])
    if top > 0:
        merged = merged.head(top)
    resolved_plan_date = plan_date or _first_text(merged, "plan_date") or target_date
    rows = [_handoff_row(row, target_date=target_date, plan_date=resolved_plan_date) for _, row in merged.iterrows()]
    return pd.DataFrame(rows, columns=BERKSHIRE_HANDOFF_COLUMNS)


def save_long_cycle_berkshire_context(
    handoff: pd.DataFrame,
    *,
    target_date: str,
    plan_date: str,
    output_root: Path | None = None,
) -> Path:
    root = output_root or BERKSHIRE_CONTEXT_ROOT
    output_dir = root / target_date
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"berkshire_long_cycle_plan_{plan_date}.json"
    payload = {
        "metadata": {
            "schema_version": BERKSHIRE_HANDOFF_VERSION,
            "target_date": target_date,
            "plan_date": plan_date,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "policy": {
            "scope": "只处理经 alpha_cn 连续认证的低风险 A1，不替代量化扫盘。",
            "tracking_note": "A1 可研究跟踪 60 个交易日，但量化执行最长 20 日并每 5 日重新认证。",
            "skill_usage": "先去劣，再做四大师综合研究；只有通过后才进入公司长文或论文跟踪。",
        },
        "handoff": [_json_ready(item) for item in handoff.to_dict("records")],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _handoff_score(row: pd.Series) -> float:
    score = _number(row.get("current_score"))
    score += min(_number(row.get("days_observed")), 10.0) * 1.5
    if _number(row.get("score_delta")) >= 0:
        score += 5.0
    risk_tags = _text(row.get("risk_tags_life")) or _text(row.get("risk_tags_signal"))
    if not risk_tags or risk_tags == "无明显风险":
        score += 5.0
    return round(score, 2)


def _handoff_row(row: pd.Series, *, target_date: str, plan_date: str) -> dict[str, Any]:
    days_observed = int(_number(row.get("days_observed")))
    handoff_score = _number(row.get("_handoff_score"))
    priority = "high" if handoff_score >= 78 and days_observed >= 5 else "medium"
    risk_tags = _text(row.get("risk_tags_life")) or _text(row.get("risk_tags_signal"))
    reason_tags = _text(row.get("reason_tags_life")) or _text(row.get("reason_tags_signal"))
    theme = _text(row.get("theme")) or _text(row.get("matched_theme")) or _text(row.get("theme_cluster"))
    return {
        "target_date": target_date,
        "plan_date": plan_date,
        "symbol": _text(row.get("symbol")).zfill(6),
        "name": _text(row.get("name_signal")) or _text(row.get("name_life")),
        "handoff_priority": priority,
        "handoff_score": round(handoff_score, 2),
        "research_tier": "A1",
        "action_bucket": _text(row.get("action_bucket")) or _text(row.get("current_action_bucket")),
        "days_observed": days_observed,
        "days_since_entry": int(_number(row.get("days_since_entry"))),
        "current_score": round(_number(row.get("current_score")), 2),
        "score_delta": round(_number(row.get("score_delta")), 2),
        "research_horizon": _text(row.get("research_horizon_signal")) or "10-60d",
        "tracking_window_days": int(_number(row.get("tracking_window_days"), 60)),
        "risk_level": _text(row.get("risk_level_life")) or _text(row.get("risk_level_signal")),
        "risk_tags": risk_tags or "无明显风险",
        "reason_tags": reason_tags,
        "theme": theme,
        "primary_skill": "investment-research",
        "skill_chain": "quality-screen -> investment-research -> deep-company-series -> thesis-tracker",
        "deep_research_reason": f"A1 连续认证 {days_observed} 次，量化分层仍有效；需要验证公司质量、产业景气和估值是否支持中长周期观察。",
        "deep_research_questions": "商业模式和护城河是否清楚；景气能否传导到利润和现金流；估值隐含了什么预期；治理、减持、质押和财务风险是否可接受；什么事实会推翻长期观察逻辑",
        "handoff_status": "ready",
        "berkshire_handoff_version": BERKSHIRE_HANDOFF_VERSION,
    }


def _first_text(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns:
        return ""
    for value in frame[column]:
        text = _text(value)
        if text:
            return text
    return ""


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y", "是"}


def _number(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
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
