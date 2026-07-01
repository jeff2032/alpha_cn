from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS


def save_report(
    rows: Iterable[dict],
    *,
    report_type: str,
    reports_dir: Path | None = None,
    date_prefix: str | None = None,
) -> Path:
    root = reports_dir or DEFAULT_PATHS.reports
    root.mkdir(parents=True, exist_ok=True)
    if date_prefix:
        stamp = f"{date_prefix.replace('-', '')}_{datetime.now().strftime('%H%M%S')}"
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = root / f"{report_type}_{stamp}.csv"
    pd.DataFrame(list(rows)).to_csv(path, index=False)
    return path
