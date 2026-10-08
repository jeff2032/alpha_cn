from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.cache import STANDARD_COLUMNS
from quant_a_stock.data.normalization import normalize_a_share_volume


AUDIT_COLUMNS = [
    "symbol",
    "name",
    "target_date",
    "last_date",
    "rows",
    "quality_status",
    "quarantined",
    "issue",
    "basis_jump_count",
    "extreme_return_count",
    "max_abs_return",
    "normalized_volume_rows",
]


@dataclass(frozen=True)
class DailyCacheAuditConfig:
    recent_days: int = 190
    basis_jump_threshold: float = 0.15
    min_basis_jumps: int = 8
    extreme_return_threshold: float = 0.45
    min_extreme_returns: int = 1


def audit_daily_cache(
    universe: pd.DataFrame,
    *,
    target_date: str | pd.Timestamp,
    cache_dir: Path | None = None,
    config: DailyCacheAuditConfig | None = None,
) -> pd.DataFrame:
    config = config or DailyCacheAuditConfig()
    target = pd.Timestamp(target_date).normalize()
    cutoff = target - pd.Timedelta(days=max(1, config.recent_days))
    daily_dir = (cache_dir or DEFAULT_PATHS.data_cache) / "akshare" / "daily"
    names = _name_map(universe)
    rows = [
        _audit_symbol(
            symbol,
            names.get(symbol, ""),
            path=daily_dir / f"{symbol}.csv",
            target=target,
            cutoff=cutoff,
            config=config,
        )
        for symbol in sorted(names)
    ]
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def _audit_symbol(
    symbol: str,
    name: str,
    *,
    path: Path,
    target: pd.Timestamp,
    cutoff: pd.Timestamp,
    config: DailyCacheAuditConfig,
) -> dict[str, object]:
    base = {
        "symbol": symbol,
        "name": name,
        "target_date": target.date().isoformat(),
        "last_date": "",
        "rows": 0,
        "quality_status": "CRITICAL",
        "quarantined": True,
        "issue": "缓存文件缺失",
        "basis_jump_count": 0,
        "extreme_return_count": 0,
        "max_abs_return": 0.0,
        "normalized_volume_rows": 0,
    }
    if not path.exists():
        return base
    try:
        frame = pd.read_csv(path, dtype={"symbol": str})
    except Exception as exc:
        return {**base, "issue": f"缓存无法读取: {type(exc).__name__}: {exc}"}

    base["rows"] = len(frame)
    missing = set(STANDARD_COLUMNS) - set(frame.columns)
    if missing:
        return {**base, "issue": f"缺少字段: {','.join(sorted(missing))}"}

    timestamp = pd.to_datetime(frame["timestamp"], errors="coerce")
    prices = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    amount = pd.to_numeric(frame["amount"], errors="coerce")
    raw_multiplier = amount / (prices["close"] * volume)
    base["normalized_volume_rows"] = int(raw_multiplier.between(20, 500).sum())
    normalized = normalize_a_share_volume(frame)
    volume = pd.to_numeric(normalized["volume"], errors="coerce")

    structural_issues: list[str] = []
    if timestamp.isna().any():
        structural_issues.append("时间字段无效")
    if timestamp.duplicated().any():
        structural_issues.append("日期重复")
    if not timestamp.is_monotonic_increasing:
        structural_issues.append("日期未排序")
    if prices.isna().any().any() or (prices <= 0).any().any():
        structural_issues.append("价格缺失或非正数")
    invalid_ohlc = (prices["high"] < prices[["open", "close", "low"]].max(axis=1)) | (
        prices["low"] > prices[["open", "close", "high"]].min(axis=1)
    )
    if invalid_ohlc.any():
        structural_issues.append("OHLC关系异常")
    if (volume < 0).any() or (amount < 0).any():
        structural_issues.append("成交量或成交额为负")

    valid_dates = timestamp.dropna()
    if not valid_dates.empty:
        base["last_date"] = valid_dates.max().date().isoformat()

    recent = timestamp.ge(cutoff) & timestamp.le(target)
    valid_trade = volume.gt(0) & amount.gt(0) & prices["close"].gt(0)
    basis = (amount / (volume * prices["close"])).where(valid_trade)
    basis_jumps = basis.pct_change(fill_method=None).abs().gt(config.basis_jump_threshold) & recent
    returns = prices["close"].pct_change(fill_method=None)
    extreme_returns = returns.abs().gt(config.extreme_return_threshold) & recent
    base["basis_jump_count"] = int(basis_jumps.sum())
    base["extreme_return_count"] = int(extreme_returns.sum())
    recent_returns = returns[recent].abs().dropna()
    base["max_abs_return"] = round(float(recent_returns.max()), 6) if not recent_returns.empty else 0.0

    unstable_basis = (
        int(base["basis_jump_count"]) >= config.min_basis_jumps
        and int(base["extreme_return_count"]) >= config.min_extreme_returns
    )
    if structural_issues:
        return {**base, "issue": ";".join(structural_issues)}
    if unstable_basis:
        return {
            **base,
            "issue": "前复权基准频繁跳变，疑似混合数据源或历史复权拼接污染",
        }
    if base["last_date"] and pd.Timestamp(base["last_date"]) < target:
        return {
            **base,
            "quality_status": "WARN",
            "quarantined": False,
            "issue": "目标日无K线，可能停牌、退市或源端缺失",
        }
    return {**base, "quality_status": "OK", "quarantined": False, "issue": ""}


def _name_map(universe: pd.DataFrame) -> dict[str, str]:
    if universe.empty or "symbol" not in universe.columns:
        return {}
    symbols = universe["symbol"].astype(str).str.zfill(6)
    if "name" not in universe.columns:
        return dict.fromkeys(symbols, "")
    names = universe["name"].fillna("").astype(str)
    return dict(zip(symbols, names))
