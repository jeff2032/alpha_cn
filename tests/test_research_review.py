from __future__ import annotations

import pandas as pd
import pytest

import quant_a_stock.research.review as review_module
from quant_a_stock.config import ProjectPaths
from quant_a_stock.research.review import build_research_review
from quant_a_stock.research.review import save_research_review_reports


def test_build_research_review_summarizes_candidates_and_missed_movers(tmp_path, monkeypatch) -> None:
    paths = ProjectPaths(root=tmp_path, data_cache=tmp_path / "data" / "cache", reports=tmp_path / "reports")
    monkeypatch.setattr(review_module, "DEFAULT_PATHS", paths)

    universe_path = tmp_path / "data" / "universe" / "a_stock.csv"
    universe_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"symbol": "000001", "name": "一号股份", "market": "sz"},
            {"symbol": "000002", "name": "二号股份", "market": "sz"},
            {"symbol": "000003", "name": "三号股份", "market": "sz"},
        ]
    ).to_csv(universe_path, index=False)

    daily_dir = paths.data_cache / "akshare" / "daily"
    daily_dir.mkdir(parents=True)
    _write_daily(daily_dir / "000001.csv", "000001", [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    _write_daily(daily_dir / "000002.csv", "000002", [20.0, 19.0, 18.0, 17.0, 16.0, 15.0])
    _write_daily(daily_dir / "000003.csv", "000003", [30.0, 36.0, 37.0, 38.0, 39.0, 40.0])

    snapshot_root = tmp_path / "snapshots"
    snapshot_day = snapshot_root / "2026-06-12"
    snapshot_day.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "symbol": "000001",
                "name": "",
                "research_tier": "A2",
                "action_bucket": "主攻-A2启动确认",
                "risk_level": "低",
                "risk_tags": "",
                "research_score": 70,
                "setup_phase": "日线触发观察",
                "stage": "accumulation",
                "theme_cluster": "半导体链",
            },
            {
                "symbol": "000002",
                "name": "二号股份",
                "research_tier": "B2",
                "action_bucket": "补票-B2强主题",
                "risk_level": "中",
                "risk_tags": "观察补票",
                "research_score": 55,
                "setup_phase": "观察补票",
                "stage": "trend_pullback",
                "theme_cluster": "金融",
            },
        ]
    ).to_csv(snapshot_day / "research_candidates.csv", index=False)

    review = build_research_review(
        since="2026-06-12",
        until="2026-06-12",
        snapshot_root=snapshot_root,
        top_movers=1,
        universe_file=universe_path,
        min_market_count=1,
    )

    assert review.closed_signal_dates == ["2026-06-12"]
    assert set(review.details["symbol"]) == {"000001", "000002"}
    assert "model_bucket" in review.details.columns
    assert "action_bucket" in review.details.columns
    assert "preferred_ret" in review.details.columns
    assert "risk_tags" in review.details.columns
    buckets = dict(zip(review.details["symbol"], review.details["model_bucket"]))
    assert buckets["000001"] == "A1/A2_early_setup"
    assert buckets["000002"] == "B_watchlist"
    preferred = review.details[review.details["symbol"] == "000001"].iloc[0]
    assert preferred["evaluation_horizon"] == "3d_5d"
    assert preferred["preferred_horizon"] == "5d"
    assert preferred["outcome_label"] == "hit"
    a2 = review.by_tier[review.by_tier["tier"] == "A2"].iloc[0]
    assert a2["count"] == 1
    assert a2["avg_ret"] == pytest.approx(0.1)
    early_bucket = review.by_model_bucket[review.by_model_bucket["model_bucket"] == "A1/A2_early_setup"].iloc[0]
    assert early_bucket["count"] == 1
    assert not review.by_action_bucket.empty
    assert "主攻-A2启动确认" in set(review.by_action_bucket["action_bucket"])
    a2_horizon = review.by_tier_horizon[review.by_tier_horizon["tier"] == "A2"]
    assert set(a2_horizon["horizon"]) == {"1d", "3d", "5d"}
    assert a2_horizon[a2_horizon["horizon"] == "5d"]["avg_ret"].iloc[0] == pytest.approx(0.5)
    model_horizon = review.by_model_bucket_horizon[
        review.by_model_bucket_horizon["model_bucket"] == "A1/A2_early_setup"
    ]
    assert set(model_horizon["horizon"]) == {"1d", "3d", "5d"}
    capture = review.market_capture.iloc[0]
    assert capture["top_in_candidates"] == 0
    assert review.missed_movers.iloc[0]["symbol"] == "000003"
    assert review.missed_movers.iloc[0]["miss_reason"] == "形态未入池"
    assert review.missed_movers.iloc[0]["model_bucket"] in {"miss_learnable", "miss_event_only"}
    assert "is_learnable" in review.missed_movers.columns
    assert not review.miss_learnability.empty
    assert review.missed_movers.iloc[0]["risk_level"] in {"中", "中高", "高"}
    assert "未做公告风险核验" in review.missed_movers.iloc[0]["risk_tags"]

    markdown_path, details_path, summary_path = save_research_review_reports(review)

    assert markdown_path.exists()
    assert details_path.exists()
    assert summary_path.exists()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "模型桶 1/3/5 日表现" in markdown
    assert "动作分组首日表现" in markdown
    assert "亏损样本归因" in markdown
    assert "明显错过样本和风险提示" in markdown
    assert "risk_tags" in markdown


def _write_daily(path, symbol: str, closes: list[float]) -> None:
    rows = []
    dates = ["2026-06-12", "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"]
    for timestamp, close in zip(dates, closes):
        rows.append(
            {
                "timestamp": timestamp,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 10000,
                "amount": close * 10000,
                "symbol": symbol,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
