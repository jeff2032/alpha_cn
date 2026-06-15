from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class StrategyParameters:
    fast_window: int = 20
    slow_window: int = 60
    trend_window: int = 120


class Strategy(Protocol):
    name: str

    def generate_signals(
        self, candles: pd.DataFrame, parameters: StrategyParameters
    ) -> pd.Series:
        ...


def assert_long_only_signal(signal: pd.Series) -> None:
    allowed = {0, 1}
    values = set(signal.dropna().astype(int).unique())
    if not values.issubset(allowed):
        raise ValueError(f"Long-only signal must only contain 0/1, got {sorted(values)}")


def build_stateful_long_signal(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """Build a 0/1 long-only holding signal from entry and exit conditions."""

    if len(entry) != len(exit_):
        raise ValueError("entry and exit conditions must have the same length")

    holding = 0
    values: list[int] = []
    for should_enter, should_exit in zip(entry.fillna(False), exit_.fillna(False)):
        if holding and bool(should_exit):
            holding = 0
        if not holding and bool(should_enter):
            holding = 1
        values.append(holding)

    signal = pd.Series(values, index=entry.index, name="signal", dtype="int64")
    assert_long_only_signal(signal)
    return signal
