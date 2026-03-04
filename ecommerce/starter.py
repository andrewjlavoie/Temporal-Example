"""E-Commerce Starter — launches the order workflow.

Usage:
    # Happy path — all steps succeed
    uv run python ecommerce/starter.py

    # Fail at shipping — triggers compensation (refund + release inventory)
    uv run python ecommerce/starter.py --fail-at shipping

    # Fail at inventory — triggers compensation (refund only)
    uv run python ecommerce/starter.py --fail-at inventory

    # Fail at payment — no compensation needed (nothing to undo)
    uv run python ecommerce/starter.py --fail-at payment

    # Fail at notification — non-critical, order still completes
    uv run python ecommerce/starter.py --fail-at notification
"""

import argparse
import asyncio
import uuid

from temporalio.client import Client

from ecommerce.models import OrderInput, OrderItem
from ecommerce.worker import TASK_QUEUE
from ecommerce.workflows import OrderWorkflow


async def main(fail_at: str | None = None):
    client = await Client.connect("localhost:7233")

    # Create a realistic order
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    order = OrderInput(
        order_id=order_id,
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
                product_name="Laptop Sleeve, Top Secret ",
                quantity=1,
                unit_price=49.99,
            ),
        ],
        shipping_address="123 Main St, Colorado Springs, CO 80919",
        fail_at_step=fail_at,
    )

    print(f"\n{'=' * 60}")
    print("  Starting Order Workflow")
    print(f"  Order ID:    {order.order_id}")
    print(f"  Workflow ID: order-{order.order_id}")
    print(f"  Total:       ${order.total_amount:.2f}")
    print(f"  Items:       {len(order.items)}")
    if fail_at:
        print(f"  ⚠️  Injecting failure at: {fail_at}")
    print(f"{'=' * 60}\n")

    # Start the workflow with the order ID as the Workflow ID.
    # This ensures idempotency: starting the same order twice
    # returns a handle to the existing workflow, not a duplicate.
    handle = await client.start_workflow(
        OrderWorkflow.run,
        order,
        id=f"order-{order.order_id}",
        task_queue=TASK_QUEUE,
    )

    print(f"Workflow started. ID: {handle.id}")
    print(f"View in Temporal UI: http://localhost:8233/namespaces/default/workflows/{handle.id}\n")

    # Wait for the result
    result = await handle.result()

    # Query the final status
    status = await handle.query(OrderWorkflow.get_status)

    print(f"\n{'=' * 60}")
    print("  Workflow Complete")
    print(f"  Status: {status}")
    if result.get("status") == "completed":
        print(f"  Transaction ID:  {result['payment_transaction_id']}")
        print(f"  Tracking Number: {result['tracking_number']}")
        print(f"  Est. Delivery:   {result['estimated_delivery']}")
    elif result.get("status") == "compensated":
        print(f"  Failure Reason:  {result['failure_reason']}")
        print("  All compensations executed successfully.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start an e-commerce order workflow")
    parser.add_argument(
        "--fail-at",
        choices=["payment", "inventory", "shipping", "notification"],
        help="Inject a failure at a specific step to demonstrate saga compensation",
    )
    args = parser.parse_args()
    asyncio.run(main(fail_at=args.fail_at))
