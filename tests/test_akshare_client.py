from __future__ import annotations

from quant_a_stock.data.akshare_client import (
    _candidate_asset_types,
    _normalize_adjust,
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
