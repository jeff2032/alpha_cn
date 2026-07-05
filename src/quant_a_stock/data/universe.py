from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.cache import daily_cache_path


UniverseProvider = Literal["auto", "eastmoney", "exchange", "sina"]


@dataclass(frozen=True)
class StockUniverse:
    frame: pd.DataFrame
    provider: str


def normalize_symbol(value: str | int) -> str:
    text = str(value).strip()
    if "." in text:
        text = text.split(".")[-1]
    if text.lower().startswith(("sh", "sz", "bj")):
        text = text[2:]
    return text.zfill(6)


def infer_market(symbol: str) -> str:
    symbol = normalize_symbol(symbol)
    if symbol.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh"
    if symbol.startswith(("000", "001", "002", "003", "300", "301")):
        return "sz"
    if symbol.startswith(("4", "8", "9")):
        return "bj"
    return "unknown"


def is_supported_a_stock_symbol(symbol: str, markets: set[str] | None = None) -> bool:
    market = infer_market(symbol)
    if market == "unknown":
        return False
    return markets is None or market in markets


def _standardize_universe_frame(frame: pd.DataFrame, *, provider: str) -> StockUniverse:
    if frame.empty:
        return StockUniverse(pd.DataFrame(columns=["symbol", "name", "market"]), provider)

    rename_map = {
        "代码": "symbol",
        "证券代码": "symbol",
        "A股代码": "symbol",
        "名称": "name",
        "证券简称": "name",
        "A股简称": "name",
    }
    output = frame.rename(columns=rename_map).copy()
    if "symbol" not in output.columns:
        raise ValueError(f"Universe provider {provider} did not return a symbol column")
    if "name" not in output.columns:
        output["name"] = ""

    output["symbol"] = output["symbol"].map(normalize_symbol)
    output["name"] = output["name"].fillna("").astype(str)
    output["market"] = output["symbol"].map(infer_market)
    output = output[output["market"] != "unknown"]
    output = output.drop_duplicates(subset=["symbol"], keep="first")
    output = output.sort_values("symbol").reset_index(drop=True)
    return StockUniverse(output[["symbol", "name", "market"]], provider)


def fetch_stock_universe(provider: UniverseProvider = "auto") -> StockUniverse:
    import akshare as ak

    providers = ["eastmoney", "exchange", "sina"] if provider == "auto" else [provider]
    errors: list[str] = []

    for candidate in providers:
        try:
            if candidate == "eastmoney":
                return _standardize_universe_frame(ak.stock_zh_a_spot_em(), provider=candidate)
            if candidate == "exchange":
                return _standardize_universe_frame(ak.stock_info_a_code_name(), provider=candidate)
            if candidate == "sina":
                return _standardize_universe_frame(ak.stock_zh_a_spot(), provider=candidate)
            raise ValueError(f"Unsupported universe provider: {candidate}")
        except Exception as exc:  # pragma: no cover - depends on provider/network state
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")

    raise RuntimeError("Failed to fetch stock universe. Attempts: " + "; ".join(errors))


def filter_universe(
    universe: pd.DataFrame,
    *,
    markets: set[str] | None = None,
    exclude_st: bool = True,
) -> pd.DataFrame:
    output = universe.copy()
    output["symbol"] = output["symbol"].map(normalize_symbol)
    if "name" not in output.columns:
        output["name"] = ""
    if "market" not in output.columns:
        output["market"] = output["symbol"].map(infer_market)

    if markets is not None:
        output = output[output["market"].isin(markets)]
    if exclude_st:
        output = output[~output["name"].str.contains("ST", case=False, na=False)]

    return output.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)


def merge_universe_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge universe snapshots without dropping symbols from older snapshots."""

    standardized = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        standardized.append(_standardize_universe_frame(frame, provider="merge").frame)

    if not standardized:
        return pd.DataFrame(columns=["symbol", "name", "market"])

    output = pd.concat(standardized, ignore_index=True, sort=False)
    output["symbol"] = output["symbol"].map(normalize_symbol)
    output["market"] = output["symbol"].map(infer_market)
    output["name"] = output["name"].fillna("").astype(str)
    output = output.sort_values(["symbol", "name"], ascending=[True, False])
    output = output.drop_duplicates(subset=["symbol"], keep="first")
    return output.sort_values("symbol").reset_index(drop=True)[["symbol", "name", "market"]]


def load_universe_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Universe file not found: {path}")

    if path.suffix.lower() in {".csv", ".txt"}:
        try:
            frame = pd.read_csv(path, dtype={"symbol": str, "代码": str})
        except pd.errors.ParserError:
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
            frame = pd.DataFrame({"symbol": [line for line in lines if line]})
    else:
        raise ValueError(f"Unsupported universe file type: {path.suffix}")

    if len(frame.columns) == 1 and frame.columns[0] not in {"symbol", "代码"}:
        frame = frame.rename(columns={frame.columns[0]: "symbol"})
    return _standardize_universe_frame(frame, provider=str(path)).frame


def save_universe_file(
    universe: pd.DataFrame,
    *,
    path: Path | None = None,
) -> Path:
    output_path = path or DEFAULT_PATHS.root / "data" / "universe" / "a_stock.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    universe.to_csv(output_path, index=False)
    return output_path


def missing_cached_symbols(symbols: list[str]) -> list[str]:
    missing = []
    for symbol in symbols:
        if not daily_cache_path(symbol).exists():
            missing.append(symbol)
    return missing
