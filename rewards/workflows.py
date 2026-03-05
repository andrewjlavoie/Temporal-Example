"""Rewards Program Workflow — Long-Running Entity Pattern.

This workflow represents a single customer's reward membership as a Temporal
Workflow Entity.
It runs for the entire lifetime of the membership (days, months, years)
and responds to external events via Signals and returns info via Queries.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rewards.activities import (
        apply_reward_redemption,
        process_offboarding,
        send_tier_change_notification,
        send_welcome_email,
    )
    from rewards.models import (
        AddPointsSignal,
        EnrollmentInput,
        EventType,
        MembershipState,
        RedeemPointsSignal,
        RewardEvent,
        RewardTier,
        evaluate_tier,
    )


# After this many signal events, perform Continue-As-New to
# prevent unbounded event history growth
CONTINUE_AS_NEW_THRESHOLD = 1000


@workflow.defn
class RewardsWorkflow:
    """A long-running entity workflow representing a customer's reward membership.

    The workflow sits in a loop:
    - Signals modify the internal state.
    - Queries can read the state at any time.
    - The workflow only completes when the customer leaves the program.
    """

    def __init__(self) -> None:
        self._state: MembershipState | None = None
        self._pending_points: list[AddPointsSignal] = []
        self._pending_redemptions: list[RedeemPointsSignal] = []
        self._should_leave = False

    # Signals

    @workflow.signal
    async def add_points(self, signal: AddPointsSignal) -> None:
        """Signal: Customer earned points from an activity.

        Points are queued and processed in the main loop. This ensures
        that state transitions and tier evaluations happen sequentially,
        avoiding race conditions from concurrent signals.
        """
        self._pending_points.append(signal)

    @workflow.signal
    async def redeem_points(self, signal: RedeemPointsSignal) -> None:
        """Signal: Customer wants to redeem points for a reward."""
        self._pending_redemptions.append(signal)

    @workflow.signal
    async def leave_program(self) -> None:
        """Signal: Customer wants to leave the rewards program."""
        self._should_leave = True

    # Queries

    @workflow.query
    def get_status(self) -> MembershipState | None:
        """Query: Returns the full membership state.

        This is the primary read path. Any client — a web UI, a support
        tool, an API — can query this to get the customer's current points,
        tier, history, etc. without affecting the workflow.
        """
        return self._state

    @workflow.query
    def get_level(self) -> str:
        """Query: Returns just the current reward tier.

        A lightweight query for systems that only need the tier level
        (e.g., to display a badge in the customer's profile).
        """
        return self._state.tier if self._state else RewardTier.BASIC.value

    # Main Workflow Logic

    @workflow.run
    async def run(self, input: EnrollmentInput) -> MembershipState:
        """Main workflow execution.

        The workflow initializes state (or restores it after Continue-As-New),
        then enters an event loop that processes signals until the customer
        leaves the program.
        """

        # Initialize or restore state
        if input.restored_state is not None:
            # Continue-As-New: restore the carried-over state
            self._state = input.restored_state
        else:
            # First enrollment: create fresh state
            self._state = MembershipState(
                customer_id=input.customer_id,
                customer_name=input.customer_name,
                points=input.initial_points,
                tier=evaluate_tier(input.initial_points).value,
            )
            self._record_event(
                EventType.ENROLLED,
                f"Welcome to the rewards program, {input.customer_name}!",
                points_change=input.initial_points,
            )

            # Send welcome email (activity with side effects)
            await workflow.execute_activity(
                send_welcome_email,
                args=[input.customer_id, input.customer_name],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        assert self._state is not None

        workflow.logger.info(
            f"Rewards workflow active for {input.customer_name} "
            f"({input.customer_id}): {self._state.points} pts, "
            f"tier={self._state.tier}"
        )

        # ── Event Loop─
        # The workflow exists here, waiting for signals
        while not self._should_leave:
            # Wait until a signal arrives (zero compute while parked)
            await workflow.wait_condition(
                lambda: (
                    len(self._pending_points) > 0
                    or len(self._pending_redemptions) > 0
                    or self._should_leave
                ),
            )

            # Process all pending point additions
            while self._pending_points:
                signal = self._pending_points.pop(0)
                await self._process_add_points(signal)

            # Process all pending redemptions
            while self._pending_redemptions:
                signal = self._pending_redemptions.pop(0)
                await self._process_redemption(signal)

            # Check if we should Continue-As-New
            if self._state.event_count >= CONTINUE_AS_NEW_THRESHOLD:
                workflow.logger.info(
                    f"Event count ({self._state.event_count}) reached threshold. "
                    f"Performing Continue-As-New to reset history."
                )
                # Trim history and reset event count before carrying over
                self._state.history = []
                self._state.event_count = 0
                workflow.continue_as_new(
                    EnrollmentInput(
                        customer_id=self._state.customer_id,
                        customer_name=self._state.customer_name,
                        initial_points=input.initial_points,
                        restored_state=self._state,
                    )
                )

        # Customer is leaving the program
        workflow.logger.info(f"Processing departure for {self._state.customer_name}")

        self._record_event(
            EventType.LEFT_PROGRAM,
            f"Customer left the program. Final balance: {self._state.points} pts.",
        )

        # Run offboarding activities
        await workflow.execute_activity(
            process_offboarding,
            args=[
                self._state.customer_id,
                self._state.customer_name,
                self._state.points,
            ],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

        self._state.is_active = False
        workflow.logger.info(
            f"Rewards workflow completed for {self._state.customer_name}. "
            f"Total earned: {self._state.total_points_earned}, "
            f"Total redeemed: {self._state.total_points_redeemed}"
        )

        return self._state

    # Internal Processing Methods

    async def _process_add_points(self, signal: AddPointsSignal) -> None:
        """Process a point addition: update balance, evaluate tier, notify."""
        assert self._state is not None
        old_tier = self._state.tier
        self._state.points += signal.points
        self._state.total_points_earned += signal.points
        new_tier = evaluate_tier(self._state.points)

        source_desc = f" ({signal.source})" if signal.source else ""
        description = signal.description or f"Earned {signal.points} points{source_desc}"

        self._record_event(
            EventType.POINTS_EARNED,
            description,
            points_change=signal.points,
        )

        workflow.logger.info(
            f"{self._state.customer_name}: +{signal.points} pts "
            f"({self._state.points} total, tier: {new_tier.value})"
        )

        # Check for tier change
        if new_tier.value != old_tier:
            event_type = (
                EventType.TIER_UPGRADED
                if _tier_rank(new_tier.value) > _tier_rank(old_tier)
                else EventType.TIER_DOWNGRADED
            )
            self._state.tier = new_tier.value
            self._record_event(
                event_type,
                f"Tier changed: {old_tier} → {new_tier.value}",
            )

            # Send tier change notification (activity)
            await workflow.execute_activity(
                send_tier_change_notification,
                args=[
                    self._state.customer_id,
                    self._state.customer_name,
                    old_tier,
                    new_tier.value,
                ],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

    async def _process_redemption(self, signal: RedeemPointsSignal) -> None:
        """Process a point redemption: validate, deduct, apply reward."""
        assert self._state is not None
        if signal.points > self._state.points:
            workflow.logger.warning(
                f"Redemption rejected for {self._state.customer_name}: "
                f"requested {signal.points} pts but only has {self._state.points}"
            )
            self._record_event(
                EventType.POINTS_REDEEMED,
                f"Redemption REJECTED: insufficient points "
                f"(requested {signal.points}, available {self._state.points})",
                points_change=0,
            )
            return

        old_tier = self._state.tier
        self._state.points -= signal.points
        self._state.total_points_redeemed += signal.points
        new_tier = evaluate_tier(self._state.points)

        self._record_event(
            EventType.POINTS_REDEEMED,
            f"Redeemed {signal.points} pts for: {signal.reward_description}",
            points_change=-signal.points,
        )

        # Apply the redemption in the external fulfillment system
        await workflow.execute_activity(
            apply_reward_redemption,
            args=[
                self._state.customer_id,
                signal.points,
                signal.reward_description,
            ],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

        # Check for tier downgrade after redemption
        if new_tier.value != old_tier:
            self._state.tier = new_tier.value
            self._record_event(
                EventType.TIER_DOWNGRADED,
                f"Tier changed after redemption: {old_tier} → {new_tier.value}",
            )
            await workflow.execute_activity(
                send_tier_change_notification,
                args=[
                    self._state.customer_id,
                    self._state.customer_name,
                    old_tier,
                    new_tier.value,
                ],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        workflow.logger.info(
            f"{self._state.customer_name}: -{signal.points} pts "
            f"for '{signal.reward_description}' "
            f"({self._state.points} remaining, tier: {self._state.tier})"
        )

    def _record_event(
        self,
        event_type: EventType,
        description: str,
        points_change: int = 0,
    ) -> None:
        """Record an event in the membership history."""
        assert self._state is not None
        event = RewardEvent(
            event_type=event_type,
            description=description,
            points_change=points_change,
            points_after=self._state.points,
            tier_after=self._state.tier,
        )
        self._state.history.append(event)
        self._state.event_count += 1


def _tier_rank(tier: str) -> int:
    """Helper to compare tier levels numerically."""
    ranks = {
        RewardTier.BASIC.value: 0,
        RewardTier.GOLD.value: 1,
        RewardTier.PLATINUM.value: 2,
    }
    return ranks.get(tier, 0)
