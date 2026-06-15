from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RiskConfig:
    max_single_position: float = 1.0
    max_total_position: float = 1.0
    max_drawdown_circuit_breaker: float | None = None
    consecutive_loss_pause_days: int = 0
    allow_st: bool = False
    allow_suspended: bool = False


def apply_basic_risk_rules(
    candles: pd.DataFrame,
    signal: pd.Series,
    *,
    config: RiskConfig = RiskConfig(),
) -> pd.Series:
    """Apply first-phase long-only risk filters to a single-symbol signal."""

    filtered = signal.fillna(0).clip(lower=0, upper=1).astype(float)
    filtered *= min(config.max_single_position, config.max_total_position)

    if not config.allow_suspended and "is_suspended" in candles.columns:
        filtered = filtered.mask(candles["is_suspended"].fillna(False), 0.0)

    if not config.allow_st and "is_st" in candles.columns:
        filtered = filtered.mask(candles["is_st"].fillna(False), 0.0)

    return filtered

