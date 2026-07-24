from __future__ import annotations

import pandas as pd

from quant_a_stock.research.fundamental_quality import build_fundamental_quality_row
from quant_a_stock.research.fundamental_quality import build_research_queue


def _indicator_rows(*, weak: bool = False) -> pd.DataFrame:
    rows = []
    for year, notice_year in [(2025, 2026), (2024, 2025), (2023, 2024)]:
        rows.append(
            {
                "REPORT_DATE": f"{year}-12-31",
                "NOTICE_DATE": f"{notice_year}-04-30",
                "REPORT_TYPE": "年报",
                "ROEJQ": 3.0 if weak else 16.0,
                "XSMLL": 20.0 if weak else 55.0,
                "NCO_NETPROFIT": 0.1 if weak else 1.25,
                "ZCFZL": 88.0 if weak else 58.0,
                "TOTALOPERATEREVETZ": -5.0 if weak else 5.0,
                "PARENTNETPROFITTZ": -60.0 if weak else 8.0,
                "EPSJB": 1.4,
                "BPS": 9.0,
            }
        )
    rows.append(
        {
            "REPORT_DATE": "2026-03-31",
            "NOTICE_DATE": "2026-04-30",
            "REPORT_TYPE": "一季报",
            "ZCFZL": 57.0,
            "TOTALOPERATEREVETZ": 6.0,
            "PARENTNETPROFITTZ": 20.0,
        }
    )
    rows.append(
        {
            "REPORT_DATE": "2026-06-30",
            "NOTICE_DATE": "2026-08-30",
            "REPORT_TYPE": "中报",
            "ZCFZL": 40.0,
            "TOTALOPERATEREVETZ": 99.0,
            "PARENTNETPROFITTZ": 99.0,
        }
    )
    return pd.DataFrame(rows)


def test_quality_screen_is_point_in_time_and_passes_good_cash_business() -> None:
    result = build_fundamental_quality_row(
        _indicator_rows(),
        symbol="600900",
        name="长江电力",
        target_date="2026-07-23",
        close=28.94,
    )

    assert result["latest_report_date"] == "2026-03-31"
    assert result["recent_profit_growth"] == 20.0
    assert result["annual_count"] == 3
    assert result["quality_verdict"] == "pass"
    assert result["quality_score"] >= 70
    assert result["pe"] == round(28.94 / 1.4, 4)


def test_quality_screen_rejects_weak_profit_cash_and_balance_sheet() -> None:
    result = build_fundamental_quality_row(
        _indicator_rows(weak=True),
        symbol="000001",
        name="普通制造",
        target_date="2026-07-23",
        close=10.0,
    )

    assert result["quality_verdict"] == "reject"
    assert bool(result["hard_reject"]) is True
    assert "三年ROE低于6%" in result["hard_reject_reasons"]
    assert "ROE过低" in result["risk_tags"]
    assert "现金利润严重偏弱" in result["risk_tags"]


def test_bank_uses_specialized_financial_metrics() -> None:
    indicators = _indicator_rows()
    indicators.loc[indicators.index[-2], "NONPERLOAN"] = 0.9
    indicators.loc[indicators.index[-2], "BLDKBBL"] = 300.0
    indicators.loc[indicators.index[-2], "NEWCAPITALADER"] = 12.0
    result = build_fundamental_quality_row(
        indicators,
        symbol="600919",
        name="江苏银行",
        target_date="2026-07-23",
        industry="货币金融服务",
        close=12.0,
    )

    assert result["quality_model"] == "bank"
    assert result["quality_verdict"] == "pass"
    assert bool(result["specialized_model"]) is False


def test_semiconductor_model_does_not_hard_reject_growth_cash_lag_alone() -> None:
    indicators = _indicator_rows()
    annual_mask = indicators["REPORT_TYPE"].eq("年报")
    indicators.loc[annual_mask, "NCO_NETPROFIT"] = 0.2
    indicators.loc[annual_mask, "ROEJQ"] = 18.0
    indicators.loc[annual_mask, "XSMLL"] = 50.0
    indicators.loc[annual_mask, "TOTALOPERATEREVETZ"] = 30.0
    result = build_fundamental_quality_row(
        indicators,
        symbol="002371",
        name="半导体样本",
        target_date="2026-07-23",
        industry="半导体制造",
        close=100.0,
    )

    assert result["quality_model"] == "semiconductor"
    assert result["quality_verdict"] in {"pass", "watch"}
    assert bool(result["hard_reject"]) is False


def test_semiconductor_model_uses_theme_without_misclassifying_all_equipment() -> None:
    indicators = _indicator_rows()
    themed = build_fundamental_quality_row(
        indicators,
        symbol="002371",
        name="北方华创",
        target_date="2026-07-23",
        industry="专用设备制造业",
        theme_hint="半导体链",
    )
    generic = build_fundamental_quality_row(
        indicators,
        symbol="000001",
        name="普通设备",
        target_date="2026-07-23",
        industry="专用设备制造业",
    )

    assert themed["quality_model"] == "semiconductor"
    assert generic["quality_model"] == "generic"


def test_research_queue_excludes_rejects_and_prefers_pass() -> None:
    watchlist = pd.DataFrame(
        [
            {
                "symbol": "600900",
                "name": "长江电力",
                "research_priority": "high",
                "research_score": 75,
                "risk_tags": "",
            },
            {
                "symbol": "600886",
                "name": "国投电力",
                "research_priority": "high",
                "research_score": 65,
                "risk_tags": "",
            },
            {
                "symbol": "300001",
                "name": "低质样本",
                "research_priority": "high",
                "research_score": 80,
                "risk_tags": "",
            },
        ]
    )
    quality = pd.DataFrame(
        [
            {"symbol": "600900", "name": "长江电力", "quality_verdict": "pass", "quality_score": 85},
            {"symbol": "600886", "name": "国投电力", "quality_verdict": "watch", "quality_score": 65},
            {"symbol": "300001", "name": "低质样本", "quality_verdict": "reject", "quality_score": 30},
        ]
    )

    result = build_research_queue(watchlist, quality, top=5)

    assert result["symbol"].tolist() == ["600900", "600886"]
    assert result.iloc[0]["fundamental_research_rank_score"] > result.iloc[1]["fundamental_research_rank_score"]


def test_research_queue_penalizes_expensive_quality_without_rejecting_it() -> None:
    watchlist = pd.DataFrame(
        [
            {
                "symbol": "300502",
                "name": "成长公司",
                "research_priority": "medium",
                "research_score": 75,
                "risk_tags": "",
            },
            {
                "symbol": "600642",
                "name": "稳健公司",
                "research_priority": "low",
                "research_score": 60,
                "risk_tags": "",
            },
        ]
    )
    quality = pd.DataFrame(
        [
            {
                "symbol": "300502",
                "name": "成长公司",
                "quality_verdict": "pass",
                "quality_score": 90,
                "risk_tags": "市盈率偏高；市净率偏高",
            },
            {
                "symbol": "600642",
                "name": "稳健公司",
                "quality_verdict": "pass",
                "quality_score": 85,
                "risk_tags": "",
            },
        ]
    )

    result = build_research_queue(watchlist, quality, top=2)

    assert result["symbol"].tolist() == ["600642", "300502"]
    assert set(result["quality_verdict"]) == {"pass"}
