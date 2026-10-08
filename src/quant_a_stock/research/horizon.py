from __future__ import annotations

from dataclasses import dataclass


HORIZON_POLICY_VERSION = "horizon_policy_v2026_08_02_tier_specific"


@dataclass(frozen=True)
class TierHorizonPolicy:
    execution_horizon: str
    research_horizon: str
    primary_horizon_days: int
    tracking_window_days: int
    min_hold_days: int
    max_hold_days: int
    revalidation_interval_days: int
    deep_research_eligible: bool = False


TIER_HORIZON_POLICIES = {
    "A1": TierHorizonPolicy(
        execution_horizon="10-20d",
        research_horizon="10-60d",
        primary_horizon_days=20,
        tracking_window_days=60,
        min_hold_days=3,
        max_hold_days=20,
        revalidation_interval_days=5,
        deep_research_eligible=True,
    ),
    "A2": TierHorizonPolicy(
        execution_horizon="1-5d",
        research_horizon="1-10d",
        primary_horizon_days=5,
        tracking_window_days=10,
        min_hold_days=1,
        max_hold_days=5,
        revalidation_interval_days=1,
    ),
    "A3": TierHorizonPolicy(
        execution_horizon="1-3d",
        research_horizon="1-5d",
        primary_horizon_days=3,
        tracking_window_days=5,
        min_hold_days=1,
        max_hold_days=3,
        revalidation_interval_days=1,
    ),
    "B2": TierHorizonPolicy(
        execution_horizon="1-3d",
        research_horizon="1-5d",
        primary_horizon_days=3,
        tracking_window_days=5,
        min_hold_days=0,
        max_hold_days=0,
        revalidation_interval_days=1,
    ),
    "B1": TierHorizonPolicy(
        execution_horizon="0d",
        research_horizon="0d",
        primary_horizon_days=0,
        tracking_window_days=0,
        min_hold_days=0,
        max_hold_days=0,
        revalidation_interval_days=0,
    ),
}

DEFAULT_HORIZON_POLICY = TierHorizonPolicy(
    execution_horizon="3-5d",
    research_horizon="3-10d",
    primary_horizon_days=5,
    tracking_window_days=10,
    min_hold_days=1,
    max_hold_days=5,
    revalidation_interval_days=1,
)


def resolve_tier(action_bucket: object = "", tier: object = "") -> str:
    tier_text = str(tier or "").strip().upper()
    if tier_text in TIER_HORIZON_POLICIES:
        return tier_text
    bucket = str(action_bucket or "").strip().upper()
    for candidate in ("A1", "A2", "A3", "B2", "B1"):
        if candidate in bucket:
            return candidate
    return tier_text


def horizon_policy(action_bucket: object = "", tier: object = "") -> TierHorizonPolicy:
    return TIER_HORIZON_POLICIES.get(resolve_tier(action_bucket, tier), DEFAULT_HORIZON_POLICY)
