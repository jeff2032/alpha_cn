from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.research.snapshot import SNAPSHOT_ROOT
from quant_a_stock.research.version import CANDIDATE_MODEL_VERSION
from quant_a_stock.research.version import DECISION_SIGNAL_VERSION


DECISION_SIGNAL_COLUMNS = [
    "target_date",
    "plan_date",
    "symbol",
    "name",
    "signal_type",
    "decision_bucket",
    "action_bucket",
    "research_tier",
    "confidence",
    "expected_horizon",
    "research_score",
    "risk_level",
    "reason_tags",
    "risk_tags",
    "observe_condition",
    "invalid_condition",
    "position_hint",
    "matched_theme",
    "theme_cluster",
    "stage",
    "setup_phase",
    "candidate_model_version",
    "decision_signal_version",
]


def load_candidates_for_decision_signals(
    *,
    target_date: str,
    research_report: Path | None = None,
    snapshot_dir: Path | None = None,
) -> pd.DataFrame:
    if research_report is not None:
        return pd.read_csv(research_report, dtype={"symbol": str})
    snapshot = snapshot_dir or SNAPSHOT_ROOT / target_date
    path = snapshot / "research_candidates.csv"
    if path.exists():
        return pd.read_csv(path, dtype={"symbol": str})
    latest = _latest_research_report(target_date)
    if latest is None:
        raise FileNotFoundError(f"Missing research candidates for {target_date}: {path}")
    return pd.read_csv(latest, dtype={"symbol": str})


def build_decision_signals(
    candidates: pd.DataFrame,
    *,
    target_date: str,
    plan_date: str | None = None,
    top: int | None = None,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=DECISION_SIGNAL_COLUMNS)
    frame = candidates.copy()
    if "symbol" in frame.columns:
        frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    if "action_rank" in frame.columns:
        frame = frame.sort_values(["action_rank", "research_score"], ascending=[True, False])
    elif "research_score" in frame.columns:
        frame = frame.sort_values("research_score", ascending=False)
    if top:
        frame = frame.head(top)

    rows = [_signal_row(row, target_date=target_date, plan_date=plan_date or target_date) for _, row in frame.iterrows()]
    output = pd.DataFrame(rows)
    return output.loc[:, DECISION_SIGNAL_COLUMNS]


def _signal_row(row: pd.Series, *, target_date: str, plan_date: str) -> dict:
    action_bucket = _text(row.get("action_bucket"))
    tier = _text(row.get("research_tier"))
    risk_level = _text(row.get("risk_level")) or "未标注"
    signal_type, decision_bucket = _signal_type_and_bucket(action_bucket, tier, risk_level)
    horizon = _expected_horizon(action_bucket, tier)
    confidence = _confidence(row, signal_type=signal_type, risk_level=risk_level)
    return {
        "target_date": target_date,
        "plan_date": plan_date,
        "symbol": _text(row.get("symbol")).zfill(6),
        "name": _text(row.get("name")),
        "signal_type": signal_type,
        "decision_bucket": decision_bucket,
        "action_bucket": action_bucket,
        "research_tier": tier,
        "confidence": confidence,
        "expected_horizon": horizon,
        "research_score": _round(row.get("research_score")),
        "risk_level": risk_level,
        "reason_tags": _reason_tags(row),
        "risk_tags": _risk_tags(row),
        "observe_condition": _observe_condition(signal_type, action_bucket, tier),
        "invalid_condition": _invalid_condition(signal_type, action_bucket, tier),
        "position_hint": _position_hint(signal_type, action_bucket),
        "matched_theme": _text(row.get("matched_theme")),
        "theme_cluster": _text(row.get("theme_cluster")),
        "stage": _text(row.get("stage")),
        "setup_phase": _text(row.get("setup_phase")),
        "candidate_model_version": _text(row.get("candidate_model_version")) or CANDIDATE_MODEL_VERSION,
        "decision_signal_version": DECISION_SIGNAL_VERSION,
    }


def _signal_type_and_bucket(action_bucket: str, tier: str, risk_level: str) -> tuple[str, str]:
    if tier == "B1" or action_bucket.startswith("移出-B1"):
        return "avoid", "移出推荐"
    if "回避" in action_bucket or risk_level in {"中高", "高"}:
        return "avoid", "风险回避"
    if not action_bucket:
        if tier == "A2":
            return "buy_watch", "主攻"
        if tier == "A3":
            return "buy_watch", "短线"
        if tier == "B2":
            return "upgrade_watch", "升级观察"
    if tier == "A2" and action_bucket.startswith("主攻"):
        return "buy_watch", "主攻"
    if tier == "A3" and action_bucket.startswith("短线"):
        return "buy_watch", "短线"
    if tier == "B2" and action_bucket.startswith("升级"):
        return "upgrade_watch", "升级观察"
    if action_bucket.startswith("主攻"):
        return "buy_watch", "主攻"
    if "A3" in action_bucket and "观察" in action_bucket:
        return "hold_watch", "趋势观察"
    if "B2a" in action_bucket or "B2s" in action_bucket or "补票" in action_bucket:
        return "upgrade_watch", "升级观察"
    if tier == "A1" or "A1" in action_bucket:
        return "watch", "潜伏观察"
    return "watch", "观察"


def _expected_horizon(action_bucket: str, tier: str) -> str:
    if tier == "A1" or "A1" in action_bucket:
        return "10-20d"
    if tier == "A2" or "A2" in action_bucket:
        return "3-5d"
    if tier == "A3" or "A3" in action_bucket:
        return "1-3d"
    if tier == "B2" or "B2" in action_bucket:
        return "3-5d"
    if tier == "B1":
        return "0d"
    if "B2a" in action_bucket:
        return "3-10d"
    if "B2s" in action_bucket or "主线突发" in action_bucket:
        return "1-5d"
    if "B2b" in action_bucket:
        return "1-5d"
    return "3-10d"


def _confidence(row: pd.Series, *, signal_type: str, risk_level: str) -> str:
    if signal_type == "avoid" or risk_level in {"中高", "高"}:
        return "low"
    score = _float(row.get("research_score"))
    penalty = _float(row.get("total_penalty"))
    core_news = _float(row.get("core_news_count"))
    strong_theme = bool(row.get("is_strong_theme_candidate"))
    if score >= 70 and penalty <= 0 and risk_level == "低":
        return "high"
    if score >= 62 and risk_level in {"低", "中"} and (core_news > 0 or strong_theme):
        return "medium"
    if score >= 55 and risk_level in {"低", "中"}:
        return "medium" if signal_type in {"buy_watch", "upgrade_watch"} else "low"
    return "low"


def _reason_tags(row: pd.Series) -> str:
    tags = []
    for label, value in [
        ("分层", row.get("research_tier")),
        ("动作", row.get("action_bucket")),
        ("阶段", row.get("stage")),
        ("节奏", row.get("setup_phase")),
        ("主线", row.get("matched_theme")),
        ("主题簇", row.get("theme_cluster")),
    ]:
        text = _text(value)
        if text:
            tags.append(f"{label}:{text}")
    if _float(row.get("money_flow_score")) >= 50:
        tags.append("资金确认")
    if _float(row.get("iwencai_hit")) > 0:
        tags.append("问财命中")
    if _float(row.get("core_news_count")) > 0:
        tags.append("核心消息")
    return "；".join(dict.fromkeys(tags))


def _risk_tags(row: pd.Series) -> str:
    tags = []
    raw = _text(row.get("risk_tags"))
    if raw:
        tags.extend([item.strip() for item in raw.split("；") if item.strip()])
    if _float(row.get("ret_20_pct")) > 0.18:
        tags.append("20日涨幅偏热")
    if _float(row.get("volume_ratio")) > 2.2:
        tags.append("量能偏热")
    if _float(row.get("monthly_position_pct")) > 0.75:
        tags.append("月线位置偏高")
    return "；".join(dict.fromkeys(tags)) or "无明显风险"


def _observe_condition(signal_type: str, action_bucket: str, tier: str) -> str:
    if signal_type == "avoid":
        return "只做复盘观察，等待风险解除或重新入池。"
    if signal_type == "buy_watch":
        return "看开盘承接、回踩不破、量能不过热，优先等分歧确认。"
    if signal_type == "upgrade_watch":
        return "限定 3-5 日观察升级；看主题扩散、盘中承接和公告/情绪补足。"
    if tier == "A1" or "A1" in action_bucket:
        return "看 10-30 日内是否补量、补主题、升级到 A2/A3。"
    return "看是否维持形态、主题和风险三项不恶化。"


def _invalid_condition(signal_type: str, action_bucket: str, tier: str) -> str:
    if signal_type == "avoid":
        return "风险标签未消除前不恢复常规观察。"
    if tier == "A2" or "A2" in action_bucket:
        return "跌回突破区间且放量转弱；高开后放量滞涨；主线明显转弱。"
    if tier == "A3" or "A3" in action_bucket:
        return "1-3 日未延续、趋势承接失败或连续冲高回落即退出。"
    if tier == "B2" or "B2" in action_bucket:
        return "3-5 日未升级到 A2/A3，或主题热度消退且没有补量/承接，即移出。"
    if "B2s" in action_bucket or "主线突发" in action_bucket:
        return "1-5 日没有持续性或次日低开低走，降级为普通观察。"
    if "B2a" in action_bucket or "B2b" in action_bucket:
        return "主题热度消退且没有补量/补承接，移出升级观察。"
    return "形态破坏、风险升级或主线退潮。"


def _position_hint(signal_type: str, action_bucket: str) -> str:
    if signal_type == "avoid":
        return "回避，不作为新增机会。"
    if signal_type == "buy_watch":
        return "候选主攻，只等确认，不高开硬追。"
    if signal_type == "upgrade_watch":
        return "升级观察，不直接当买点。"
    if signal_type == "hold_watch":
        return "趋势观察，只看分歧承接。"
    return "观察为主，等待升级信号。"


def _latest_research_report(target_date: str) -> Path | None:
    root = DEFAULT_PATHS.reports
    compact = target_date.replace("-", "")
    matches = [path for path in root.glob("research_candidates_*.csv") if compact in path.name]
    if not matches:
        return None
    return sorted(matches, key=lambda path: path.stat().st_mtime)[-1]


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
