from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.universe import normalize_symbol
from quant_a_stock.research.version import FUNDAMENTAL_QUALITY_VERSION


FUNDAMENTAL_QUALITY_COLUMNS = [
    "target_date",
    "symbol",
    "name",
    "quality_verdict",
    "quality_score",
    "hard_reject",
    "hard_reject_reasons",
    "data_quality",
    "latest_notice_date",
    "latest_report_date",
    "latest_annual_date",
    "annual_count",
    "roe_3y_avg",
    "roe_3y_min",
    "gross_margin_3y_avg",
    "cfo_net_profit_3y_avg",
    "debt_ratio_latest",
    "revenue_growth_3y_avg",
    "profit_growth_3y_avg",
    "recent_revenue_growth",
    "recent_profit_growth",
    "eps_latest_annual",
    "bps_latest_annual",
    "close",
    "pe",
    "pb",
    "quality_tags",
    "risk_tags",
    "specialized_model",
    "source",
    "error",
    "fundamental_quality_version",
]


@dataclass(frozen=True)
class FundamentalQualityConfig:
    pass_score: float = 70.0
    watch_score: float = 50.0
    minimum_annual_reports: int = 3


def build_fundamental_quality_row(
    indicators: pd.DataFrame,
    *,
    symbol: str,
    name: str,
    target_date: str,
    close: float | None = None,
    source: str = "eastmoney",
    error: str = "",
    config: FundamentalQualityConfig | None = None,
) -> dict:
    cfg = config or FundamentalQualityConfig()
    code = normalize_symbol(symbol)
    if indicators.empty:
        return _empty_row(code, name, target_date, source=source, error=error or "empty")

    frame = indicators.copy()
    frame["REPORT_DATE"] = pd.to_datetime(frame.get("REPORT_DATE"), errors="coerce")
    frame["NOTICE_DATE"] = pd.to_datetime(frame.get("NOTICE_DATE"), errors="coerce")
    cutoff = pd.Timestamp(target_date).normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    frame = frame[
        frame["REPORT_DATE"].notna()
        & frame["NOTICE_DATE"].notna()
        & (frame["REPORT_DATE"] <= cutoff)
        & (frame["NOTICE_DATE"] <= cutoff)
    ].copy()
    if frame.empty:
        return _empty_row(code, name, target_date, source=source, error="no_point_in_time_records")

    frame = frame.sort_values(["REPORT_DATE", "NOTICE_DATE"], ascending=False)
    latest = frame.iloc[0]
    annual = frame[
        frame.get("REPORT_TYPE", pd.Series("", index=frame.index)).fillna("").astype(str).str.contains("年报")
    ].drop_duplicates(subset=["REPORT_DATE"], keep="first")
    annual = annual.sort_values("REPORT_DATE", ascending=False).head(3)
    specialized = bool(re.search(r"银行|证券|保险|信托", str(name)))
    metrics = _metrics(annual, latest=latest, close=close)

    if specialized:
        verdict = "specialized_review"
        score = np.nan
        hard_reject_reasons: list[str] = []
        quality_tags = "通用财务去劣规则不适用"
        risk_tags = "需银行/券商/保险专用模型"
    elif len(annual) < cfg.minimum_annual_reports:
        verdict = "data_insufficient"
        score = np.nan
        hard_reject_reasons = []
        quality_tags = ""
        risk_tags = f"仅有{len(annual)}期可用年报"
    else:
        score, quality, risks, hard_reject_reasons = _score_quality(metrics)
        if hard_reject_reasons or score < cfg.watch_score:
            verdict = "reject"
        elif score >= cfg.pass_score:
            verdict = "pass"
        else:
            verdict = "watch"
        quality_tags = "；".join(quality)
        risk_tags = "；".join(risks)

    return {
        "target_date": target_date,
        "symbol": code,
        "name": str(name or ""),
        "quality_verdict": verdict,
        "quality_score": _round(score),
        "hard_reject": bool(hard_reject_reasons),
        "hard_reject_reasons": "；".join(hard_reject_reasons),
        "data_quality": "OK" if len(annual) >= cfg.minimum_annual_reports else "WARN",
        "latest_notice_date": _date(latest.get("NOTICE_DATE")),
        "latest_report_date": _date(latest.get("REPORT_DATE")),
        "latest_annual_date": _date(annual.iloc[0].get("REPORT_DATE")) if not annual.empty else "",
        "annual_count": int(len(annual)),
        **metrics,
        "quality_tags": quality_tags,
        "risk_tags": risk_tags,
        "specialized_model": specialized,
        "source": source,
        "error": error,
        "fundamental_quality_version": FUNDAMENTAL_QUALITY_VERSION,
    }


def build_research_queue(
    watchlist: pd.DataFrame,
    quality: pd.DataFrame,
    *,
    top: int = 5,
) -> pd.DataFrame:
    if watchlist.empty or quality.empty:
        return pd.DataFrame()
    frame = watchlist.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    quality_frame = quality.copy()
    quality_frame["symbol"] = quality_frame["symbol"].astype(str).str.zfill(6)
    quality_frame = quality_frame.rename(
        columns={
            "target_date": "quality_target_date",
            "risk_tags": "fundamental_risk_tags",
            "source": "fundamental_source",
            "error": "fundamental_error",
        }
    )
    merged = frame.merge(quality_frame, on=["symbol", "name"], how="left", suffixes=("", "_quality"))
    verdict_rank = {"pass": 0, "watch": 1, "specialized_review": 2, "data_insufficient": 3, "reject": 9}
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    merged["_verdict_rank"] = merged["quality_verdict"].map(verdict_rank).fillna(8)
    merged["_priority_rank"] = merged["research_priority"].map(priority_rank).fillna(9)
    merged["_quality_score"] = pd.to_numeric(merged["quality_score"], errors="coerce").fillna(-1)
    priority_bonus = merged["research_priority"].map({"high": 20.0, "medium": 10.0, "low": 0.0}).fillna(0.0)
    verdict_bonus = merged["quality_verdict"].map({"pass": 10.0, "watch": 0.0, "specialized_review": 5.0}).fillna(0.0)
    valuation_penalty = merged.get("fundamental_risk_tags", pd.Series("", index=merged.index)).fillna("").astype(str).map(
        lambda text: 8.0 * sum(tag in text for tag in ("市盈率偏高", "市净率偏高"))
    )
    quality_base = pd.to_numeric(merged["quality_score"], errors="coerce").fillna(50.0)
    merged["fundamental_research_rank_score"] = (
        quality_base + priority_bonus + verdict_bonus - valuation_penalty
    ).round(2)
    merged = merged[merged["quality_verdict"].ne("reject")].sort_values(
        ["fundamental_research_rank_score", "_verdict_rank", "_priority_rank", "research_score"],
        ascending=[False, True, True, False],
    )
    if top > 0:
        merged = merged.head(top)
    return merged.drop(columns=["_verdict_rank", "_priority_rank", "_quality_score"]).reset_index(drop=True)


def load_close_from_cache(symbol: str, *, target_date: str, cache_root: Path | None = None) -> float | None:
    root = cache_root or DEFAULT_PATHS.root / "data" / "cache" / "akshare" / "daily"
    path = root / f"{normalize_symbol(symbol)}.csv"
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, usecols=["timestamp", "close"])
    except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    eligible = frame[(frame["timestamp"] <= pd.Timestamp(target_date)) & frame["close"].notna()]
    return float(eligible.iloc[-1]["close"]) if not eligible.empty else None


def _metrics(annual: pd.DataFrame, *, latest: pd.Series, close: float | None) -> dict:
    roe = _series(annual, "ROEJQ")
    gross = _series(annual, "XSMLL")
    cash_quality = _series(annual, "NCO_NETPROFIT")
    revenue_growth = _series(annual, "TOTALOPERATEREVETZ")
    profit_growth = _series(annual, "PARENTNETPROFITTZ")
    eps = _number(annual.iloc[0].get("EPSJB")) if not annual.empty else np.nan
    bps = _number(annual.iloc[0].get("BPS")) if not annual.empty else np.nan
    resolved_close = _number(close)
    return {
        "roe_3y_avg": _mean(roe),
        "roe_3y_min": _min(roe),
        "gross_margin_3y_avg": _mean(gross),
        "cfo_net_profit_3y_avg": _mean(cash_quality),
        "debt_ratio_latest": _number(latest.get("ZCFZL")),
        "revenue_growth_3y_avg": _mean(revenue_growth),
        "profit_growth_3y_avg": _mean(profit_growth),
        "recent_revenue_growth": _number(latest.get("TOTALOPERATEREVETZ")),
        "recent_profit_growth": _number(latest.get("PARENTNETPROFITTZ")),
        "eps_latest_annual": _round(eps),
        "bps_latest_annual": _round(bps),
        "close": _round(resolved_close),
        "pe": _round(resolved_close / eps) if eps > 0 and resolved_close > 0 else np.nan,
        "pb": _round(resolved_close / bps) if bps > 0 and resolved_close > 0 else np.nan,
    }


def _score_quality(metrics: dict) -> tuple[float, list[str], list[str], list[str]]:
    score = 10.0
    quality: list[str] = []
    risks: list[str] = []
    hard_reject_reasons: list[str] = []

    roe = _number(metrics["roe_3y_avg"])
    if roe >= 20:
        score += 30
        quality.append("三年ROE优秀")
    elif roe >= 15:
        score += 25
        quality.append("三年ROE良好")
    elif roe >= 10:
        score += 18
    elif roe >= 8:
        score += 12
        risks.append("ROE偏低")
    else:
        score += 4
        risks.append("ROE过低")
    if roe < 6:
        hard_reject_reasons.append("三年ROE低于6%")

    cash = _number(metrics["cfo_net_profit_3y_avg"])
    if cash >= 1.2:
        score += 25
        quality.append("现金利润匹配优秀")
    elif cash >= 0.9:
        score += 20
        quality.append("现金利润匹配良好")
    elif cash >= 0.7:
        score += 13
        risks.append("现金利润匹配一般")
    elif cash >= 0.3:
        score += 5
        risks.append("现金利润偏弱")
    else:
        risks.append("现金利润严重偏弱")
        hard_reject_reasons.append("三年现金利润比低于0.3")

    debt = _number(metrics["debt_ratio_latest"])
    if debt <= 40:
        score += 20
        quality.append("负债稳健")
    elif debt <= 55:
        score += 16
    elif debt <= 65:
        score += 12
        risks.append("负债率中等")
    elif debt <= 75:
        score += 6
        risks.append("负债率偏高")
    else:
        risks.append("负债率过高")
    if debt > 85:
        hard_reject_reasons.append("资产负债率高于85%")

    roe_min = _number(metrics["roe_3y_min"])
    revenue_growth = _number(metrics["revenue_growth_3y_avg"])
    if roe_min >= 10:
        score += 10
        quality.append("盈利稳定")
    elif roe_min > 0:
        score += 5
    else:
        risks.append("盈利稳定性不足")
    if revenue_growth > 0:
        score += 5
        quality.append("收入保持增长")
    else:
        risks.append("三年收入增长偏弱")

    recent_profit = _number(metrics["recent_profit_growth"])
    if recent_profit < -30:
        risks.append("最近报告期利润明显下滑")
    if recent_profit < -50:
        hard_reject_reasons.append("最近报告期利润下降超过50%")
    pe = _number(metrics["pe"])
    pb = _number(metrics["pb"])
    if pe > 40:
        risks.append("市盈率偏高")
    if pb > 6:
        risks.append("市净率偏高")
    return round(max(0.0, min(100.0, score)), 2), quality, risks, hard_reject_reasons


def _empty_row(symbol: str, name: str, target_date: str, *, source: str, error: str) -> dict:
    row = {column: "" for column in FUNDAMENTAL_QUALITY_COLUMNS}
    row.update(
        {
            "target_date": target_date,
            "symbol": symbol,
            "name": str(name or ""),
            "quality_verdict": "data_insufficient",
            "hard_reject": False,
            "hard_reject_reasons": "",
            "data_quality": "ERROR",
            "source": source,
            "error": error,
            "fundamental_quality_version": FUNDAMENTAL_QUALITY_VERSION,
        }
    )
    return row


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _number(value: object) -> float:
    try:
        number = float(value)
        return number if np.isfinite(number) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _mean(values: pd.Series) -> float:
    return _round(values.mean()) if not values.empty else np.nan


def _min(values: pd.Series) -> float:
    return _round(values.min()) if not values.empty else np.nan


def _round(value: object) -> float:
    number = _number(value)
    return round(number, 4) if np.isfinite(number) else np.nan


def _date(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.date().isoformat() if not pd.isna(parsed) else ""
