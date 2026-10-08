from __future__ import annotations

import numpy as np
import pandas as pd

from quant_a_stock.research.observation_pool import evaluate_latent_catalyst_history


def test_latent_catalyst_history_uses_next_open_and_marks_execution() -> None:
    close = pd.Series(np.concatenate([np.linspace(20, 12, 190), np.linspace(12, 13.5, 30)]))
    frame = pd.DataFrame(
        {
            "timestamp": pd.bdate_range("2025-01-01", periods=len(close)),
            "open": close * 1.001,
            "high": close * 1.02,
            "low": close * 0.99,
            "close": close,
            "volume": 1_200_000.0,
            "amount": close * 1_200_000 * 100,
            "symbol": "000001",
        }
    )

    review = evaluate_latent_catalyst_history(
        {"000001": frame},
        since=str(frame.iloc[0]["timestamp"].date()),
        until=str(frame.iloc[205]["timestamp"].date()),
        min_score=30,
    )

    assert not review.details.empty
    executable = review.details[review.details["executable"]]
    assert not executable.empty
    first = executable.iloc[0]
    signal_index = frame.index[frame["timestamp"].eq(pd.Timestamp(first["signal_date"]))][0]
    assert first["entry_open"] == round(float(frame.iloc[signal_index + 1]["open"]), 4)
    assert "ret_5d_from_open" in review.details.columns
    assert not review.summary.empty
