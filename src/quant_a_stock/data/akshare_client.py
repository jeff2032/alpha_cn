from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from time import sleep
from typing import Literal

import pandas as pd

from quant_a_stock.cleaning.pipeline import clean_candles


AssetType = Literal["auto", "etf", "stock"]
ConcreteAssetType = Literal["etf", "stock"]
EtfProvider = Literal["eastmoney", "sina"]
StockProvider = Literal["eastmoney", "sina"]


@dataclass(frozen=True)
class FetchAttemptError:
    asset_type: ConcreteAssetType
    attempt: int
    error_type: str
    message: str


class FetchDailyError(RuntimeError):
    def __init__(self, symbol: str, errors: list[FetchAttemptError]) -> None:
        details = "; ".join(
            f"{error.asset_type} attempt {error.attempt}: "
            f"{error.error_type}: {error.message}"
            for error in errors
        )
        super().__init__(f"Failed to fetch daily data for {symbol}. Attempts: {details}")
        self.symbol = symbol
        self.errors = errors


def _compact_date(value: str | date | None, default: str) -> str:
    if value is None:
        return default
    return pd.Timestamp(value).strftime("%Y%m%d")


def _normalize_adjust(adjust: str) -> str:
    normalized = adjust.strip().lower()
    if normalized in {"none", "no", "raw", "unadjusted"}:
        return ""
    return normalized


def _looks_like_etf(symbol: str) -> bool:
    return symbol.startswith(("1", "5"))


def _candidate_asset_types(symbol: str, asset_type: AssetType) -> list[ConcreteAssetType]:
    if asset_type == "auto":
        return ["etf"] if _looks_like_etf(symbol) else ["stock"]
    return [asset_type]


def _rename_akshare_columns(frame: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "日期": "timestamp",
        "date": "timestamp",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }
    return frame.rename(columns=rename_map)


def _sina_etf_symbol(symbol: str) -> str:
    if symbol.startswith("5"):
        return f"sh{symbol}"
    if symbol.startswith("1"):
        return f"sz{symbol}"
    raise ValueError(f"Cannot infer Sina ETF market prefix for {symbol}")


def _sina_stock_symbol(symbol: str) -> str:
    if symbol.startswith(("6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("0", "2", "3")):
        return f"sz{symbol}"
    raise ValueError(f"Cannot infer Sina stock market prefix for {symbol}")


def _fetch_etf_eastmoney(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> pd.DataFrame:
    import akshare as ak

    return ak.fund_etf_hist_em(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )


def _fetch_etf_sina(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> pd.DataFrame:
    if adjust:
        raise ValueError("Sina ETF provider does not support adjusted data; use --adjust none")

    import akshare as ak

    frame = ak.fund_etf_hist_sina(symbol=_sina_etf_symbol(symbol))
    if frame.empty:
        return frame

    renamed = _rename_akshare_columns(frame)
    renamed["timestamp"] = pd.to_datetime(renamed["timestamp"])
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return renamed[(renamed["timestamp"] >= start) & (renamed["timestamp"] <= end)]


def _fetch_etf(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
    provider: EtfProvider,
) -> pd.DataFrame:
    if provider == "eastmoney":
        return _fetch_etf_eastmoney(symbol, start_date, end_date, adjust)
    if provider == "sina":
        return _fetch_etf_sina(symbol, start_date, end_date, adjust)
    raise ValueError(f"Unsupported ETF provider: {provider}")


def _fetch_stock_eastmoney(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )


def _fetch_stock_sina(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> pd.DataFrame:
    import akshare as ak

    frame = ak.stock_zh_a_daily(
        symbol=_sina_stock_symbol(symbol),
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )
    if frame.empty:
        return frame

    output = frame.copy()
    if "date" in output.columns:
        output = _rename_akshare_columns(output)
    else:
        output = output.reset_index().rename(columns={"index": "timestamp"})
    return output


def _fetch_stock(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
    provider: StockProvider,
) -> pd.DataFrame:
    if provider == "eastmoney":
        return _fetch_stock_eastmoney(symbol, start_date, end_date, adjust)
    if provider == "sina":
        return _fetch_stock_sina(symbol, start_date, end_date, adjust)
    raise ValueError(f"Unsupported stock provider: {provider}")


def fetch_daily(
    symbol: str,
    *,
    since: str | date | None = None,
    until: str | date | None = None,
    adjust: str = "qfq",
    asset_type: AssetType = "auto",
    etf_provider: EtfProvider = "eastmoney",
    stock_provider: StockProvider = "eastmoney",
    retries: int = 3,
    retry_wait: float = 1.0,
) -> pd.DataFrame:
    """Fetch daily candles from AKShare and return standard cleaned columns."""

    start_date = _compact_date(since, "19900101")
    end_date = _compact_date(until, "20500101")
    symbol = str(symbol).strip()
    adjust = _normalize_adjust(adjust)

    fetch_order = _candidate_asset_types(symbol, asset_type)
    max_attempts = max(1, retries)

    errors: list[FetchAttemptError] = []
    for candidate in fetch_order:
        for attempt in range(1, max_attempts + 1):
            try:
                raw = (
                    _fetch_etf(symbol, start_date, end_date, adjust, etf_provider)
                    if candidate == "etf"
                    else _fetch_stock(symbol, start_date, end_date, adjust, stock_provider)
                )
                if raw.empty:
                    raise ValueError(f"AKShare returned no rows for {symbol} as {candidate}")
                renamed = _rename_akshare_columns(raw)
                return clean_candles(renamed, symbol=symbol)
            except Exception as exc:  # pragma: no cover - depends on network/provider state
                errors.append(
                    FetchAttemptError(
                        asset_type=candidate,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                if attempt < max_attempts and retry_wait > 0:
                    sleep(retry_wait)

    raise FetchDailyError(symbol, errors)
