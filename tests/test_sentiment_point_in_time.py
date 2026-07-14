from __future__ import annotations

import pandas as pd

from quant_a_stock.sentiment import score
from quant_a_stock.sentiment.provider import FetchResult
from quant_a_stock.sentiment.score import SentimentConfig
from quant_a_stock.sentiment.score import build_sentiment_scores


def test_historical_sentiment_blocks_live_only_sources(monkeypatch) -> None:
    live_calls: list[str] = []

    monkeypatch.setattr(score, "fetch_hot_rank", lambda: live_calls.append("rank") or FetchResult(pd.DataFrame()))
    monkeypatch.setattr(
        score,
        "fetch_hot_keywords",
        lambda symbol: live_calls.append(f"keywords:{symbol}") or FetchResult(pd.DataFrame()),
    )
    monkeypatch.setattr(
        score,
        "fetch_hot_rank_latest",
        lambda symbol: live_calls.append(f"latest:{symbol}") or FetchResult(pd.DataFrame()),
    )
    monkeypatch.setattr(score, "fetch_limit_pool", lambda date: FetchResult(pd.DataFrame()))
    monkeypatch.setattr(score, "fetch_strong_pool", lambda date: FetchResult(pd.DataFrame()))
    monkeypatch.setattr(score, "fetch_stock_news", lambda symbol: FetchResult(pd.DataFrame()))
    monkeypatch.setattr(score, "fetch_research_reports", lambda symbol: FetchResult(pd.DataFrame()))

    result, meta = build_sentiment_scores(
        pd.DataFrame([{"symbol": "002137", "name": "实益达"}]),
        config=SentimentConfig(target_date="2020-01-02"),
    )

    assert live_calls == []
    assert not result.loc[0, "point_in_time"]
    assert result.loc[0, "data_mode"] == "historical_date_filtered"
    assert meta["data_mode"] == "historical_date_filtered"


def test_explicit_live_historical_mode_is_marked_non_point_in_time(monkeypatch) -> None:
    empty = FetchResult(pd.DataFrame())
    monkeypatch.setattr(score, "fetch_hot_rank", lambda: empty)
    monkeypatch.setattr(score, "fetch_hot_keywords", lambda symbol: empty)
    monkeypatch.setattr(score, "fetch_hot_rank_latest", lambda symbol: empty)
    monkeypatch.setattr(score, "fetch_limit_pool", lambda date: empty)
    monkeypatch.setattr(score, "fetch_strong_pool", lambda date: empty)
    monkeypatch.setattr(score, "fetch_stock_news", lambda symbol: empty)
    monkeypatch.setattr(score, "fetch_research_reports", lambda symbol: empty)

    result, meta = build_sentiment_scores(
        pd.DataFrame([{"symbol": "002137", "name": "实益达"}]),
        config=SentimentConfig(target_date="2020-01-02", allow_live_historical=True),
    )

    assert not result.loc[0, "point_in_time"]
    assert result.loc[0, "data_mode"] == "historical_with_live_sources"
    assert not meta["point_in_time"]
