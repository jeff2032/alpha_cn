from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import sleep

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.universe import infer_market, normalize_symbol


FUNDAMENTAL_CACHE_ROOT = DEFAULT_PATHS.root / "data" / "cache" / "akshare" / "fundamentals"


@dataclass(frozen=True)
class FinancialFetchResult:
    symbol: str
    frame: pd.DataFrame
    source: str
    cache_path: Path
    error: str = ""


def fetch_financial_indicators(
    symbol: str,
    *,
    cache_root: Path | None = None,
    refresh: bool = False,
    retries: int = 2,
    retry_wait: float = 1.5,
) -> FinancialFetchResult:
    code = normalize_symbol(symbol)
    root = cache_root or FUNDAMENTAL_CACHE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    cache_path = root / f"{code}.csv"
    if cache_path.exists() and not refresh:
        try:
            cached = pd.read_csv(cache_path, dtype={"SECURITY_CODE": str})
            return FinancialFetchResult(code, cached, "eastmoney_cache", cache_path)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
            pass

    import akshare as ak

    market = infer_market(code).upper()
    secucode = f"{code}.{market}" if market in {"SH", "SZ", "BJ"} else code
    attempts = max(1, int(retries) + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            frame = ak.stock_financial_analysis_indicator_em(symbol=secucode, indicator="按报告期")
            if frame is None or frame.empty:
                raise ValueError("empty financial indicator response")
            frame.to_csv(cache_path, index=False, encoding="utf-8-sig")
            return FinancialFetchResult(code, frame, "eastmoney", cache_path)
        except Exception as exc:  # pragma: no cover - provider/network dependent
            last_error = f"attempt {attempt}/{attempts}: {type(exc).__name__}: {exc}"
            if attempt < attempts and retry_wait > 0:
                sleep(retry_wait)
    return FinancialFetchResult(code, pd.DataFrame(), "eastmoney", cache_path, last_error)

