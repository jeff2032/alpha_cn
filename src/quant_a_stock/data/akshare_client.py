from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from threading import local
from time import sleep
from typing import Literal

import pandas as pd

from quant_a_stock.cleaning.pipeline import clean_candles


AssetType = Literal["auto", "etf", "stock"]
ConcreteAssetType = Literal["etf", "stock"]
EtfProvider = Literal["eastmoney", "sina", "tencent"]
StockProvider = Literal["eastmoney", "sina", "tencent"]


_HTTP_STATE = local()


def _http_session():
    """Reuse HTTP connections inside each downloader worker thread."""

    import requests

    session = getattr(_HTTP_STATE, "session", None)
    if session is None:
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AlphaCN/0.1",
                "Connection": "keep-alive",
            }
        )
        _HTTP_STATE.session = session
    return session


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


def _parse_tencent_etf_rows(rows: list[list[object]]) -> pd.DataFrame:
    return _parse_tencent_rows(rows, volume_multiplier=100)


def _parse_tencent_stock_rows(rows: list[list[object]]) -> pd.DataFrame:
    return _parse_tencent_rows(rows, volume_multiplier=100)


def _parse_tencent_rows(
    rows: list[list[object]],
    *,
    volume_multiplier: int,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for row in rows:
        if len(row) < 9:
            continue
        records.append(
            {
                "timestamp": row[0],
                "open": row[1],
                "close": row[2],
                "high": row[3],
                "low": row[4],
                "volume": pd.to_numeric(row[5], errors="coerce") * volume_multiplier,
                # 腾讯 K 线的成交额单位为万元。
                "amount": pd.to_numeric(row[8], errors="coerce") * 10_000,
            }
        )
    return pd.DataFrame.from_records(records)


def _fetch_tencent_rows(
    market_symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> list[list[object]]:
    from akshare.utils import demjson

    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    all_rows: list[list[object]] = []
    for year in range(int(start_date[:4]), int(end_date[:4]) + 1):
        params = {
            "_var": f"kline_day{adjust}{year}",
            "param": f"{market_symbol},day,{year}-01-01,{year}-12-31,640,{adjust}",
            "r": "0.8205512681390605",
        }
        response = _http_session().get(url, params=params, timeout=(5, 15))
        response.raise_for_status()
        marker = response.text.find("={")
        if marker < 0:
            raise ValueError(f"Tencent returned an unexpected payload for {market_symbol}")
        payload = demjson.decode(response.text[marker + 1 :])
        symbol_data = payload.get("data", {}).get(market_symbol, {})
        row_key = f"{adjust}day" if adjust else "day"
        all_rows.extend(symbol_data.get(row_key, []))
    return all_rows


def _filter_tencent_frame(
    frame: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if frame.empty:
        return frame

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return frame[
        (frame["timestamp"] >= start) & (frame["timestamp"] <= end)
    ].drop_duplicates(subset=["timestamp"], keep="last")


def _fetch_etf_tencent(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> pd.DataFrame:
    if adjust:
        raise ValueError("Tencent ETF provider does not support adjusted data; use --adjust none")

    rows = _fetch_tencent_rows(_sina_etf_symbol(symbol), start_date, end_date, adjust)
    return _filter_tencent_frame(
        _parse_tencent_etf_rows(rows),
        start_date=start_date,
        end_date=end_date,
    )


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
    if provider == "tencent":
        return _fetch_etf_tencent(symbol, start_date, end_date, adjust)
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


def _fetch_stock_tencent(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> pd.DataFrame:
    rows = _fetch_tencent_rows(_sina_stock_symbol(symbol), start_date, end_date, adjust)
    return _filter_tencent_frame(
        _parse_tencent_stock_rows(rows),
        start_date=start_date,
        end_date=end_date,
    )


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
    if provider == "tencent":
        return _fetch_stock_tencent(symbol, start_date, end_date, adjust)
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
