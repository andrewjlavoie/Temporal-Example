"""Rewards Program Starter — interactive client demonstrating Signals and Queries.

This client enrolls a customer in the rewards program and then provides an
interactive menu to send Signals (add points, redeem, leave) and Queries
(check status, check level) to the running workflow.

Usage:
    uv run python rewards/starter.py                        # Interactive mode
    uv run python rewards/starter.py --scenario quick-demo   # Automated demo scenario
"""

import argparse
import asyncio

from temporalio.client import Client

from rewards.models import AddPointsSignal, EnrollmentInput, RedeemPointsSignal
from rewards.worker import TASK_QUEUE
from rewards.workflows import RewardsWorkflow


async def run_interactive(client: Client, customer_id: str = "customer-42"):
    """Interactive mode: menu-driven Signal/Query interface."""
    input_data = EnrollmentInput(
        customer_id=customer_id,
        customer_name="Maria Garcia",
        initial_points=100,  # Welcome bonus
    )

    workflow_id = f"rewards-customer-{customer_id}"

    # Start the workflow (or get handle to existing one)
    handle = await client.start_workflow(
        RewardsWorkflow.run,
        input_data,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    print(f"\n{'=' * 60}")
    print("  Rewards Program — Interactive Demo")
    print(f"  Customer:    {input_data.customer_name}")
    print(f"  Workflow ID: {workflow_id}")
    print(f"  Welcome bonus: {input_data.initial_points} pts")
    print(f"  View in UI: http://localhost:8233/namespaces/default/workflows/{workflow_id}")
    print(f"{'=' * 60}\n")

    while True:
        print("\n--- Actions ---")
        print("  1. Earn points (Signal: add_points)")
        print("  2. Redeem points (Signal: redeem_points)")
        print("  3. Check status (Query: get_status)")
        print("  4. Check level (Query: get_level)")
        print("  5. Leave program (Signal: leave_program)")
        print("  6. Exit client (workflow keeps running)")

        choice = input("\nChoice [1-6]: ").strip()

        try:
            if choice == "1":
                pts = int(input("  Points to add: "))
                source = input("  Source (purchase/review/referral): ") or "purchase"
                await handle.signal(
                    RewardsWorkflow.add_points,
                    AddPointsSignal(points=pts, source=source),
                )
                print(f"  ✅ Signal sent: +{pts} pts from {source}")

                # Brief pause then show updated status
                await asyncio.sleep(1)
                status = await handle.query(RewardsWorkflow.get_status)
                assert status is not None
                print(f"  📊 Points: {status.points} | Tier: {status.tier}")

            elif choice == "2":
                pts = int(input("  Points to redeem: "))
                reward = input("  Reward description: ") or "store credit"
                await handle.signal(
                    RewardsWorkflow.redeem_points,
                    RedeemPointsSignal(points=pts, reward_description=reward),
                )
                print(f"  ✅ Signal sent: redeem {pts} pts for '{reward}'")

                await asyncio.sleep(1)
                status = await handle.query(RewardsWorkflow.get_status)
                assert status is not None
                print(f"  📊 Points: {status.points} | Tier: {status.tier}")

            elif choice == "3":
                status = await handle.query(RewardsWorkflow.get_status)
                assert status is not None
                print(f"\n  {'─' * 50}")
                print(f"  Customer:  {status.customer_name}")
                print(f"  Points:    {status.points}")
                print(f"  Tier:      {status.tier}")
                print(f"  Active:    {status.is_active}")
                print(f"  Earned:    {status.total_points_earned} (lifetime)")
                print(f"  Redeemed:  {status.total_points_redeemed} (lifetime)")
                print(f"  Events:    {status.event_count}")
                print(f"  Since:     {status.member_since}")
                if status.history:
                    print("\n  Recent History (last 5):")
                    for event in status.history[-5:]:
                        sign = "+" if event.points_change > 0 else ""
                        pts_str = (
                            f" ({sign}{event.points_change} pts)"
                            if event.points_change != 0
                            else ""
                        )
                        print(f"    [{event.event_type}]{pts_str} {event.description}")
                print(f"  {'─' * 50}")

            elif choice == "4":
                level = await handle.query(RewardsWorkflow.get_level)
                print(f"  🏆 Current tier: {level}")

            elif choice == "5":
                confirm = input("  Are you sure? This ends the membership. (y/n): ")
                if confirm.lower() == "y":
                    await handle.signal(RewardsWorkflow.leave_program)
                    print("  ✅ Signal sent: leaving program...")
                    print("  Waiting for workflow to complete...")
                    result = await handle.result()
                    print("\n  Membership ended.")
                    print(f"  Final points: {result.points}")
                    print(f"  Lifetime earned: {result.total_points_earned}")
                    print(f"  Lifetime redeemed: {result.total_points_redeemed}")
                    break

            elif choice == "6":
                print("  Client exiting. Workflow continues running in Temporal.")
                print(f"  Reconnect anytime using workflow ID: {workflow_id}")
                break

            else:
                print("  Invalid choice. Try 1-6.")

        except Exception as e:
            print(f"  ❌ Error: {e}")


async def run_automated_demo(client: Client):
    """Automated demo: runs a scripted scenario showing the full lifecycle."""
    customer_id = "demo-customer-001"
    input_data = EnrollmentInput(
        customer_id=customer_id,
        customer_name="Alex Johnson",
        initial_points=100,
    )
    workflow_id = f"rewards-customer-{customer_id}"

    print(f"\n{'=' * 60}")
    print("  Rewards Program — Automated Demo Scenario")
    print(f"{'=' * 60}\n")

    # Start workflow
    handle = await client.start_workflow(
        RewardsWorkflow.run,
        input_data,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    print("Enrolled Andrew Lavoie (100 pts welcome bonus)")
    await asyncio.sleep(1)

    # Earn points toward gold
    scenarios = [
        (200, "purchase", "Holiday shopping spree"),
        (150, "purchase", "Electronics order"),
        (50, "review", "Product review bonus"),
        (100, "referral", "Friend referral bonus"),
        # Now at 600 pts = gold
    ]

    for pts, source, desc in scenarios:
        await handle.signal(
            RewardsWorkflow.add_points,
            AddPointsSignal(points=pts, source=source, description=desc),
        )
        await asyncio.sleep(0.5)
        status = await handle.query(RewardsWorkflow.get_status)
        assert status is not None
        print(f"  +{pts:>4} pts ({source:>10}): {status.points} pts total → {status.tier}")

    print("\nTier check via Query: ", end="")
    level = await handle.query(RewardsWorkflow.get_level)
    print(f"{level}")

    # Redeem some points
    print("\n--- Redemption ---")
    await handle.signal(
        RewardsWorkflow.redeem_points,
        RedeemPointsSignal(points=200, reward_description="$20 store credit"),
    )
    await asyncio.sleep(1)
    status = await handle.query(RewardsWorkflow.get_status)
    assert status is not None
    print(f"  Redeemed 200 pts → {status.points} pts remaining, tier: {status.tier}")

    # Earn more to reach Platinum
    print("\n--- Push to Platinum ---")
    big_purchases = [
        (300, "purchase", "Premium Apple AI Top Secret Subscription"),
        (200, "purchase", "Signal Blocking Accessories bundle"),
        # Should push past 1000
    ]
    for pts, source, desc in big_purchases:
        await handle.signal(
            RewardsWorkflow.add_points,
            AddPointsSignal(points=pts, source=source, description=desc),
        )
        await asyncio.sleep(0.5)
        status = await handle.query(RewardsWorkflow.get_status)
        assert status is not None
        print(f"  +{pts:>4} pts ({source:>10}): {status.points} pts total → {status.tier}")

    # Final status
    print("\n--- Final Status (Query) ---")
    status = await handle.query(RewardsWorkflow.get_status)
    assert status is not None
    print(f"  Points:    {status.points}")
    print(f"  Tier:      {status.tier}")
    print(f"  Earned:    {status.total_points_earned} (lifetime)")
    print(f"  Redeemed:  {status.total_points_redeemed} (lifetime)")
    print(f"  Events:    {status.event_count}")

    print("\n--- Leaving Program (Signal) ---")
    await handle.signal(RewardsWorkflow.leave_program)
    result = await handle.result()
    print(f"  Membership ended. Final state: {result.tier}, {result.points} pts")

    print(f"\n{'=' * 60}")
    print("  Demo complete! Check the Temporal UI for the full Event History:")
    print(f"  http://localhost:8233/namespaces/default/workflows/{workflow_id}")
    print(f"{'=' * 60}\n")


async def main(scenario: str | None = None):
    client = await Client.connect("localhost:7233")

    if scenario == "quick-demo":
        await run_automated_demo(client)
    else:
        await run_interactive(client)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rewards program client")
    parser.add_argument(
        "--scenario",
        choices=["quick-demo"],
        help="Run an automated demo scenario instead of interactive mode",
    )
    args = parser.parse_args()
    asyncio.run(main(scenario=args.scenario))
