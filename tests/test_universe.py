from __future__ import annotations

import pandas as pd

from quant_a_stock.data.universe import filter_universe
from quant_a_stock.data.universe import infer_market
from quant_a_stock.data.universe import normalize_symbol


def test_normalize_symbol_removes_market_prefix() -> None:
    assert normalize_symbol("sh688143") == "688143"
    assert normalize_symbol("SZ300750") == "300750"
    assert normalize_symbol(1) == "000001"


def test_infer_market_for_common_a_share_prefixes() -> None:
    assert infer_market("688143") == "sh"
    assert infer_market("600519") == "sh"
    assert infer_market("300750") == "sz"
    assert infer_market("000001") == "sz"


def test_filter_universe_excludes_st_and_markets() -> None:
    raw = pd.DataFrame(
        {
            "symbol": ["688143", "300750", "830000"],
            "name": ["长盈通", "*ST示例", "北交所示例"],
        }
    )

    result = filter_universe(raw, markets={"sh", "sz"}, exclude_st=True)

    assert result["symbol"].tolist() == ["688143"]
