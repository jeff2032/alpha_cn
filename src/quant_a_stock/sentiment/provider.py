from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_a_stock.data.universe import infer_market, normalize_symbol


@dataclass(frozen=True)
class FetchResult:
    frame: pd.DataFrame
    error: str = ""


def eastmoney_symbol(symbol: str) -> str:
    code = normalize_symbol(symbol)
    market = infer_market(code)
    if market == "sh":
        return f"SH{code}"
    if market == "sz":
        return f"SZ{code}"
    if market == "bj":
        return f"BJ{code}"
    return code


def strip_market_prefix(symbol: str) -> str:
    text = str(symbol).strip()
    if text.upper().startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return normalize_symbol(text)


def safe_fetch(callable_obj, *args, **kwargs) -> FetchResult:
    try:
        return FetchResult(callable_obj(*args, **kwargs))
    except Exception as exc:  # pragma: no cover - depends on provider/network state
        return FetchResult(pd.DataFrame(), f"{type(exc).__name__}: {exc}")


def fetch_hot_rank() -> FetchResult:
    import akshare as ak

    result = safe_fetch(ak.stock_hot_rank_em)
    if result.frame.empty:
        return result
    frame = result.frame.copy()
    if "代码" in frame.columns:
        frame["symbol"] = frame["代码"].map(strip_market_prefix)
    return FetchResult(frame, result.error)


def fetch_stock_news(symbol: str) -> FetchResult:
    import akshare as ak

    return safe_fetch(ak.stock_news_em, symbol=normalize_symbol(symbol))


def fetch_research_reports(symbol: str) -> FetchResult:
    import akshare as ak

    return safe_fetch(ak.stock_research_report_em, symbol=normalize_symbol(symbol))


def fetch_hot_keywords(symbol: str) -> FetchResult:
    import akshare as ak

    return safe_fetch(ak.stock_hot_keyword_em, symbol=eastmoney_symbol(symbol))


def fetch_hot_rank_latest(symbol: str) -> FetchResult:
    import akshare as ak

    return safe_fetch(ak.stock_hot_rank_latest_em, symbol=eastmoney_symbol(symbol))


def fetch_limit_pool(date: str) -> FetchResult:
    import akshare as ak

    return safe_fetch(ak.stock_zt_pool_em, date=date)


def fetch_strong_pool(date: str) -> FetchResult:
    import akshare as ak

    return safe_fetch(ak.stock_zt_pool_strong_em, date=date)
