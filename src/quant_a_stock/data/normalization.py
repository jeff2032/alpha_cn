from __future__ import annotations

import pandas as pd


def normalize_a_share_volume(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize A-share daily volume to shares using amount-implied VWAP.

    AKShare providers commonly expose volume in lots (100 shares), while some
    fallback endpoints expose shares. The amount/price relationship lets us
    normalize mixed-provider cache rows without relying on provider metadata.
    """

    output = frame.copy()
    required = {"close", "volume", "amount"}
    if output.empty or not required.issubset(output.columns):
        return output

    close = pd.to_numeric(output["close"], errors="coerce")
    volume = pd.to_numeric(output["volume"], errors="coerce")
    amount = pd.to_numeric(output["amount"], errors="coerce")
    implied_multiplier = amount / (close * volume)
    lot_rows = close.gt(0) & volume.gt(0) & amount.gt(0) & implied_multiplier.between(20, 500)
    output.loc[lot_rows, "volume"] = volume.loc[lot_rows] * 100
    return output
