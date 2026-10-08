from __future__ import annotations

from quant_a_stock.data.akshare_client import (
    _candidate_asset_types,
    _normalize_adjust,
    _parse_tencent_etf_rows,
    _parse_tencent_stock_rows,
    _sina_etf_symbol,
    _sina_stock_symbol,
)


def test_auto_asset_type_routes_etf_codes_to_etf_endpoint() -> None:
    assert _candidate_asset_types("510300", "auto") == ["etf"]
    assert _candidate_asset_types("159915", "auto") == ["etf"]


def test_auto_asset_type_routes_stock_codes_to_stock_endpoint() -> None:
    assert _candidate_asset_types("600519", "auto") == ["stock"]
    assert _candidate_asset_types("000001", "auto") == ["stock"]


def test_normalize_adjust_accepts_none_aliases() -> None:
    assert _normalize_adjust("qfq") == "qfq"
    assert _normalize_adjust("none") == ""
    assert _normalize_adjust("UNADJUSTED") == ""


def test_sina_etf_symbol_adds_market_prefix() -> None:
    assert _sina_etf_symbol("510300") == "sh510300"
    assert _sina_etf_symbol("159915") == "sz159915"


def test_sina_stock_symbol_adds_market_prefix() -> None:
    assert _sina_stock_symbol("688146") == "sh688146"
    assert _sina_stock_symbol("600519") == "sh600519"
    assert _sina_stock_symbol("300750") == "sz300750"
    assert _sina_stock_symbol("000001") == "sz000001"


def test_parse_tencent_etf_rows_restores_base_units() -> None:
    frame = _parse_tencent_etf_rows(
        [
            [
                "2026-07-28",
                "3.513",
                "3.355",
                "3.538",
                "3.335",
                "37337710.00",
                {},
                "22.00",
                "1279302.48",
            ]
        ]
    )

    assert frame.loc[0, "timestamp"] == "2026-07-28"
    assert frame.loc[0, "volume"] == 3_733_771_000
    assert frame.loc[0, "amount"] == 12_793_024_800


def test_parse_tencent_stock_rows_restores_share_volume() -> None:
    frame = _parse_tencent_stock_rows(
        [
            [
                "2026-07-28",
                "39.63",
                "39.92",
                "40.59",
                "39.10",
                "115228.00",
                {},
                "2.76",
                "46113.36",
            ]
        ]
    )

    assert frame.loc[0, "volume"] == 11_522_800
    assert frame.loc[0, "amount"] == 461_133_600
