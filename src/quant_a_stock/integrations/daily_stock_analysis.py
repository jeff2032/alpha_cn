from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from quant_a_stock.config import DEFAULT_PATHS


ACTIONABLE_SIGNAL_TYPES = {"buy_watch", "upgrade_watch"}
ALLOWED_RISK_LEVELS = {"", "低", "中", "未标注"}


@dataclass(frozen=True)
class DailyStockAnalysisHandoff:
    context_path: Path
    output_path: Path
    target_date: str
    plan_date: str
    symbols: list[str]
    payload: dict[str, Any]


def find_latest_context_pack(
    *,
    context_root: Path | None = None,
    target_date: str | None = None,
    plan_date: str | None = None,
) -> Path:
    root = context_root or DEFAULT_PATHS.root / "data" / "context" / "research"
    candidates = sorted(root.glob("????-??-??/plan_????-??-??.json"), key=lambda path: path.stat().st_mtime)
    if target_date:
        candidates = [path for path in candidates if path.parent.name == target_date]
    if plan_date:
        candidates = [path for path in candidates if path.stem == f"plan_{plan_date}"]
    if not candidates:
        raise FileNotFoundError("没有找到符合日期条件的 AlphaCN Context Pack。")
    return candidates[-1]


def build_daily_stock_analysis_handoff(
    *,
    context_path: Path | None = None,
    context_root: Path | None = None,
    output_root: Path | None = None,
    target_date: str | None = None,
    plan_date: str | None = None,
    top: int = 8,
) -> DailyStockAnalysisHandoff:
    source = context_path or find_latest_context_pack(
        context_root=context_root,
        target_date=target_date,
        plan_date=plan_date,
    )
    pack = json.loads(source.read_text(encoding="utf-8"))
    metadata = pack.get("metadata", {}) if isinstance(pack, dict) else {}
    resolved_target = str(metadata.get("target_date") or target_date or source.parent.name)
    resolved_plan = str(metadata.get("plan_date") or plan_date or source.stem.removeprefix("plan_"))
    signal_context = pack.get("decision_signal_context", {}) if isinstance(pack, dict) else {}
    raw_signals = signal_context.get("signals", []) if isinstance(signal_context, dict) else []
    rows = []
    for row in raw_signals if isinstance(raw_signals, list) else []:
        if not isinstance(row, dict):
            continue
        signal_type = str(row.get("signal_type", "") or "")
        risk_level = str(row.get("risk_level", "") or "")
        symbol = str(row.get("symbol", "") or "").zfill(6)
        if signal_type not in ACTIONABLE_SIGNAL_TYPES or risk_level not in ALLOWED_RISK_LEVELS:
            continue
        if len(symbol) != 6 or not symbol.isdigit():
            continue
        priority = 0 if signal_type == "buy_watch" else 1
        score = _number(row.get("research_score"))
        rows.append((priority, -score, symbol, row))
    selected = []
    seen = set()
    for _, _, symbol, row in sorted(rows):
        if symbol in seen:
            continue
        seen.add(symbol)
        selected.append(
            {
                "symbol": symbol,
                "name": row.get("name", ""),
                "signal_type": row.get("signal_type", ""),
                "action_bucket": row.get("action_bucket", ""),
                "research_tier": row.get("research_tier", ""),
                "research_score": _number(row.get("research_score")),
                "risk_level": row.get("risk_level", ""),
                "expected_horizon": row.get("expected_horizon", ""),
                "reason_tags": row.get("reason_tags", ""),
                "risk_tags": row.get("risk_tags", ""),
                "observe_condition": row.get("observe_condition", ""),
                "invalid_condition": row.get("invalid_condition", ""),
            }
        )
        if len(selected) >= max(1, int(top)):
            break
    payload = {
        "contract_version": "alpha_cn_to_dsa_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "alpha_cn",
        "source_context_path": str(source),
        "target_date": resolved_target,
        "plan_date": resolved_plan,
        "selection_policy": {
            "signal_types": sorted(ACTIONABLE_SIGNAL_TYPES),
            "risk_levels": sorted(ALLOWED_RISK_LEVELS),
            "top": max(1, int(top)),
        },
        "symbols": [row["symbol"] for row in selected],
        "candidates": selected,
    }
    root = output_root or DEFAULT_PATHS.root / "data" / "context" / "dsa"
    output_dir = root / resolved_target
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"plan_{resolved_plan}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return DailyStockAnalysisHandoff(
        context_path=source,
        output_path=output_path,
        target_date=resolved_target,
        plan_date=resolved_plan,
        symbols=payload["symbols"],
        payload=payload,
    )


def daily_stock_analysis_health(base_url: str, *, timeout: float = 5.0) -> tuple[bool, str]:
    root = base_url.rstrip("/")
    errors = []
    for path in ("/api/health", "/health"):
        try:
            with urlopen(f"{root}{path}", timeout=timeout) as response:
                if 200 <= response.status < 300:
                    return True, f"{path}: HTTP {response.status}"
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"{path}: {exc}")
    return False, "; ".join(errors)


def daily_stock_analysis_model_ready(base_url: str, *, timeout: float = 5.0) -> tuple[bool, str]:
    url = f"{base_url.rstrip('/')}/api/v1/system/config/setup/status"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return False, f"无法读取模型配置状态: {exc}"
    checks = payload.get("checks", []) if isinstance(payload, dict) else []
    primary = next((item for item in checks if isinstance(item, dict) and item.get("key") == "llm_primary"), None)
    if not primary:
        return False, "DSA 未返回 llm_primary 配置状态。"
    ready = str(primary.get("status", "")) == "configured"
    return ready, str(primary.get("message", "") or ("主模型已配置" if ready else "主模型未配置"))


def submit_daily_stock_analysis(
    handoff: DailyStockAnalysisHandoff,
    *,
    base_url: str = "http://127.0.0.1:8000",
    notify: bool = False,
    report_type: str = "detailed",
    timeout: float = 30.0,
) -> dict[str, Any]:
    if not handoff.symbols:
        return {"status": "skipped", "reason": "没有可提交的量化候选。", "symbols": []}
    body = {
        "stock_codes": handoff.symbols,
        "report_type": report_type,
        "force_refresh": False,
        "async_mode": True,
        "analysis_phase": "premarket",
        "selection_source": "import",
        "notify": bool(notify),
        "report_language": "zh",
    }
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/analysis/analyze",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-AlphaCN-Contract": "alpha_cn_to_dsa_v1"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            result = json.loads(raw) if raw else {}
            return {
                "status": "submitted",
                "http_status": response.status,
                "symbols": handoff.symbols,
                "response": result,
            }
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"DSA 拒绝提交: HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"无法连接 DSA: {exc}") from exc


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
