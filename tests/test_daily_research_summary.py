from __future__ import annotations

import pandas as pd

from quant_a_stock.research.summary import _candidate_reason_lines
from quant_a_stock.research.summary import _apply_market_shock_cap
from quant_a_stock.research.summary import classify_theme_cluster


def test_classify_theme_cluster_uses_keywords_and_reports() -> None:
    row = pd.Series(
        {
            "matched_theme": "",
            "industry": "化学原料和化学制品制造业",
            "top_keywords": "液冷概念、半导体概念、氟化工",
            "latest_report": "卡位先进制程核心环节，半导体材料国产替代",
        }
    )

    assert classify_theme_cluster(row) == "半导体链"


def test_market_shock_cap_forces_defensive_regime_score() -> None:
    components = pd.DataFrame(
        [
            {"ret1": -0.03, "ret3": -0.02, "ret5": -0.04},
            {"ret1": -0.036, "ret3": -0.014, "ret5": -0.026},
            {"ret1": -0.056, "ret3": -0.047, "ret5": -0.082},
        ]
    )

    assert _apply_market_shock_cap(components, 80.0) == 35.0


def test_classify_theme_cluster_falls_back_to_keyword_name() -> None:
    row = pd.Series({"top_keywords": "未知概念", "industry": "其他行业"})

    assert classify_theme_cluster(row) == "未知概念"


def test_classify_theme_cluster_names_common_low_level_sectors() -> None:
    rows = [
        ({"name": "青龙管业", "top_keywords": "地下管网、水利建设、新型城镇化"}, "水利基建"),
        ({"name": "唐山港", "industry": "水上运输业", "top_keywords": "国企改革"}, "港口航运"),
        ({"name": "江苏金租", "industry": "货币金融服务", "top_keywords": "机构重仓"}, "金融"),
        ({"name": "山西焦煤", "industry": "煤炭开采和洗选业"}, "煤炭资源"),
        ({"name": "广深铁路", "industry": "铁路运输业"}, "交通运输"),
        ({"name": "长信科技", "industry": "计算机、通信和其他电子设备制造业", "top_keywords": "光学光电"}, "消费电子"),
        ({"name": "香农芯创", "top_keywords": "存储芯片、电子化学品"}, "半导体链"),
        ({"name": "永贵电器", "top_keywords": "汽车零部件、智能驾驶"}, "汽车链"),
        (
            {"name": "中国船舶", "industry": "铁路、船舶、航空航天和其他运输设备制造业"},
            "军工航天",
        ),
        ({"name": "亿联网络", "industry": "计算机、通信和其他电子设备制造业"}, "通信设备"),
    ]

    for data, expected in rows:
        assert classify_theme_cluster(pd.Series(data)) == expected


def test_candidate_reason_lines_show_empty_fields_as_none() -> None:
    row = pd.Series(
        {
            "symbol": "600060",
            "name": "海信视像",
            "research_tier": "A",
            "research_score": 68.89,
            "theme_cluster": "消费",
            "stage": "near_breakout",
            "matched_theme": float("nan"),
            "latest_core_news": float("nan"),
            "latest_report": "2026Q1收入业绩稳健增长",
            "core_news_count": 0,
            "research_report_count": 1,
            "co_rise_count": 1,
            "total_penalty": 0,
        }
    )

    text = "\n".join(_candidate_reason_lines(row))

    assert "nan" not in text
    assert "核心新闻：无" in text
