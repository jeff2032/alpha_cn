from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.data.cache import save_daily_cache
from quant_a_stock.research.lifecycle import build_candidate_lifecycle_tracking
from quant_a_stock.research.lifecycle import save_candidate_lifecycle_reports


def _write_snapshot(root: Path, date: str, rows: list[dict]) -> None:
    day_dir = root / date
    day_dir.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(day_dir / "research_candidates.csv", index=False)


def test_candidate_lifecycle_tracks_upgrade_and_hit(tmp_path: Path) -> None:
    snapshot_root = tmp_path / "snapshots"
    cache_dir = tmp_path / "cache"
    universe_file = tmp_path / "a_stock.csv"
    pd.DataFrame(
        [
            {"symbol": "002137", "name": "实益达", "market": "sz"},
            {"symbol": "600999", "name": "招商证券", "market": "sh"},
        ]
    ).to_csv(universe_file, index=False)
    dates = pd.date_range("2026-06-01", periods=8, freq="D")
    save_daily_cache(
        pd.DataFrame(
            {
                "timestamp": dates,
                "open": [10, 10.2, 10.8, 11.0, 11.2, 11.5, 11.8, 12.0],
                "high": [10.2, 10.8, 11.4, 11.6, 12.1, 12.3, 12.4, 12.5],
                "low": [9.8, 10.0, 10.6, 10.8, 11.0, 11.3, 11.5, 11.8],
                "close": [10.0, 10.6, 11.0, 11.2, 11.8, 12.0, 12.2, 12.3],
                "volume": [100] * 8,
                "amount": [1000] * 8,
                "symbol": ["002137"] * 8,
            }
        ),
        "002137",
        cache_dir=cache_dir,
    )
    save_daily_cache(
        pd.DataFrame(
            {
                "timestamp": dates,
                "open": [20] * 8,
                "high": [20.2] * 8,
                "low": [19.8] * 8,
                "close": [20] * 8,
                "volume": [100] * 8,
                "amount": [1000] * 8,
                "symbol": ["600999"] * 8,
            }
        ),
        "600999",
        cache_dir=cache_dir,
    )

    _write_snapshot(
        snapshot_root,
        "2026-06-01",
        [
                {
                    "symbol": "002137",
                    "name": "",
                "research_tier": "B2",
                "action_bucket": "补票-B2强主题",
                "research_score": 61,
                "risk_level": "低",
                "matched_theme": "半导体链",
            },
            {
                "symbol": "600999",
                "name": "招商证券",
                "research_tier": "A1",
                "action_bucket": "观察-A1低位潜伏",
                "research_score": 55,
            },
        ],
    )
    _write_snapshot(
        snapshot_root,
        "2026-06-02",
        [
                {
                    "symbol": "002137",
                    "name": "",
                "research_tier": "A2",
                "action_bucket": "主攻-A2启动确认",
                "research_score": 72,
                "risk_level": "低",
                "matched_theme": "半导体链",
            }
        ],
    )
    _write_snapshot(
        snapshot_root,
        "2026-06-03",
        [
            {
                "symbol": "600999",
                "name": "招商证券",
                "research_tier": "A3",
                "action_bucket": "主攻-A3趋势延续",
                "research_score": 70,
                "risk_level": "中",
            }
        ],
    )
    for date in ["2026-06-04", "2026-06-05", "2026-06-06", "2026-06-07", "2026-06-08"]:
        _write_snapshot(
            snapshot_root,
            date,
            [
                {
                    "symbol": "600999",
                    "name": "招商证券",
                    "research_tier": "A1",
                    "action_bucket": "观察-A1低位潜伏",
                    "research_score": 50,
                }
            ],
        )

    tracking = build_candidate_lifecycle_tracking(
        until="2026-06-08",
        snapshot_root=snapshot_root,
        cache_dir=cache_dir,
        universe_file=universe_file,
    )

    lifecycle = tracking.lifecycles.loc[tracking.lifecycles["symbol"] == "002137"].iloc[0]
    assert lifecycle["name"] == "实益达"
    assert lifecycle["first_action_bucket"] == "补票-B2强主题"
    assert lifecycle["highest_action_bucket"] == "主攻-A2启动确认"
    assert bool(lifecycle["has_upgrade"]) is True
    assert lifecycle["result_label"] == "strong_hit"

    daily = tracking.daily[tracking.daily["symbol"] == "002137"]
    assert "upgraded" in set(daily["day_status"])

    lifecycle_path, daily_path, md_path = save_candidate_lifecycle_reports(tracking, reports_dir=tmp_path)
    assert lifecycle_path.exists()
    assert daily_path.exists()
    assert "候选生命周期跟踪" in md_path.read_text(encoding="utf-8")
