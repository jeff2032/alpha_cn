from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.warehouse import warehouse_status


CORE_WAREHOUSE_TABLES = [
    "stock_universe",
    "daily_candles",
    "daily_candles_index",
    "research_candidates",
    "daily_research_candidates",
    "sentiment_scores",
    "market_themes",
    "risk_events",
    "money_flow",
    "iwencai_import",
    "research_review_details",
    "research_review_summary",
    "research_outcome_daily",
    "missed_opportunities",
    "run_manifest",
    "data_quality_daily",
    "report_index",
    "security_master_daily",
]

REQUIRED_NONEMPTY_TABLES = {
    "stock_universe",
    "daily_candles",
    "daily_candles_index",
    "research_candidates",
    "daily_research_candidates",
    "sentiment_scores",
    "market_themes",
    "research_review_details",
    "research_review_summary",
    "research_outcome_daily",
    "run_manifest",
    "data_quality_daily",
    "report_index",
    "security_master_daily",
}

ENHANCEMENT_TABLES = {"risk_events", "money_flow", "iwencai_import"}


@dataclass(frozen=True)
class RetentionPolicy:
    reports_days: int = 14
    ops_reports_days: int = 60
    logs_days: int = 30
    snapshots_days: int = 30


def build_data_loop_status(
    *,
    target_date: str | None = None,
    plan_date: str | None = None,
    warehouse_dir: Path | None = None,
    obsidian_root: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return data-layer inventory and closed-loop checks."""

    root = DEFAULT_PATHS.root
    resolved_obsidian = obsidian_root or Path(r"G:\Program Files (x86)\Obsidian_base\中国A股荐股")
    warehouse_root = warehouse_dir or root / "data" / "warehouse"
    status = warehouse_status(warehouse_dir=warehouse_dir)
    inferred_target = target_date or _latest_target_date(status)

    layers = pd.DataFrame(
        [
            _layer_row(
                "raw_csv_cache",
                "源数据缓存",
                root / "data" / "cache" / "akshare" / "daily",
                "保留；当前增量下载仍依赖它",
                "原始日线 CSV，不作为研究复盘主数据。",
            ),
            _layer_row(
                "warehouse_parquet",
                "数仓主数据",
                warehouse_root / "parquet",
                "长期保留",
                "结构化研究与行情主存储，后续因子和复盘优先从这里读。",
            ),
            _layer_row(
                "warehouse_duckdb",
                "查询入口",
                warehouse_root / "alpha_cn.duckdb",
                "可重建；保留",
                "DuckDB 主要保存视图和元信息，数据主体在 Parquet。",
            ),
            _layer_row(
                "research_snapshots",
                "正式研究快照",
                root / "data" / "snapshots" / "research",
                "不可变；长期保留",
                "冻结当日研究事实，用于回填、审计和防止历史判断被回跑改写。",
            ),
            _layer_row(
                "reports",
                "机器报告产物",
                root / "reports",
                "保留最近 14 天；重要结论进 Obsidian",
                "CSV/Markdown 运行产物，入仓和同步后可清旧版本。",
            ),
            _layer_row(
                "ops_reports",
                "运维报告",
                root / "reports" / "ops",
                "保留最近 60 天",
                "夜间任务状态和失败原因。",
            ),
            _layer_row(
                "logs",
                "运行日志",
                root / "logs",
                "保留最近 30 天",
                "调试用日志，不参与研究统计。",
            ),
            _layer_row(
                "obsidian",
                "人工知识库",
                resolved_obsidian,
                "人工保留，不自动清理",
                "人看的复盘、计划和策略沉淀。",
            ),
        ]
    )

    checks = _build_checks(
        status=status,
        target_date=inferred_target,
        plan_date=plan_date,
        obsidian_root=resolved_obsidian,
    )
    return layers, checks


def build_retention_plan(
    *,
    reports_days: int = 14,
    ops_reports_days: int = 60,
    logs_days: int = 30,
    snapshots_days: int = 30,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Return removable files/directories without deleting anything."""

    policy = RetentionPolicy(
        reports_days=reports_days,
        ops_reports_days=ops_reports_days,
        logs_days=logs_days,
        snapshots_days=snapshots_days,
    )
    current = now or datetime.now()
    rows: list[dict] = []
    root = DEFAULT_PATHS.root

    rows.extend(
        _old_files(
            root / "reports",
            layer="reports",
            days=policy.reports_days,
            now=current,
            exclude_dirs={root / "reports" / "ops"},
            reason="报告已入仓或同步到 Obsidian 后，项目内只保留近期版本。",
        )
    )
    rows.extend(
        _old_files(
            root / "reports" / "ops",
            layer="ops_reports",
            days=policy.ops_reports_days,
            now=current,
            reason="运维报告只保留近期排障窗口。",
        )
    )
    rows.extend(
        _old_files(
            root / "logs",
            layer="logs",
            days=policy.logs_days,
            now=current,
            reason="日志不参与研究统计，只保留近期排障窗口。",
        )
    )
    rows.extend(
        _old_snapshot_dirs(
            root / "data" / "snapshots" / "research" / "rebuilds",
            days=policy.snapshots_days,
            now=current,
        )
    )
    return pd.DataFrame(rows, columns=_retention_columns())


def _build_checks(
    *,
    status: pd.DataFrame,
    target_date: str | None,
    plan_date: str | None,
    obsidian_root: Path,
) -> pd.DataFrame:
    rows: list[dict] = []
    if status.empty:
        return pd.DataFrame(
            [
                {
                    "check": "warehouse_exists",
                    "status": "FAIL",
                    "detail": "数仓还没有可读取的表。",
                    "target_date": target_date or "",
                }
            ]
        )

    for table in CORE_WAREHOUSE_TABLES:
        table_status = status[status["table"] == table]
        if table_status.empty:
            rows.append(_check_row(f"warehouse_table:{table}", "FAIL", "缺少核心表。", target_date))
            continue
        row_count = int(table_status.iloc[0].get("rows", 0) or 0)
        last_date = str(table_status.iloc[0].get("last_target_date", "") or "")
        if row_count <= 0:
            level = "FAIL" if table in REQUIRED_NONEMPTY_TABLES else "WARN"
            role = "核心" if table in REQUIRED_NONEMPTY_TABLES else "增强"
            rows.append(_check_row(f"warehouse_table:{table}", level, f"{role}表存在但没有数据。", target_date))
            continue
        if not last_date:
            level = "WARN" if table in ENHANCEMENT_TABLES else "FAIL"
            rows.append(_check_row(f"warehouse_table:{table}", level, f"表有 {row_count} 行，但缺少可核验日期。", target_date))
            continue
        if target_date and last_date and last_date < target_date:
            rows.append(
                _check_row(
                    f"warehouse_table:{table}",
                    "WARN",
                    f"最后日期 {last_date} 早于目标日 {target_date}。",
                    target_date,
                )
            )
        else:
            rows.append(_check_row(f"warehouse_table:{table}", "OK", f"最后日期 {last_date}。", target_date))

    if target_date:
        digest_path = obsidian_root / "复盘摘要" / f"{target_date}.md"
        rows.append(
            _check_row(
                "obsidian_review_digest",
                "OK" if digest_path.exists() else "WARN",
                f"{'已生成' if digest_path.exists() else '缺失'}: {digest_path}",
                target_date,
            )
        )

    if plan_date:
        plan_path = obsidian_root / "开盘决策" / f"{plan_date}.md"
        rows.append(
            _check_row(
                "obsidian_open_decision",
                "OK" if plan_path.exists() else "WARN",
                f"{'已生成' if plan_path.exists() else '缺失'}: {plan_path}",
                target_date,
            )
        )
        holding_path = obsidian_root / "持仓观察" / f"{plan_date}.md"
        rows.append(
            _check_row(
                "obsidian_holding_observation",
                "OK" if holding_path.exists() else "WARN",
                f"{'已生成' if holding_path.exists() else '缺失'}: {holding_path}",
                target_date,
            )
        )

    return pd.DataFrame(rows)


def _layer_row(layer: str, role: str, path: Path, policy: str, note: str) -> dict:
    stats = _path_stats(path)
    return {
        "layer": layer,
        "role": role,
        "path": str(path),
        "exists": stats["exists"],
        "files": stats["files"],
        "mb": stats["mb"],
        "newest": stats["newest"],
        "retention_policy": policy,
        "note": note,
    }


def _path_stats(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "files": 0, "mb": 0.0, "newest": ""}
    if path.is_file():
        stat = path.stat()
        return {
            "exists": True,
            "files": 1,
            "mb": round(stat.st_size / 1024 / 1024, 2),
            "newest": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }

    files = [item for item in path.rglob("*") if item.is_file()]
    total = sum(item.stat().st_size for item in files)
    newest = max((item.stat().st_mtime for item in files), default=None)
    return {
        "exists": True,
        "files": len(files),
        "mb": round(total / 1024 / 1024, 2),
        "newest": datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M:%S") if newest else "",
    }


def _old_files(
    root: Path,
    *,
    layer: str,
    days: int,
    now: datetime,
    reason: str,
    exclude_dirs: set[Path] | None = None,
) -> list[dict]:
    if not root.exists():
        return []
    excludes = {path.resolve() for path in (exclude_dirs or set())}
    rows = []
    cutoff_seconds = days * 24 * 60 * 60
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if any(excluded == resolved or excluded in resolved.parents for excluded in excludes):
            continue
        stat = path.stat()
        age_seconds = now.timestamp() - stat.st_mtime
        if age_seconds <= cutoff_seconds:
            continue
        rows.append(
            {
                "action": "delete_file",
                "layer": layer,
                "path": str(path),
                "files": 1,
                "mb": round(stat.st_size / 1024 / 1024, 2),
                "last_modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "reason": reason,
            }
        )
    return rows


def _old_snapshot_dirs(root: Path, *, days: int, now: datetime) -> list[dict]:
    if not root.exists():
        return []
    cutoff_seconds = days * 24 * 60 * 60
    rows = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        files = [item for item in path.rglob("*") if item.is_file()]
        newest = max((item.stat().st_mtime for item in files), default=path.stat().st_mtime)
        age_seconds = now.timestamp() - newest
        if age_seconds <= cutoff_seconds:
            continue
        total = sum(item.stat().st_size for item in files)
        rows.append(
            {
                "action": "delete_dir",
                "layer": "research_snapshot_rebuilds",
                "path": str(path),
                "files": len(files),
                "mb": round(total / 1024 / 1024, 2),
                "last_modified": datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M:%S"),
                "reason": "历史重建副本只保留近期排障窗口；正式快照不自动清理。",
            }
        )
    return rows


def _retention_columns() -> list[str]:
    return ["action", "layer", "path", "files", "mb", "last_modified", "reason"]


def _latest_target_date(status: pd.DataFrame) -> str | None:
    if status.empty or "last_target_date" not in status.columns:
        return None
    dates = [str(value) for value in status["last_target_date"].dropna().tolist() if str(value)]
    return max(dates) if dates else None


def _check_row(check: str, status: str, detail: str, target_date: str | None) -> dict:
    return {
        "check": check,
        "status": status,
        "detail": detail,
        "target_date": target_date or "",
    }
