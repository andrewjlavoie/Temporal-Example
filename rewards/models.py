"""Data models for the rewards program entity workflow."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class RewardTier(StrEnum):
    BASIC = "BASIC"  # 0+ points
    GOLD = "GOLD"  # 500+ points
    PLATINUM = "PLATINUM"  # 1000+ points


# Tier thresholds — centralized for easy modification
TIER_THRESHOLDS = {
    RewardTier.BASIC: 0,
    RewardTier.GOLD: 500,
    RewardTier.PLATINUM: 1000,
}


class EventType(StrEnum):
    ENROLLED = "ENROLLED"
    POINTS_EARNED = "POINTS_EARNED"
    POINTS_REDEEMED = "POINTS_REDEEMED"
    TIER_UPGRADED = "TIER_UPGRADED"
    TIER_DOWNGRADED = "TIER_DOWNGRADED"
    LEFT_PROGRAM = "LEFT_PROGRAM"


@dataclass
class RewardEvent:
    """A single event in the customer's reward history."""

    event_type: EventType
    description: str
    points_change: int = 0
    points_after: int = 0
    tier_after: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class MembershipState:
    """The complete state of a customer's reward membership for Temporal Queries."""

    customer_id: str
    customer_name: str
    points: int = 0
    tier: str = RewardTier.BASIC.value
    is_active: bool = True
    member_since: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    history: list[RewardEvent] = field(default_factory=list)
    total_points_earned: int = 0
    total_points_redeemed: int = 0
    event_count: int = 0  # Tracks events for Continue-As-New threshold


@dataclass
class AddPointsSignal:
    """Signal payload: customer earned points from an activity."""

    points: int
    source: str  # e.g., "purchase", "review", "referral"
    description: str = ""


@dataclass
class RedeemPointsSignal:
    """Signal payload: customer wants to redeem points."""

    points: int
    reward_description: str  # e.g., "10% off coupon", "free shipping"


@dataclass
class EnrollmentInput:
    """Input for starting a new rewards membership workflow."""

    customer_id: str
    customer_name: str
    initial_points: int = 0  # Welcome bonus
    # Carries full state across Continue-As-New; None on first enrollment
    restored_state: MembershipState | None = None


def evaluate_tier(points: int) -> RewardTier:
    """Determine the correct tier based on current points.

    Tiers are evaluated in descending order: if you have 1000+ points,
    you're Platinum regardless of how you got there.
    """
    if points >= TIER_THRESHOLDS[RewardTier.PLATINUM]:
        return RewardTier.PLATINUM
    elif points >= TIER_THRESHOLDS[RewardTier.GOLD]:
        return RewardTier.GOLD
    else:
        return RewardTier.BASIC
