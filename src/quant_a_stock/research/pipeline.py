from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_a_stock.backtest.report import save_report
from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.research.context_pack import save_research_context_pack
from quant_a_stock.research.decision_signal import build_decision_signals
from quant_a_stock.research.decision_signal import load_candidates_for_decision_signals
from quant_a_stock.research.fundamental_watchlist import build_fundamental_watchlist
from quant_a_stock.research.fundamental_watchlist import load_holdings_file
from quant_a_stock.research.fundamental_watchlist import save_fundamental_watchlist_context
from quant_a_stock.research.snapshot import save_research_snapshot
from quant_a_stock.research.summary import build_daily_research_summary
from quant_a_stock.research.summary import save_daily_research_summary_markdown
from quant_a_stock.warehouse import ingest_latest_reports


PIPELINE_VERSION = "research_pipeline_v2026_07_09_finalize"


@dataclass(frozen=True)
class ResearchPipelineConfig:
    target_date: str
    plan_date: str | None = None
    top: int = 30
    signal_top: int = 80
    fundamental_top: int = 20
    reports_dir: Path | None = None
    write_warehouse: bool = False


@dataclass(frozen=True)
class ResearchPipelineStep:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class ResearchPipelineResult:
    target_date: str
    plan_date: str
    version: str
    steps: list[ResearchPipelineStep]
    artifacts: dict[str, Path]


def run_research_pipeline(config: ResearchPipelineConfig) -> ResearchPipelineResult:
    """Finalize a research day from existing scan/candidate reports.

    This is the alpha_cn research kernel, not an AI/product UI layer. It assumes
    raw data and scan reports already exist, then produces structured outputs
    for review, warehouse ingestion, Obsidian export, and downstream readers.
    """

    plan_date = config.plan_date or config.target_date
    reports_dir = config.reports_dir or DEFAULT_PATHS.reports
    steps: list[ResearchPipelineStep] = []
    artifacts: dict[str, Path] = {}

    snapshot_reports = _latest_research_reports(config.target_date, reports_dir=reports_dir)
    snapshot_dir = save_research_snapshot(target_date=config.target_date, reports=snapshot_reports)
    artifacts["snapshot"] = snapshot_dir
    steps.append(ResearchPipelineStep("snapshot", "ok", str(snapshot_dir)))

    summary = build_daily_research_summary(target_date=config.target_date, snapshot_dir=snapshot_dir)
    daily_csv = save_report(
        summary.candidates.to_dict("records"),
        report_type="daily_research_candidates",
        reports_dir=reports_dir,
        date_prefix=config.target_date,
    )
    daily_md = save_daily_research_summary_markdown(summary, top=config.top)
    artifacts["daily_research_candidates"] = daily_csv
    artifacts["daily_research_summary"] = daily_md
    steps.append(ResearchPipelineStep("daily_summary", "ok", f"{daily_csv}; {daily_md}"))

    candidates = load_candidates_for_decision_signals(target_date=config.target_date, snapshot_dir=snapshot_dir)
    signals = build_decision_signals(
        candidates,
        target_date=config.target_date,
        plan_date=plan_date,
        top=config.signal_top,
    )
    signal_csv = save_report(
        signals.to_dict("records"),
        report_type="decision_signals",
        reports_dir=reports_dir,
        date_prefix=config.target_date,
    )
    artifacts["decision_signals"] = signal_csv
    steps.append(ResearchPipelineStep("decision_signals", "ok", f"{len(signals)} rows -> {signal_csv}"))

    fundamental_watchlist = build_fundamental_watchlist(
        signals,
        target_date=config.target_date,
        plan_date=plan_date,
        top=config.fundamental_top,
        holdings=load_holdings_file(),
    )
    fundamental_csv = save_report(
        fundamental_watchlist.to_dict("records"),
        report_type="fundamental_watchlist",
        reports_dir=reports_dir,
        date_prefix=config.target_date,
    )
    fundamental_context = save_fundamental_watchlist_context(
        fundamental_watchlist,
        target_date=config.target_date,
        plan_date=plan_date,
    )
    artifacts["fundamental_watchlist"] = fundamental_csv
    artifacts["fundamental_watchlist_context"] = fundamental_context.path
    steps.append(
        ResearchPipelineStep(
            "fundamental_watchlist",
            "ok",
            f"{len(fundamental_watchlist)} rows -> {fundamental_csv}; {fundamental_context.path}",
        )
    )

    context = save_research_context_pack(
        target_date=config.target_date,
        plan_date=plan_date,
        top=config.top,
        snapshot_dir=snapshot_dir,
        reports_dir=reports_dir,
    )
    artifacts["context_pack"] = context.path
    steps.append(ResearchPipelineStep("context_pack", "ok", str(context.path)))

    if config.write_warehouse:
        ingest = ingest_latest_reports(
            target_date=config.target_date,
            plan_date=plan_date,
            reports_dir=reports_dir,
        )
        artifacts["warehouse"] = ingest.db_path
        steps.append(ResearchPipelineStep("warehouse_ingest", "ok", ingest.run_id))
    else:
        steps.append(ResearchPipelineStep("warehouse_ingest", "skipped", "write_warehouse=False"))

    return ResearchPipelineResult(
        target_date=config.target_date,
        plan_date=plan_date,
        version=PIPELINE_VERSION,
        steps=steps,
        artifacts=artifacts,
    )


def _latest_research_reports(target_date: str, *, reports_dir: Path) -> dict[str, Path | None]:
    return {
        "scan_base_breakout_setup": _latest_file_for_target(reports_dir, "scan_base_breakout_setup_*.csv", target_date),
        "scan_accumulation_setup": _latest_file_for_target(reports_dir, "scan_accumulation_setup_*.csv", target_date),
        "scan_trend_pullback_setup": _latest_file_for_target(reports_dir, "scan_trend_pullback_setup_*.csv", target_date),
        "sentiment_watchlist": _latest_file_for_target(reports_dir, "sentiment_watchlist_*.csv", target_date),
        "market_theme": _latest_file_for_target(reports_dir, "market_theme_*.csv", target_date),
        "research_candidates": _latest_file_for_target(reports_dir, "research_candidates_*.csv", target_date),
    }


def _latest_file_for_target(root: Path, pattern: str, target_date: str) -> Path | None:
    compact = target_date.replace("-", "")
    if not root.exists():
        return None
    matches = [path for path in root.glob(pattern) if compact in path.name or target_date in path.name]
    if not matches:
        return None
    return sorted(matches, key=lambda path: path.stat().st_mtime)[-1]
