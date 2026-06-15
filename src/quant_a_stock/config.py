from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProjectPaths:
    root: Path = PROJECT_ROOT
    data_cache: Path = PROJECT_ROOT / "data" / "cache"
    reports: Path = PROJECT_ROOT / "reports"

    def ensure(self) -> None:
        self.data_cache.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    buy_commission_rate: float = 0.0003
    sell_commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.0
    trade_on_next_bar: bool = True
    t_plus_1: bool = True


DEFAULT_PATHS = ProjectPaths()
DEFAULT_BACKTEST_CONFIG = BacktestConfig()

