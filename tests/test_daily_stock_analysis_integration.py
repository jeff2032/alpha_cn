from __future__ import annotations

import json
from pathlib import Path

from quant_a_stock.integrations.daily_stock_analysis import build_daily_stock_analysis_handoff


def test_dsa_handoff_only_exports_actionable_low_risk_signals(tmp_path: Path) -> None:
    context = {
        "metadata": {"target_date": "2026-07-10", "plan_date": "2026-07-13"},
        "decision_signal_context": {
            "signals": [
                {
                    "symbol": "000001",
                    "name": "低分主攻",
                    "signal_type": "buy_watch",
                    "research_score": 70,
                    "risk_level": "低",
                },
                {
                    "symbol": "000002",
                    "name": "高分升级",
                    "signal_type": "upgrade_watch",
                    "research_score": 95,
                    "risk_level": "中",
                },
                {
                    "symbol": "000003",
                    "name": "风险回避",
                    "signal_type": "avoid",
                    "research_score": 99,
                    "risk_level": "低",
                },
                {
                    "symbol": "000004",
                    "name": "高风险主攻",
                    "signal_type": "buy_watch",
                    "research_score": 98,
                    "risk_level": "中高",
                },
            ]
        },
    }
    source = tmp_path / "context.json"
    source.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")

    handoff = build_daily_stock_analysis_handoff(
        context_path=source,
        output_root=tmp_path / "dsa",
        top=8,
    )

    assert handoff.symbols == ["000001", "000002"]
    assert handoff.output_path.exists()
    saved = json.loads(handoff.output_path.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "alpha_cn_to_dsa_v1"
    assert saved["target_date"] == "2026-07-10"
    assert saved["plan_date"] == "2026-07-13"


def test_dsa_handoff_respects_top_and_deduplicates(tmp_path: Path) -> None:
    signals = [
        {
            "symbol": "600001",
            "name": "样本",
            "signal_type": "buy_watch",
            "research_score": score,
            "risk_level": "低",
        }
        for score in (90, 80)
    ]
    signals.append(
        {
            "symbol": "600002",
            "name": "样本二",
            "signal_type": "buy_watch",
            "research_score": 70,
            "risk_level": "低",
        }
    )
    source = tmp_path / "context.json"
    source.write_text(
        json.dumps(
            {
                "metadata": {"target_date": "2026-07-10", "plan_date": "2026-07-13"},
                "decision_signal_context": {"signals": signals},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    handoff = build_daily_stock_analysis_handoff(
        context_path=source,
        output_root=tmp_path / "dsa",
        top=1,
    )

    assert handoff.symbols == ["600001"]
