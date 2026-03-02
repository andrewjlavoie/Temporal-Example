"""Activities for the rewards program workflow.
Each activity is an interaction with the customer during the membership lifecycle.
"""

import asyncio

from temporalio import activity

from .models import RewardTier


@activity.defn
async def send_welcome_email(customer_id: str, customer_name: str) -> str:
    """Send welcome email to a new rewards member."""
    activity.logger.info(f"Sending welcome email to {customer_name} ({customer_id})")
    await asyncio.sleep(0.3)
    return f"Welcome email sent to {customer_name}"


@activity.defn
async def send_tier_change_notification(
    customer_id: str,
    customer_name: str,
    old_tier: str,
    new_tier: str,
) -> str:
    """Notify customer of a tier change (upgrade or downgrade)."""
    direction = "upgraded" if _tier_rank(new_tier) > _tier_rank(old_tier) else "downgraded"
    activity.logger.info(f"Notifying {customer_name}: {direction} from {old_tier} to {new_tier}")
    await asyncio.sleep(0.3)
    return f"Tier {direction} notification sent: {old_tier} → {new_tier}"


@activity.defn
async def process_offboarding(customer_id: str, customer_name: str, final_points: int) -> str:
    """Process member offboarding: archive data, send farewell, etc."""
    activity.logger.info(
        f"Processing offboarding for {customer_name} ({customer_id}). "
        f"Final points balance: {final_points}"
    )
    await asyncio.sleep(0.5)
    return f"Offboarding complete for {customer_name}. Points forfeited: {final_points}"


@activity.defn
async def apply_reward_redemption(
    customer_id: str,
    points_redeemed: int,
    reward_description: str,
) -> str:
    """Apply a reward redemption in the external rewards fulfillment system."""
    activity.logger.info(
        f"Applying redemption for {customer_id}: {points_redeemed} pts → '{reward_description}'"
    )
    await asyncio.sleep(0.3)
    return f"Redemption applied: {reward_description} ({points_redeemed} pts)"


def _tier_rank(tier: str) -> int:
    """Helper to compare tier levels."""
    ranks = {RewardTier.BASIC.value: 0, RewardTier.GOLD.value: 1, RewardTier.PLATINUM.value: 2}
    return ranks.get(tier, 0)
