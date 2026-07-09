from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.research.version import FUNDAMENTAL_WATCHLIST_VERSION


FUNDAMENTAL_CONTEXT_ROOT = DEFAULT_PATHS.root / "data" / "context" / "fundamental"

FUNDAMENTAL_WATCHLIST_COLUMNS = [
    "target_date",
    "plan_date",
    "symbol",
    "name",
    "research_priority",
    "suggested_ai_berkshire_skill",
    "handoff_reason",
    "ai_berkshire_questions",
    "alpha_cn_summary",
    "source_signal_type",
    "decision_bucket",
    "action_bucket",
    "confidence",
    "expected_horizon",
    "research_score",
    "risk_level",
    "reason_tags",
    "risk_tags",
    "matched_theme",
    "theme_cluster",
    "stage",
    "setup_phase",
    "observe_condition",
    "invalid_condition",
    "position_hint",
    "is_holding",
    "source",
    "fundamental_watchlist_version",
]


@dataclass(frozen=True)
class FundamentalWatchlistContextResult:
    target_date: str
    plan_date: str
    path: Path
    payload: dict[str, Any]


def load_holdings_file(path: Path | None = None) -> pd.DataFrame:
    holdings_path = path or DEFAULT_PATHS.root / "data" / "manual" / "holdings.csv"
    if not holdings_path.exists():
        return pd.DataFrame()
    try:
        holdings = pd.read_csv(holdings_path, dtype={"symbol": str})
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if "symbol" in holdings.columns:
        holdings["symbol"] = holdings["symbol"].astype(str).str.zfill(6)
    return holdings


def build_fundamental_watchlist(
    decision_signals: pd.DataFrame,
    *,
    target_date: str,
    plan_date: str | None = None,
    top: int = 20,
    holdings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if decision_signals.empty:
        return pd.DataFrame(columns=FUNDAMENTAL_WATCHLIST_COLUMNS)

    resolved_plan_date = plan_date or target_date
    frame = decision_signals.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    for column, default in {
        "signal_type": "",
        "confidence": "",
        "risk_level": "",
        "research_score": 0.0,
    }.items():
        if column not in frame.columns:
            frame[column] = default
    holding_symbols = _holding_symbols(holdings)
    frame["is_holding"] = frame["symbol"].isin(holding_symbols)

    signal_type = frame.get("signal_type", pd.Series("", index=frame.index)).fillna("").astype(str)
    risk_level = frame.get("risk_level", pd.Series("", index=frame.index)).fillna("").astype(str)
    keep = (~signal_type.eq("avoid") & ~risk_level.isin(["中高", "高"])) | frame["is_holding"]
    frame = frame[keep].copy()
    if frame.empty:
        return pd.DataFrame(columns=FUNDAMENTAL_WATCHLIST_COLUMNS)

    frame["_priority_rank"] = frame.apply(_priority_rank, axis=1)
    frame["_signal_rank"] = frame["signal_type"].map(_SIGNAL_RANK).fillna(9)
    frame["_confidence_rank"] = frame["confidence"].map(_CONFIDENCE_RANK).fillna(9)
    frame["_score"] = pd.to_numeric(frame.get("research_score", 0), errors="coerce").fillna(0.0)
    frame = frame.sort_values(
        ["_priority_rank", "_signal_rank", "_confidence_rank", "is_holding", "_score"],
        ascending=[True, True, True, False, False],
    )
    if top and top > 0:
        frame = frame.head(top)

    rows = [_watchlist_row(row, target_date=target_date, plan_date=resolved_plan_date) for _, row in frame.iterrows()]
    output = pd.DataFrame(rows)
    return output.loc[:, FUNDAMENTAL_WATCHLIST_COLUMNS]


def save_fundamental_watchlist_context(
    watchlist: pd.DataFrame,
    *,
    target_date: str,
    plan_date: str,
    output_root: Path | None = None,
) -> FundamentalWatchlistContextResult:
    payload = build_fundamental_watchlist_context(
        watchlist,
        target_date=target_date,
        plan_date=plan_date,
    )
    root = output_root or FUNDAMENTAL_CONTEXT_ROOT
    output_dir = root / target_date
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"ai_berkshire_plan_{plan_date}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return FundamentalWatchlistContextResult(target_date=target_date, plan_date=plan_date, path=path, payload=payload)


def build_fundamental_watchlist_context(
    watchlist: pd.DataFrame,
    *,
    target_date: str,
    plan_date: str,
) -> dict[str, Any]:
    return _json_ready(
        {
            "metadata": {
                "schema_version": FUNDAMENTAL_WATCHLIST_VERSION,
                "target_date": target_date,
                "plan_date": plan_date,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            },
            "handoff_policy": {
                "alpha_cn_role": "从技术形态、主线、情绪、风险和资金流中筛出少量需要基本面验证的股票。",
                "ai_berkshire_role": "只对交接清单做深研：商业质量、景气周期、估值、财报和长期风险，不做全市场扫盘。",
                "usage_note": "这不是买卖指令；用于决定哪些票值得进一步做基本面深挖或持仓复核。",
            },
            "summary": {
                "total": int(len(watchlist)),
                "priority_counts": _value_counts(watchlist, "research_priority"),
                "skill_counts": _value_counts(watchlist, "suggested_ai_berkshire_skill"),
                "signal_type_counts": _value_counts(watchlist, "source_signal_type"),
            },
            "watchlist": _records(watchlist, limit=max(len(watchlist), 1)),
        }
    )


_SIGNAL_RANK = {
    "buy_watch": 0,
    "upgrade_watch": 1,
    "hold_watch": 2,
    "watch": 3,
    "avoid": 9,
}

_CONFIDENCE_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}

_PRIORITY_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


def _watchlist_row(row: pd.Series, *, target_date: str, plan_date: str) -> dict[str, Any]:
    signal_type = _text(row.get("signal_type"))
    priority = _priority_label(row)
    skill = _suggested_skill(row, priority=priority)
    return {
        "target_date": target_date,
        "plan_date": plan_date,
        "symbol": _text(row.get("symbol")).zfill(6),
        "name": _text(row.get("name")),
        "research_priority": priority,
        "suggested_ai_berkshire_skill": skill,
        "handoff_reason": _handoff_reason(row, priority=priority),
        "ai_berkshire_questions": _ai_berkshire_questions(row, skill=skill),
        "alpha_cn_summary": _alpha_cn_summary(row),
        "source_signal_type": signal_type,
        "decision_bucket": _text(row.get("decision_bucket")),
        "action_bucket": _text(row.get("action_bucket")),
        "confidence": _text(row.get("confidence")),
        "expected_horizon": _text(row.get("expected_horizon")),
        "research_score": _round(row.get("research_score")),
        "risk_level": _text(row.get("risk_level")) or "未标注",
        "reason_tags": _text(row.get("reason_tags")),
        "risk_tags": _text(row.get("risk_tags")),
        "matched_theme": _text(row.get("matched_theme")),
        "theme_cluster": _text(row.get("theme_cluster")),
        "stage": _text(row.get("stage")),
        "setup_phase": _text(row.get("setup_phase")),
        "observe_condition": _text(row.get("observe_condition")),
        "invalid_condition": _text(row.get("invalid_condition")),
        "position_hint": _text(row.get("position_hint")),
        "is_holding": bool(row.get("is_holding", False)),
        "source": "decision_signal+holding" if bool(row.get("is_holding", False)) else "decision_signal",
        "fundamental_watchlist_version": FUNDAMENTAL_WATCHLIST_VERSION,
    }


def _priority_rank(row: pd.Series) -> int:
    return _PRIORITY_RANK[_priority_label(row)]


def _priority_label(row: pd.Series) -> str:
    signal_type = _text(row.get("signal_type"))
    confidence = _text(row.get("confidence"))
    risk_level = _text(row.get("risk_level")) or "未标注"
    score = _float(row.get("research_score"))
    is_holding = bool(row.get("is_holding", False))

    if risk_level in {"中高", "高"}:
        return "medium" if is_holding else "low"
    if signal_type == "buy_watch" and confidence == "high":
        return "high"
    if signal_type == "buy_watch" and confidence == "medium" and score >= 62:
        return "high"
    if is_holding and signal_type in {"buy_watch", "hold_watch", "upgrade_watch"}:
        return "high"
    if signal_type in {"upgrade_watch", "hold_watch"} and confidence in {"high", "medium"}:
        return "medium"
    if is_holding:
        return "medium"
    return "low"


def _suggested_skill(row: pd.Series, *, priority: str) -> str:
    signal_type = _text(row.get("signal_type"))
    action_bucket = _text(row.get("action_bucket"))
    horizon = _text(row.get("expected_horizon"))
    is_holding = bool(row.get("is_holding", False))
    if is_holding:
        return "thesis-tracker"
    if signal_type == "buy_watch" and priority == "high":
        return "investment-checklist"
    if "A1" in action_bucket or horizon == "10-30d":
        return "investment-research"
    if signal_type in {"upgrade_watch", "hold_watch"}:
        return "quality-screen"
    return "quality-screen"


def _handoff_reason(row: pd.Series, *, priority: str) -> str:
    parts = [f"优先级:{priority}"]
    for label, value in [
        ("信号", row.get("signal_type")),
        ("分组", row.get("action_bucket")),
        ("主线", row.get("matched_theme")),
        ("主题簇", row.get("theme_cluster")),
        ("风险", row.get("risk_level")),
    ]:
        text = _text(value)
        if text:
            parts.append(f"{label}:{text}")
    if bool(row.get("is_holding", False)):
        parts.append("本地持仓匹配")
    return "；".join(dict.fromkeys(parts))


def _ai_berkshire_questions(row: pd.Series, *, skill: str) -> str:
    questions = [
        "主线逻辑能否落到订单、盈利或行业景气",
        "估值和盈利弹性是否匹配当前技术位置",
        "公告、减持、质押、问询和财务风险是否干净",
        "同主题里它是否比替代标的更有质量优势",
    ]
    if skill == "thesis-tracker":
        questions.insert(0, "现有持仓 thesis 是否仍成立，亏损或盈利是否需要调整观察条件")
    elif skill == "investment-checklist":
        questions.insert(0, "是否具备从交易机会升级为可研究标的的基本面支撑")
    elif skill == "investment-research":
        questions.insert(0, "中期景气和公司质量是否足以支持 10-30 日以上观察")
    else:
        questions.insert(0, "先做质量筛查，判断是否值得进入深研")
    return "；".join(questions)


def _alpha_cn_summary(row: pd.Series) -> str:
    fields = [
        _text(row.get("position_hint")),
        _text(row.get("observe_condition")),
        f"失效:{_text(row.get('invalid_condition'))}" if _text(row.get("invalid_condition")) else "",
    ]
    return "；".join(item for item in fields if item)


def _holding_symbols(holdings: pd.DataFrame | None) -> set[str]:
    if holdings is None or holdings.empty or "symbol" not in holdings.columns:
        return set()
    return set(holdings["symbol"].astype(str).str.zfill(6).tolist())


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


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _float(value: object) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _round(value: object) -> float:
    return round(_float(value), 4)
