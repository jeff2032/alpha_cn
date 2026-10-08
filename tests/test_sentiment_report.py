from __future__ import annotations

import pandas as pd

import quant_a_stock.sentiment.report as report_module
from quant_a_stock.config import ProjectPaths
from quant_a_stock.sentiment.report import save_market_theme_markdown
from quant_a_stock.sentiment.score import _normalize_industry_name


def test_market_theme_report_explains_hot_rank_provider_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report_module, "DEFAULT_PATHS", ProjectPaths(root=tmp_path))
    theme = pd.DataFrame(
        [
            {
                "theme": "半导体",
                "theme_score": 115.0,
                "limit_count": 4,
                "strong_count": 49,
                "stock_count": 53,
            }
        ]
    )

    path = save_market_theme_markdown(
        theme,
        {
            "target_date": "2026-06-18",
            "hot_rank_error": "ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))",
            "hot_top": [],
        },
    )

    text = path.read_text(encoding="utf-8")

    assert "半导体：主线分 115.0" in text
    assert "人气榜暂不可用：东财接口临时断开" in text
    assert "东财人气榜：接口临时断开" in text


def test_market_theme_restores_known_truncated_industry_names() -> None:
    assert _normalize_industry_name("房地产开") == "房地产开发"
    assert _normalize_industry_name("汽车零部") == "汽车零部件"
    assert _normalize_industry_name("半导体") == "半导体"
