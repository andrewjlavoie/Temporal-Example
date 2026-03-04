"""E2E tests for Temporal demo workflows.

Uses temporalio.testing.WorkflowEnvironment to spin up an in-process
Temporal server — no external `temporal server start-dev` needed.

Run with: uv run pytest tests/test_e2e.py -vv -s
"""

import asyncio
import uuid

import pytest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from ecommerce.activities import (
    cancel_shipment,
    notify_customer,
    process_payment,
    refund_payment,
    release_inventory,
    reserve_inventory,
    ship_package,
)
from ecommerce.models import OrderInput, OrderItem
from ecommerce.workflows import OrderWorkflow
from rewards.activities import (
    apply_reward_redemption,
    process_offboarding,
    send_tier_change_notification,
    send_welcome_email,
)
from rewards.models import AddPointsSignal, EnrollmentInput, RedeemPointsSignal
from rewards.workflows import RewardsWorkflow


@pytest.fixture(scope="session")
async def env():
    async with await WorkflowEnvironment.start_local() as env:
        yield env


@pytest.fixture
def client(env: WorkflowEnvironment) -> Client:
    return env.client


def _sample_order(fail_at_step: str | None = None) -> OrderInput:
    return OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8].upper()}",
        customer_id="customer-1337",
        customer_email="andrewjlavoie@gmail.com",
        items=[
            OrderItem(
                product_id="SKU-LAPTOP-001",
                product_name='15" MacBook Pro, M6 Special AI Edition',
                quantity=1,
                unit_price=3499.00,
            ),
            OrderItem(
                product_id="SKU-CASE-042",
                product_name="Laptop Sleeve, Top Secret",
                quantity=1,
                unit_price=49.99,
            ),
        ],
        shipping_address="123 Main St, Colorado Springs, CO 80919",
        fail_at_step=fail_at_step,
    )


ECOMMERCE_TASK_QUEUE = "ecommerce-order-queue"
REWARDS_TASK_QUEUE = "rewards-program-queue"

ECOMMERCE_ACTIVITIES = [
    process_payment,
    reserve_inventory,
    ship_package,
    notify_customer,
    refund_payment,
    release_inventory,
    cancel_shipment,
]

REWARDS_ACTIVITIES = [
    send_welcome_email,
    send_tier_change_notification,
    process_offboarding,
    apply_reward_redemption,
]


# ── Ecommerce Saga Tests ─────────────────────────────────────────


async def test_ecommerce_happy_path(client: Client):
    order = _sample_order()
    task_queue = f"{ECOMMERCE_TASK_QUEUE}-{uuid.uuid4().hex[:8]}"
    workflow_id = f"order-{order.order_id}"

    print(f"\n{'=' * 60}")
    print("  E-Commerce Saga — Happy Path")
    print(f"{'=' * 60}")
    print(f"  Order ID:    {order.order_id}")
    print(f"  Workflow ID: {workflow_id}")
    print(f"  Customer:    {order.customer_email}")
    print(f"  Items:       {len(order.items)}")
    for item in order.items:
        print(f"    - {item.quantity}x {item.product_name} (${item.unit_price:.2f})")
    print(f"  Total:       ${order.total_amount:.2f}")
    print(f"  Ship to:     {order.shipping_address}")
    print()

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[OrderWorkflow],
        activities=ECOMMERCE_ACTIVITIES,
    ):
        print("  Starting workflow...")
        handle = await client.start_workflow(
            OrderWorkflow.run,
            order,
            id=workflow_id,
            task_queue=task_queue,
        )
        print(f"  Workflow started: {handle.id}")
        print("  Waiting for result...")

        result = await handle.result()

        print(f"\n  --- Result ---")
        print(f"  Status:          {result['status']}")
        print(f"  Transaction ID:  {result['payment_transaction_id']}")
        print(f"  Tracking Number: {result['tracking_number']}")
        print(f"  Est. Delivery:   {result['estimated_delivery']}")

        status = await handle.query(OrderWorkflow.get_status)
        print(f"\n  --- Query: get_status ---")
        print(f"  Order Status:    {status}")
        print(f"{'=' * 60}\n")

        assert result["status"] == "completed"
        assert "payment_transaction_id" in result
        assert "tracking_number" in result
        assert status == "COMPLETED"


async def test_ecommerce_compensation(client: Client):
    order = _sample_order(fail_at_step="shipping")
    task_queue = f"{ECOMMERCE_TASK_QUEUE}-{uuid.uuid4().hex[:8]}"
    workflow_id = f"order-{order.order_id}"

    print(f"\n{'=' * 60}")
    print("  E-Commerce Saga — Compensation (failure at shipping)")
    print(f"{'=' * 60}")
    print(f"  Order ID:      {order.order_id}")
    print(f"  Workflow ID:   {workflow_id}")
    print(f"  Customer:      {order.customer_email}")
    print(f"  Total:         ${order.total_amount:.2f}")
    print(f"  Fail at step:  {order.fail_at_step}")
    print()
    print("  Expected flow:")
    print("    1. Payment     -> succeeds")
    print("    2. Inventory   -> succeeds")
    print("    3. Shipping    -> FAILS")
    print("    4. Compensate: release inventory")
    print("    5. Compensate: refund payment")
    print()

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[OrderWorkflow],
        activities=ECOMMERCE_ACTIVITIES,
    ):
        print("  Starting workflow...")
        handle = await client.start_workflow(
            OrderWorkflow.run,
            order,
            id=workflow_id,
            task_queue=task_queue,
        )
        print(f"  Workflow started: {handle.id}")
        print("  Waiting for result (expecting compensation)...")

        result = await handle.result()

        print(f"\n  --- Result ---")
        print(f"  Status:         {result['status']}")
        print(f"  Failure Reason: {result['failure_reason']}")

        status = await handle.query(OrderWorkflow.get_status)
        print(f"\n  --- Query: get_status ---")
        print(f"  Order Status:   {status}")
        print("  All compensations executed successfully.")
        print(f"{'=' * 60}\n")

        assert result["status"] == "compensated"
        assert "failure_reason" in result
        assert status == "COMPENSATED"


# ── Rewards Entity Test ──────────────────────────────────────────


async def test_rewards_lifecycle(client: Client):
    enrollment = EnrollmentInput(
        customer_id="demo-customer-001",
        customer_name="Alex Johnson",
        initial_points=100,
    )
    task_queue = f"{REWARDS_TASK_QUEUE}-{uuid.uuid4().hex[:8]}"
    workflow_id = f"rewards-{uuid.uuid4().hex[:8]}"

    print(f"\n{'=' * 60}")
    print("  Rewards Program — Full Lifecycle")
    print(f"{'=' * 60}")
    print(f"  Customer:      {enrollment.customer_name}")
    print(f"  Customer ID:   {enrollment.customer_id}")
    print(f"  Workflow ID:   {workflow_id}")
    print(f"  Welcome bonus: {enrollment.initial_points} pts")
    print()

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[RewardsWorkflow],
        activities=REWARDS_ACTIVITIES,
    ):
        print("  Enrolling customer...")
        handle = await client.start_workflow(
            RewardsWorkflow.run,
            enrollment,
            id=workflow_id,
            task_queue=task_queue,
        )
        print(f"  Workflow started: {handle.id}")

        # ── Earn points toward Gold ──
        print(f"\n  --- Earning Points (Signals) ---")
        point_events = [
            (200, "purchase", "Holiday shopping spree", 300, "BASIC"),
            (150, "purchase", "Electronics order", 450, "BASIC"),
            (50, "review", "Product review bonus", 500, "GOLD"),
        ]

        for pts, source, desc, expected_pts, expected_tier in point_events:
            await handle.signal(
                RewardsWorkflow.add_points,
                AddPointsSignal(points=pts, source=source, description=desc),
            )
            ep, et = expected_pts, expected_tier
            await _poll_until(
                lambda ep=ep, et=et: _check_state(handle, ep, et)
            )
            state = await handle.query(RewardsWorkflow.get_status)
            print(f"    +{pts:>4} pts ({source:>10}): {desc}")
            print(f"         -> {state.points} pts total, tier: {state.tier}")

        # Verify GOLD
        state = await handle.query(RewardsWorkflow.get_status)
        print(f"\n  --- Query: get_status ---")
        print(f"  Points:    {state.points}")
        print(f"  Tier:      {state.tier}")
        print(f"  Earned:    {state.total_points_earned} (lifetime)")
        print(f"  Events:    {state.event_count}")
        assert state.points == 500
        assert state.tier == "GOLD"

        level = await handle.query(RewardsWorkflow.get_level)
        print(f"\n  --- Query: get_level ---")
        print(f"  Tier: {level}")

        # ── Redeem points ──
        print(f"\n  --- Redemption (Signal) ---")
        await handle.signal(
            RewardsWorkflow.redeem_points,
            RedeemPointsSignal(points=50, reward_description="$5 store credit"),
        )

        async def _redeemed():
            s = await handle.query(RewardsWorkflow.get_status)
            return s.points == 450 and s.tier == "BASIC"

        await _poll_until(_redeemed)

        state = await handle.query(RewardsWorkflow.get_status)
        print(f"  Redeemed 50 pts for '$5 store credit'")
        print(f"    -> {state.points} pts remaining, tier: {state.tier}")
        assert state.points == 450
        assert state.tier == "BASIC"

        # ── Full status dump ──
        print(f"\n  --- Full Status (Query) ---")
        print(f"  Customer:  {state.customer_name}")
        print(f"  Points:    {state.points}")
        print(f"  Tier:      {state.tier}")
        print(f"  Active:    {state.is_active}")
        print(f"  Earned:    {state.total_points_earned} (lifetime)")
        print(f"  Redeemed:  {state.total_points_redeemed} (lifetime)")
        print(f"  Events:    {state.event_count}")
        print(f"  Since:     {state.member_since}")
        if state.history:
            print(f"\n  Recent History (last 5):")
            for event in state.history[-5:]:
                sign = "+" if event.points_change > 0 else ""
                pts_str = (
                    f" ({sign}{event.points_change} pts)"
                    if event.points_change != 0
                    else ""
                )
                print(f"    [{event.event_type}]{pts_str} {event.description}")

        # ── Leave program ──
        print(f"\n  --- Leaving Program (Signal) ---")
        await handle.signal(RewardsWorkflow.leave_program)
        print("  Signal sent: leaving program...")
        print("  Waiting for workflow to complete...")
        result = await handle.result()
        print(f"  Membership ended.")
        print(f"  Final points:      {result.points}")
        print(f"  Lifetime earned:   {result.total_points_earned}")
        print(f"  Lifetime redeemed: {result.total_points_redeemed}")
        print(f"  Active:            {result.is_active}")
        print(f"{'=' * 60}\n")

        assert result.is_active is False


async def _check_state(handle, expected_pts: int, expected_tier: str) -> bool:
    s = await handle.query(RewardsWorkflow.get_status)
    return s.points == expected_pts and s.tier == expected_tier


async def _poll_until(condition, *, timeout: float = 10.0, interval: float = 0.2):
    """Poll an async condition until it returns True or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await condition():
            return
        await asyncio.sleep(interval)
    raise TimeoutError("Condition not met within timeout")
