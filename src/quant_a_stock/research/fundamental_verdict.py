from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.research.external_data import read_csv_flexible
from quant_a_stock.research.version import FUNDAMENTAL_VERDICT_VERSION


FUNDAMENTAL_VERDICT_COLUMNS = [
    "analysis_date",
    "target_date",
    "symbol",
    "name",
    "fundamental_verdict",
    "quality_score",
    "valuation_risk",
    "industry_outlook",
    "catalyst_horizon",
    "financial_risk_tags",
    "reason_summary",
    "source",
    "fundamental_verdict_version",
]

_ALIASES = {
    "股票代码": "symbol",
    "代码": "symbol",
    "股票名称": "name",
    "名称": "name",
    "结论": "fundamental_verdict",
    "基本面结论": "fundamental_verdict",
    "质量分": "quality_score",
    "估值风险": "valuation_risk",
    "行业展望": "industry_outlook",
    "催化周期": "catalyst_horizon",
    "财务风险标签": "financial_risk_tags",
    "结论摘要": "reason_summary",
    "分析日期": "analysis_date",
    "数据日期": "target_date",
}

_VERDICT_ALIASES = {
    "pass": "pass",
    "通过": "pass",
    "可跟踪": "pass",
    "watch": "watch",
    "观察": "watch",
    "谨慎观察": "watch",
    "reject": "reject",
    "否决": "reject",
    "排除": "reject",
}


def load_fundamental_verdicts(
    path: Path,
    *,
    target_date: str,
    source: str = "ai-berkshire",
) -> pd.DataFrame:
    return normalize_fundamental_verdicts(
        read_csv_flexible(path),
        target_date=target_date,
        source=source,
    )


def normalize_fundamental_verdicts(
    frame: pd.DataFrame,
    *,
    target_date: str,
    source: str = "ai-berkshire",
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=FUNDAMENTAL_VERDICT_COLUMNS)
    output = frame.rename(columns={column: _ALIASES.get(str(column).strip(), str(column).strip()) for column in frame.columns})
    if "symbol" not in output.columns or "fundamental_verdict" not in output.columns:
        raise ValueError("基本面回流文件必须包含 symbol/股票代码 和 fundamental_verdict/基本面结论。")
    output["symbol"] = output["symbol"].astype(str).str.extract(r"(\d{6})", expand=False)
    output = output[output["symbol"].notna()].copy()
    raw_verdict = output["fundamental_verdict"].fillna("").astype(str).str.strip().str.lower()
    output["fundamental_verdict"] = raw_verdict.map(_VERDICT_ALIASES)
    invalid = raw_verdict[(raw_verdict != "") & output["fundamental_verdict"].isna()].unique().tolist()
    if invalid:
        raise ValueError(f"未知基本面结论: {', '.join(map(str, invalid))}；只允许 pass/watch/reject。")
    output = output[output["fundamental_verdict"].notna()].copy()
    score = pd.to_numeric(output.get("quality_score", pd.Series(index=output.index, dtype=float)), errors="coerce")
    if ((score.dropna() < 0) | (score.dropna() > 100)).any():
        raise ValueError("quality_score 必须在 0 到 100 之间。")
    output["quality_score"] = score
    analysis_dates = output["analysis_date"] if "analysis_date" in output.columns else pd.Series(target_date, index=output.index)
    target_dates = output["target_date"] if "target_date" in output.columns else pd.Series(target_date, index=output.index)
    output["analysis_date"] = pd.to_datetime(analysis_dates, errors="coerce").fillna(pd.Timestamp(target_date)).dt.date.astype(str)
    output["target_date"] = pd.to_datetime(target_dates, errors="coerce").fillna(pd.Timestamp(target_date)).dt.date.astype(str)
    for column in (
        "name",
        "valuation_risk",
        "industry_outlook",
        "catalyst_horizon",
        "financial_risk_tags",
        "reason_summary",
    ):
        if column not in output.columns:
            output[column] = ""
        output[column] = output[column].fillna("").astype(str).str.strip()
    if "source" not in output.columns:
        output["source"] = source
    output["source"] = output["source"].fillna(source).astype(str).str.strip().replace("", source)
    output["fundamental_verdict_version"] = FUNDAMENTAL_VERDICT_VERSION
    output = output.sort_values(["analysis_date", "symbol"]).drop_duplicates("symbol", keep="last")
    return output.reindex(columns=FUNDAMENTAL_VERDICT_COLUMNS).reset_index(drop=True)


def merge_fundamental_verdicts(signals: pd.DataFrame, verdicts: pd.DataFrame) -> pd.DataFrame:
    if signals.empty or verdicts.empty:
        return signals.copy()
    output = signals.copy()
    output["symbol"] = output["symbol"].astype(str).str.zfill(6)
    columns = [column for column in FUNDAMENTAL_VERDICT_COLUMNS if column not in {"name", "target_date"}]
    return output.merge(verdicts[columns], on="symbol", how="left", validate="many_to_one")
