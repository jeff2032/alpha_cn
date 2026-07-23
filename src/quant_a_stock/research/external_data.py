from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from time import sleep

import pandas as pd

from quant_a_stock.data.universe import infer_market, normalize_symbol


RISK_EVENT_COLUMNS = [
    "symbol",
    "date",
    "title",
    "event_type",
    "severity",
    "severity_score",
    "source",
    "url",
]

MONEY_FLOW_COLUMNS = [
    "symbol",
    "date",
    "main_net_inflow",
    "main_net_inflow_pct",
    "main_net_inflow_3d",
    "main_net_inflow_5d",
    "positive_flow_days_5",
    "money_flow_score",
    "source",
    "error",
]

IWENCAI_COLUMNS = [
    "symbol",
    "name",
    "date",
    "iwencai_hit",
    "iwencai_rank",
    "iwencai_score",
    "iwencai_query",
    "iwencai_tags",
    "iwencai_reason",
    "source",
]


@dataclass(frozen=True)
class ExternalFetchResult:
    frame: pd.DataFrame
    errors: list[str]


RISK_EVENT_RULES: list[tuple[str, str, list[str]]] = [
    ("退市/ST风险", "高", [r"终止上市", r"退市风险警示", r"实施(?:其他)?风险警示", r"撤销退市风险警示未获"]),
    (
        "立案处罚",
        "高",
        [r"立案告知书", r"被立案调查", r"涉嫌.{0,20}违法.{0,20}立案", r"行政处罚(?:决定书|事先告知书)", r"纪律处分决定"],
    ),
    ("监管问询", "中高", [r"问询函", r"监管函", r"关注函", r"警示函", r"责令改正"]),
    (
        "财务审计风险",
        "中高",
        [r"前期会计差错更正", r"非标准审计意见", r"保留意见", r"无法表示意见", r"否定意见", r"审计机构辞任"],
    ),
    ("业绩风险", "中高", [r"预计亏损", r"业绩预告修正", r"业绩预告更正", r"净利润.{0,12}大幅下降"]),
    ("减持解禁", "中", [r"减持计划", r"减持股份", r"限售股解禁", r"解除限售"]),
    ("质押冻结", "中", [r"股份质押", r"司法冻结", r"轮候冻结"]),
    ("诉讼仲裁", "中", [r"重大诉讼", r"重大仲裁", r"涉及诉讼", r"涉及仲裁"]),
    ("债务担保风险", "中", [r"债务逾期", r"担保逾期", r"违规担保", r"违规占用", r"存在.{0,10}资金占用"]),
    ("异常波动", "低", [r"股票交易异常波动", r"股票交易严重异常波动"]),
]

SEVERITY_SCORE = {"高": 8.0, "中高": 5.0, "中": 3.0, "低": 1.0}


def classify_risk_event(title: str) -> tuple[str, str, float]:
    text = re.sub(r"\s+", "", str(title or ""))
    for event_type, severity, patterns in RISK_EVENT_RULES:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            return event_type, severity, SEVERITY_SCORE[severity]
    return "", "", 0.0


def fetch_cninfo_risk_events(
    symbols: list[str],
    *,
    start_date: str,
    end_date: str,
) -> ExternalFetchResult:
    import akshare as ak

    rows: list[dict] = []
    errors: list[str] = []
    for symbol in symbols:
        code = normalize_symbol(symbol)
        try:
            frame = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=code,
                market="沪深京",
                keyword="",
                category="",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
        except Exception as exc:  # pragma: no cover - depends on provider/network state
            errors.append(f"{code} 巨潮公告: {type(exc).__name__}: {exc}")
            continue
        rows.extend(_risk_events_from_cninfo_frame(frame, symbol=code))
    return ExternalFetchResult(pd.DataFrame(rows, columns=RISK_EVENT_COLUMNS), errors)


def _risk_events_from_cninfo_frame(frame: pd.DataFrame, *, symbol: str) -> list[dict]:
    if frame.empty or "公告标题" not in frame.columns:
        return []
    rows: list[dict] = []
    date_col = _first_existing(frame, ["公告时间", "公告日期", "发布日期", "date"])
    url_col = _first_existing(frame, ["公告链接", "url", "URL"])
    for _, item in frame.iterrows():
        title = str(item.get("公告标题", "") or "")
        event_type, severity, score = classify_risk_event(title)
        if not event_type:
            continue
        date_text = _date_text(item.get(date_col, "")) if date_col else ""
        rows.append(
            {
                "symbol": normalize_symbol(symbol),
                "date": date_text,
                "title": title,
                "event_type": event_type,
                "severity": severity,
                "severity_score": score,
                "source": "cninfo",
                "url": str(item.get(url_col, "") or "") if url_col else "",
            }
        )
    return rows


def summarize_risk_events(
    events: pd.DataFrame,
    *,
    as_of_date: str | None = None,
    lookback_days: int = 120,
    half_life_days: float = 30.0,
) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "risk_notice_count",
                "risk_notice_titles",
                "risk_event_score",
                "high_risk_event_count",
                "risk_event_types",
                "latest_risk_event_date",
                "risk_event_age_days",
            ]
        )
    frame = events.copy()
    frame["symbol"] = frame["symbol"].map(normalize_symbol)
    frame["title"] = frame.get("title", "").fillna("").astype(str)
    classified = frame["title"].map(classify_risk_event)
    frame["event_type"] = classified.map(lambda item: item[0])
    frame["severity"] = classified.map(lambda item: item[1])
    frame["severity_score"] = classified.map(lambda item: item[2])
    frame = frame[frame["event_type"].ne("")].copy()
    if frame.empty:
        return summarize_risk_events(pd.DataFrame())
    date_values = frame["date"] if "date" in frame.columns else pd.Series(pd.NaT, index=frame.index)
    frame["date"] = pd.to_datetime(date_values, errors="coerce").dt.normalize()
    frame["dedupe_title"] = frame["title"].map(_normalize_event_title)
    frame = frame.drop_duplicates(subset=["symbol", "date", "dedupe_title", "event_type"], keep="last")

    if as_of_date:
        as_of = pd.Timestamp(as_of_date).normalize()
        frame = frame[(frame["date"].isna()) | (frame["date"] <= as_of)].copy()
        frame["event_age_days"] = (as_of - frame["date"]).dt.days.fillna(0).clip(lower=0)
        frame = frame[frame["event_age_days"] <= max(1, int(lookback_days))].copy()
    else:
        frame["event_age_days"] = 0
    if frame.empty:
        return summarize_risk_events(pd.DataFrame())

    half_life = max(1.0, float(half_life_days))
    frame["effective_score"] = frame["severity_score"] * (0.5 ** (frame["event_age_days"] / half_life))
    frame = frame[frame["effective_score"] >= 0.5].copy()
    if frame.empty:
        return summarize_risk_events(pd.DataFrame())
    frame["is_high"] = frame["severity"].eq("高") & frame["effective_score"].ge(4.0)
    frame = frame.sort_values(["symbol", "date", "effective_score"], ascending=[True, False, False])
    grouped = frame.groupby("symbol", as_index=False).agg(
        risk_notice_count=("title", "count"),
        risk_event_score=("effective_score", "sum"),
        high_risk_event_count=("is_high", "sum"),
        risk_notice_titles=("title", lambda values: "；".join(values.astype(str).head(5))),
        risk_event_types=("event_type", lambda values: "；".join(dict.fromkeys(values.astype(str)))),
        latest_risk_event_date=("date", "max"),
        risk_event_age_days=("event_age_days", "min"),
    )
    grouped["risk_event_score"] = grouped["risk_event_score"].clip(upper=20).round(2)
    grouped["high_risk_event_count"] = grouped["high_risk_event_count"].astype(int)
    grouped["latest_risk_event_date"] = grouped["latest_risk_event_date"].dt.date.astype("string").fillna("")
    grouped["risk_event_age_days"] = grouped["risk_event_age_days"].astype(int)
    return grouped


def _normalize_event_title(title: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(title or "")).lower()


def fetch_eastmoney_money_flow(
    symbols: list[str],
    *,
    target_date: str,
    lookback_days: int = 10,
    retries: int = 2,
    retry_wait: float = 1.5,
    sleep_seconds: float = 0.2,
) -> ExternalFetchResult:
    import akshare as ak

    rows: list[dict] = []
    provider_errors: dict[str, str] = {}
    requested_symbols = [normalize_symbol(symbol) for symbol in symbols]
    fallback_error = ""
    ths_attempted = False
    if _is_current_target_date(target_date):
        ths_attempted = True
        initial = pd.DataFrame(
            [_empty_money_flow_row(code, target_date, error="ths_missing") for code in requested_symbols],
            columns=MONEY_FLOW_COLUMNS,
        )
        initial, fallback_error = _fill_money_flow_from_ths_rank(
            initial,
            symbols=requested_symbols,
            target_date=target_date,
            retries=retries,
            retry_wait=retry_wait,
        )
        successful = initial[initial["error"].fillna("").astype(str).str.strip().eq("")]
        rows.extend(successful.to_dict("records"))
        requested_symbols = initial.loc[
            initial["error"].fillna("").astype(str).str.strip().ne(""), "symbol"
        ].astype(str).tolist()

    for code in requested_symbols:
        code = normalize_symbol(code)
        frame, error = _fetch_with_retries(
            lambda: ak.stock_individual_fund_flow(stock=code, market=_ak_market(code)),
            retries=retries,
            retry_wait=retry_wait,
        )
        if error:
            provider_errors[code] = error
            rows.append(_empty_money_flow_row(code, target_date, error=error))
            if sleep_seconds > 0:
                sleep(sleep_seconds)
            continue
        row = normalize_money_flow_frame(frame, symbol=code, target_date=target_date, lookback_days=lookback_days)
        if row.get("error"):
            provider_errors[code] = str(row["error"])
        rows.append(row)
        if sleep_seconds > 0:
            sleep(sleep_seconds)

    result = pd.DataFrame(rows, columns=MONEY_FLOW_COLUMNS)
    if provider_errors and _is_current_target_date(target_date) and not ths_attempted:
        result, fallback_error = _fill_money_flow_from_ths_rank(
            result,
            symbols=list(provider_errors),
            target_date=target_date,
            retries=retries,
            retry_wait=retry_wait,
        )

    unresolved = set(
        result.loc[result["error"].fillna("").astype(str).str.strip().ne(""), "symbol"].astype(str)
    )
    errors = [f"{code} 东财资金流: {provider_errors[code]}" for code in provider_errors if code in unresolved]
    if fallback_error:
        errors.append(f"同花顺全市场资金流备用源: {fallback_error}")
    return ExternalFetchResult(result, errors)


def _fill_money_flow_from_ths_rank(
    result: pd.DataFrame,
    *,
    symbols: list[str],
    target_date: str,
    retries: int,
    retry_wait: float,
) -> tuple[pd.DataFrame, str]:
    import akshare as ak

    snapshots: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    for period in ("即时", "3日排行", "5日排行"):
        frame, error = _fetch_with_retries(
            lambda period=period: ak.stock_fund_flow_individual(symbol=period),
            retries=retries,
            retry_wait=retry_wait,
        )
        snapshots[period] = frame
        if error:
            errors.append(f"{period}: {error}")

    fallback = normalize_ths_money_flow_rank(
        snapshots.get("即时", pd.DataFrame()),
        flow_3d=snapshots.get("3日排行", pd.DataFrame()),
        flow_5d=snapshots.get("5日排行", pd.DataFrame()),
        symbols=symbols,
        target_date=target_date,
    )
    if fallback.empty:
        return result, "；".join(errors) or "empty"

    output = result.copy()
    replacements = fallback.set_index("symbol").to_dict("index")
    for index, row in output.iterrows():
        replacement = replacements.get(str(row["symbol"]))
        if replacement is None or not str(row.get("error", "") or "").strip():
            continue
        for column in MONEY_FLOW_COLUMNS:
            if column == "symbol":
                continue
            output.at[index, column] = replacement[column]
    return output, "；".join(errors)


def normalize_ths_money_flow_rank(
    current: pd.DataFrame,
    *,
    flow_3d: pd.DataFrame,
    flow_5d: pd.DataFrame,
    symbols: list[str],
    target_date: str,
) -> pd.DataFrame:
    requested = {normalize_symbol(symbol) for symbol in symbols}
    if current.empty or not requested:
        return pd.DataFrame(columns=MONEY_FLOW_COLUMNS)

    def rank_values(frame: pd.DataFrame, value_columns: list[str]) -> dict[str, float]:
        symbol_col = _first_existing(frame, ["股票代码", "代码", "symbol"])
        value_col = _first_existing(frame, value_columns)
        if frame.empty or symbol_col is None or value_col is None:
            return {}
        return {
            normalize_symbol(row[symbol_col]): _money_number(row[value_col])
            for _, row in frame.iterrows()
            if normalize_symbol(row[symbol_col]) in requested
        }

    current_values = rank_values(current, ["净额", "资金流入净额", "主力净额"])
    turnover_values = rank_values(current, ["成交额"])
    values_3d = rank_values(flow_3d, ["资金流入净额", "净额"])
    values_5d = rank_values(flow_5d, ["资金流入净额", "净额"])
    rows: list[dict] = []
    for code in sorted(requested):
        if code not in current_values:
            continue
        main_net = current_values[code]
        turnover = turnover_values.get(code, 0.0)
        main_pct = main_net / turnover * 100 if turnover else 0.0
        net_3d = values_3d.get(code, main_net)
        net_5d = values_5d.get(code, net_3d)
        rows.append(
            {
                "symbol": code,
                "date": target_date,
                "main_net_inflow": round(main_net, 2),
                "main_net_inflow_pct": round(main_pct, 4),
                "main_net_inflow_3d": round(net_3d, 2),
                "main_net_inflow_5d": round(net_5d, 2),
                "positive_flow_days_5": 0,
                "money_flow_score": _money_flow_score(main_net, main_pct, net_3d, net_5d, 0),
                "source": "10jqka_market_rank",
                "error": "",
            }
        )
    return pd.DataFrame(rows, columns=MONEY_FLOW_COLUMNS)


def _is_current_target_date(target_date: str) -> bool:
    target = pd.to_datetime(target_date, errors="coerce")
    return not pd.isna(target) and target.normalize() == pd.Timestamp.now().normalize()


def money_flow_success_rate(frame: pd.DataFrame) -> float:
    if frame.empty or "error" not in frame.columns:
        return 0.0 if frame.empty else 1.0
    errors = frame["error"].fillna("").astype(str).str.strip()
    return float((errors == "").mean())


def normalize_money_flow_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    target_date: str,
    lookback_days: int = 10,
) -> dict:
    code = normalize_symbol(symbol)
    if frame.empty:
        return _empty_money_flow_row(code, target_date, error="empty")
    data = frame.copy()
    date_col = _first_existing(data, ["日期", "date", "交易日期"])
    if date_col is None:
        return _empty_money_flow_row(code, target_date, error="missing_date")
    data["date_norm"] = pd.to_datetime(data[date_col], errors="coerce").dt.normalize()
    target = pd.Timestamp(target_date).normalize()
    data = data[data["date_norm"] <= target].sort_values("date_norm")
    if data.empty:
        return _empty_money_flow_row(code, target_date, error="no_data_before_target")

    main_col = _first_existing(
        data,
        [
            "主力净流入-净额",
            "主力净流入净额",
            "主力净流入",
            "主力净额",
            "main_net_inflow",
        ],
    )
    pct_col = _first_existing(
        data,
        [
            "主力净流入-净占比",
            "主力净流入净占比",
            "主力净占比",
            "main_net_inflow_pct",
        ],
    )
    if main_col is None:
        return _empty_money_flow_row(code, target_date, error="missing_main_net_inflow")
    data["main_net_inflow"] = data[main_col].map(_money_number)
    data["main_net_inflow_pct"] = data[pct_col].map(_percent_number) if pct_col else 0.0
    recent = data.tail(max(1, lookback_days))
    last = data.iloc[-1]
    flow_3d = float(recent.tail(3)["main_net_inflow"].sum())
    flow_5d = float(recent.tail(5)["main_net_inflow"].sum())
    positive_days_5 = int((recent.tail(5)["main_net_inflow"] > 0).sum())
    main_net = float(last.get("main_net_inflow", 0.0) or 0.0)
    main_pct = float(last.get("main_net_inflow_pct", 0.0) or 0.0)
    return {
        "symbol": code,
        "date": last["date_norm"].date().isoformat(),
        "main_net_inflow": round(main_net, 2),
        "main_net_inflow_pct": round(main_pct, 4),
        "main_net_inflow_3d": round(flow_3d, 2),
        "main_net_inflow_5d": round(flow_5d, 2),
        "positive_flow_days_5": positive_days_5,
        "money_flow_score": _money_flow_score(main_net, main_pct, flow_3d, flow_5d, positive_days_5),
        "source": "eastmoney",
        "error": "",
    }


def normalize_iwencai_export(
    frame: pd.DataFrame,
    *,
    target_date: str,
    query: str = "",
    source: str = "",
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=IWENCAI_COLUMNS)
    data = frame.copy()
    symbol_col = _first_existing(data, ["symbol", "代码", "股票代码", "证券代码"])
    if symbol_col is None:
        raise ValueError("问财导入文件缺少 symbol/代码/股票代码 列")
    name_col = _first_existing(data, ["name", "名称", "股票简称", "证券简称"])
    score_col = _first_existing(data, ["iwencai_score", "综合评分", "评分", "得分"])
    tags_col = _first_existing(data, ["iwencai_tags", "标签", "概念", "所属概念", "题材"])

    output = pd.DataFrame()
    output["symbol"] = data[symbol_col].map(normalize_symbol)
    output["name"] = data[name_col].fillna("").astype(str) if name_col else ""
    output["date"] = target_date
    output["iwencai_hit"] = 1
    output["iwencai_rank"] = range(1, len(output) + 1)
    if score_col:
        output["iwencai_score"] = pd.to_numeric(data[score_col], errors="coerce").fillna(0.0)
    else:
        output["iwencai_score"] = output["iwencai_rank"].map(lambda rank: max(1.0, 10.0 - (rank - 1) * 0.2))
    output["iwencai_query"] = query
    output["iwencai_tags"] = data[tags_col].fillna("").astype(str) if tags_col else ""
    output["iwencai_reason"] = data.apply(_compact_reason, axis=1)
    output["source"] = source or "iwencai_csv"
    return output.loc[output["symbol"] != ""].drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)


def _compact_reason(row: pd.Series) -> str:
    parts = []
    for key, value in row.items():
        text = str(value).strip()
        if not text or text.lower() == "nan":
            continue
        if str(key) in {"代码", "股票代码", "symbol", "名称", "股票简称", "name"}:
            continue
        parts.append(f"{key}:{text}")
        if len(parts) >= 5:
            break
    return "；".join(parts)[:180]


def _empty_money_flow_row(symbol: str, target_date: str, *, error: str) -> dict:
    return {
        "symbol": normalize_symbol(symbol),
        "date": target_date,
        "main_net_inflow": 0.0,
        "main_net_inflow_pct": 0.0,
        "main_net_inflow_3d": 0.0,
        "main_net_inflow_5d": 0.0,
        "positive_flow_days_5": 0,
        "money_flow_score": 0.0,
        "source": "eastmoney",
        "error": error,
    }


def _fetch_with_retries(callable_obj, *, retries: int, retry_wait: float) -> tuple[pd.DataFrame, str]:
    attempts = max(1, int(retries) + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            return callable_obj(), ""
        except Exception as exc:  # pragma: no cover - depends on provider/network state
            last_error = f"attempt {attempt}/{attempts}: {type(exc).__name__}: {exc}"
            if attempt < attempts and retry_wait > 0:
                sleep(retry_wait)
    return pd.DataFrame(), last_error


def _money_flow_score(main_net: float, main_pct: float, flow_3d: float, flow_5d: float, positive_days_5: int) -> float:
    score = 0.0
    if main_net > 0:
        score += min(25.0, main_net / 100_000_000 * 8)
    if main_pct > 0:
        score += min(25.0, main_pct * 2)
    if flow_3d > 0:
        score += min(20.0, flow_3d / 300_000_000 * 8)
    if flow_5d > 0:
        score += min(15.0, flow_5d / 500_000_000 * 8)
    score += min(15.0, positive_days_5 * 3)
    if main_net < 0 and flow_3d < 0:
        score -= min(20.0, abs(flow_3d) / 300_000_000 * 8)
    return round(max(0.0, min(100.0, score)), 2)


def _ak_market(symbol: str) -> str:
    market = infer_market(normalize_symbol(symbol))
    if market in {"sh", "sz", "bj"}:
        return market
    return "sh" if str(symbol).startswith("6") else "sz"


def _first_existing(frame: pd.DataFrame, columns: list[str]) -> str | None:
    for column in columns:
        if column in frame.columns:
            return column
    return None


def _date_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.date().isoformat()


def _money_number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "nan", "None"}:
        return 0.0
    multiplier = 1.0
    if "亿" in text:
        multiplier = 100_000_000.0
    elif "万" in text:
        multiplier = 10_000.0
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    return float(match.group()) * multiplier


def _percent_number(value: object) -> float:
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
        number = float(match.group()) if match else 0.0
    return number * 100 if abs(number) <= 1 and "%" not in str(value) else number


def read_csv_flexible(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, dtype=str)
