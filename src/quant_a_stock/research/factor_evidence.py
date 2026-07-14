from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.research.version import FACTOR_EVIDENCE_VERSION


FACTOR_COLUMNS = {
    "低位程度": ("price_position_pct", -1),
    "量能": ("volume_ratio", 1),
    "20日涨幅": ("ret_20_pct", 1),
    "60日涨幅": ("ret_60_pct", 1),
    "多周期": ("mtf_score", 1),
    "主题强度": ("co_rise_count", 1),
    "拥挤度": ("total_penalty", -1),
    "公告风险": ("risk_event_score", -1),
}

MIN_FACTOR_WEIGHTING_DATES = 40
RECOMMENDED_FACTOR_WEIGHTING_DATES = 60


@dataclass(frozen=True)
class FactorEvidenceResult:
    summary: pd.DataFrame
    quantiles: pd.DataFrame
    regimes: pd.DataFrame


def analyze_factor_evidence(
    outcomes: pd.DataFrame,
    *,
    horizon: str = "5d",
    quantile_count: int = 5,
    min_weighting_dates: int = MIN_FACTOR_WEIGHTING_DATES,
) -> FactorEvidenceResult:
    target_col = f"excess_ret_{horizon}" if f"excess_ret_{horizon}" in outcomes.columns else f"ret_{horizon}"
    benchmark_col = f"benchmark_ret_{horizon}"
    if outcomes.empty or target_col not in outcomes.columns:
        return FactorEvidenceResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    base = outcomes.copy()
    point_in_time_column = next(
        (column for column in ("point_in_time", "sentiment_point_in_time") if column in base.columns),
        None,
    )
    if point_in_time_column:
        values = base[point_in_time_column]
        explicit_false = values.fillna("").astype(str).str.lower().isin({"false", "0", "no", "n", "否"})
        base = base[~explicit_false].copy()
    base["signal_date"] = pd.to_datetime(base["signal_date"])
    base[target_col] = pd.to_numeric(base[target_col], errors="coerce")
    rows = []
    quantile_rows = []
    regime_rows = []

    for factor_name, (column, direction) in FACTOR_COLUMNS.items():
        if column not in base.columns:
            continue
        frame = base[["signal_date", "symbol", column, target_col] + ([benchmark_col] if benchmark_col in base.columns else [])].copy()
        frame[column] = pd.to_numeric(frame[column], errors="coerce") * direction
        frame = frame.dropna(subset=[column, target_col])
        if len(frame) < 10:
            continue
        daily_ic = frame.groupby("signal_date").apply(
            lambda group: _safe_spearman(group[column], group[target_col]) if len(group) >= 5 else float("nan"),
        ).dropna()
        ranked = frame.groupby("signal_date")[column].rank(method="average", pct=True)
        frame["quantile"] = ((ranked * quantile_count).apply(lambda value: min(quantile_count, max(1, int(value + 0.999999)))))
        grouped = frame.groupby("quantile")[target_col].agg(["count", "mean", "median"]).reset_index()
        monotonicity = _safe_spearman(grouped["quantile"], grouped["mean"]) if len(grouped) >= 2 else float("nan")
        turnover = _top_quantile_turnover(frame, quantile_count=quantile_count)
        date_count = frame["signal_date"].nunique()
        rows.append(
            {
                "factor": factor_name,
                "column": column,
                "direction": direction,
                "horizon": horizon,
                "factor_evidence_version": FACTOR_EVIDENCE_VERSION,
                "samples": len(frame),
                "dates": date_count,
                "eligible_for_weighting": date_count >= max(1, int(min_weighting_dates)),
                "weighting_status": _weighting_status(date_count, min_dates=min_weighting_dates),
                "mean_ic": daily_ic.mean() if not daily_ic.empty else float("nan"),
                "ic_std": daily_ic.std(ddof=0) if not daily_ic.empty else float("nan"),
                "ic_positive_rate": (daily_ic > 0).mean() if not daily_ic.empty else float("nan"),
                "quantile_monotonicity": monotonicity,
                "top_quantile_turnover": turnover,
                "top_minus_bottom": grouped.iloc[-1]["mean"] - grouped.iloc[0]["mean"] if len(grouped) >= 2 else float("nan"),
            }
        )
        for _, item in grouped.iterrows():
            quantile_rows.append(
                {
                    "factor": factor_name,
                    "horizon": horizon,
                    "quantile": int(item["quantile"]),
                    "count": int(item["count"]),
                    "avg_excess_ret": item["mean"],
                    "median_excess_ret": item["median"],
                }
            )
        if benchmark_col in frame.columns:
            frame[benchmark_col] = pd.to_numeric(frame[benchmark_col], errors="coerce")
            frame["market_regime"] = frame[benchmark_col].map(_market_regime)
            top = frame[frame["quantile"] == quantile_count]
            for regime, group in top.groupby("market_regime"):
                regime_rows.append(
                    {
                        "factor": factor_name,
                        "horizon": horizon,
                        "market_regime": regime,
                        "count": len(group),
                        "avg_excess_ret": group[target_col].mean(),
                        "win_rate": (group[target_col] > 0).mean(),
                    }
                )
    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["mean_ic", "top_minus_bottom"], ascending=False).reset_index(drop=True)
    return FactorEvidenceResult(summary, pd.DataFrame(quantile_rows), pd.DataFrame(regime_rows))


def save_factor_evidence(result: FactorEvidenceResult, *, horizon: str) -> tuple[Path, Path, Path, Path]:
    root = DEFAULT_PATHS.reports
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = root / f"factor_evidence_{horizon}_{stamp}.csv"
    quantile_path = root / f"factor_quantiles_{horizon}_{stamp}.csv"
    regime_path = root / f"factor_regimes_{horizon}_{stamp}.csv"
    markdown_path = root / f"factor_evidence_{horizon}_{stamp}.md"
    result.summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    result.quantiles.to_csv(quantile_path, index=False, encoding="utf-8-sig")
    result.regimes.to_csv(regime_path, index=False, encoding="utf-8-sig")
    markdown_path.write_text(_render_markdown(result, horizon=horizon), encoding="utf-8")
    return summary_path, quantile_path, regime_path, markdown_path


def _top_quantile_turnover(frame: pd.DataFrame, *, quantile_count: int) -> float:
    sets = [set(group.loc[group["quantile"] == quantile_count, "symbol"]) for _, group in frame.groupby("signal_date")]
    changes = []
    for previous, current in zip(sets, sets[1:]):
        denominator = max(1, len(previous | current))
        changes.append(1 - len(previous & current) / denominator)
    return float(pd.Series(changes).mean()) if changes else float("nan")


def _market_regime(value: object) -> str:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return "未知"
    if parsed >= 0.02:
        return "强势"
    if parsed <= -0.02:
        return "弱势"
    return "震荡"


def _weighting_status(date_count: int, *, min_dates: int) -> str:
    if date_count < max(1, int(min_dates)):
        return "样本积累中"
    if date_count < RECOMMENDED_FACTOR_WEIGHTING_DATES:
        return "允许候选验证，暂不正式调权"
    return "可进入正式调权评审"


def _safe_spearman(left: pd.Series, right: pd.Series) -> float:
    pair = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(pair) < 2 or pair["left"].nunique() < 2 or pair["right"].nunique() < 2:
        return float("nan")
    return float(pair["left"].corr(pair["right"], method="spearman"))


def _render_markdown(result: FactorEvidenceResult, *, horizon: str) -> str:
    lines = [
        f"# 因子证据报告 {horizon}",
        "",
        "只使用已经进入历史复盘事实表的字段，不接入新增网站。IC、分组收益、换手和市场环境稳定性需要共同判断。",
        f"少于 {MIN_FACTOR_WEIGHTING_DATES} 个完整截面日期不得调权；达到 {RECOMMENDED_FACTOR_WEIGHTING_DATES} 个日期后才进入正式调权评审。",
        "",
        "## 汇总",
        "",
        _markdown_table(result.summary) if not result.summary.empty else "暂无足够样本。",
        "",
        "## 分组收益",
        "",
        _markdown_table(result.quantiles) if not result.quantiles.empty else "暂无足够样本。",
    ]
    return "\n".join(lines)


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in frame.iterrows():
        values = [str(row[column]).replace("|", "/") for column in frame.columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
