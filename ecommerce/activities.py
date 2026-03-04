"""Activities for the e-commerce order workflow.

Each activity is an interaction with an external service.
For this demo, all interactions are mocked.

1 Each activity has its own retry policy (tuned per service characteristics)
2 Heartbeats on long-running activities (shipping)
3 Activities are idempotent — safe to retry without side effects
4 Compensation activities undo the effects of successful activities
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from temporalio import activity

from ecommerce.models import (
    InventoryResult,
    NotificationResult,
    OrderInput,
    PaymentResult,
    ShippingResult,
)

# Forward activities (the "happy path")

@activity.defn
async def process_payment(order: OrderInput) -> PaymentResult:
    """Charge the customer's payment method."""
    activity.logger.info(
        f"Processing payment of ${order.total_amount:.2f} for order {order.order_id}"
    )

    # Simulate processing time
    await asyncio.sleep(1.0)

    # Configurable failure injection for demo
    if order.fail_at_step == "payment":
        raise RuntimeError(f"Payment declined for order {order.order_id}: insufficient funds")

    return PaymentResult(
        transaction_id=f"txn_{uuid.uuid4().hex[:12]}",
        amount_charged=order.total_amount,
        status="charged",
    )


@activity.defn
async def reserve_inventory(order: OrderInput) -> InventoryResult:
    """Reserve items in the warehouse."""
    activity.logger.info(
        f"Reserving inventory for order {order.order_id}: "
        f"{[f'{i.quantity}x {i.product_name}' for i in order.items]}"
    )

    await asyncio.sleep(0.8)

    if order.fail_at_step == "inventory":
        raise RuntimeError(
            f"Inventory reservation failed for order {order.order_id}: "
            f"item '{order.items[0].product_name}' out of stock"
        )

    return InventoryResult(
        reservation_id=f"res_{uuid.uuid4().hex[:12]}",
        items_reserved=[item.product_id for item in order.items],
        warehouse_id="warehouse-east-1",
    )


@activity.defn
async def ship_package(order: OrderInput) -> ShippingResult:
    """Create a shipping label and dispatch the package."""
    activity.logger.info(f"Creating shipment for order {order.order_id}")

    # Report progress via heartbeat — Temporal will detect if we stall
    activity.heartbeat("Creating shipping label...")
    await asyncio.sleep(0.5)

    activity.heartbeat("Validating address...")
    await asyncio.sleep(0.5)

    if order.fail_at_step == "shipping":
        raise RuntimeError(
            f"Shipping failed for order {order.order_id}: "
            f"address validation failed for '{order.shipping_address}'"
        )

    activity.heartbeat("Dispatching package...")
    await asyncio.sleep(0.5)

    delivery_date = datetime.now(UTC) + timedelta(days=5)

    return ShippingResult(
        tracking_number=f"TRK{uuid.uuid4().hex[:10].upper()}",
        carrier="FedEx",
        estimated_delivery=delivery_date.strftime("%Y-%m-%d"),
    )


@activity.defn
async def notify_customer(order: OrderInput, tracking_number: str) -> NotificationResult:
    """Send order confirmation and tracking info to the customer."""
    activity.logger.info(
        f"Sending confirmation to {order.customer_email} for order {order.order_id} "
        f"(tracking: {tracking_number})"
    )

    await asyncio.sleep(0.3)

    if order.fail_at_step == "notification":
        raise RuntimeError(
            f"Notification failed for order {order.order_id}: email service unavailable"
        )

    return NotificationResult(
        notification_id=f"notif_{uuid.uuid4().hex[:12]}",
        channel="email",
        status="sent",
    )



# Compensation activities (undo on failure)


@activity.defn
async def refund_payment(order: OrderInput, payment: PaymentResult) -> str:
    """Refund a previously charged payment.
    Compensating for process_payment.
    Idempotent! Refunding the same transaction twice should be safe (id based).
    """
    activity.logger.info(
        f"COMPENSATING: Refunding ${payment.amount_charged:.2f} "
        f"(txn: {payment.transaction_id}) for order {order.order_id}"
    )
    await asyncio.sleep(0.5)
    return f"Refunded {payment.transaction_id}"


@activity.defn
async def release_inventory(order: OrderInput, reservation: InventoryResult) -> str:
    """Release a previously reserved inventory hold.
    Compensating for reserve_inventory.
    """
    activity.logger.info(
        f"COMPENSATING: Releasing inventory reservation {reservation.reservation_id} "
        f"for order {order.order_id}"
    )
    await asyncio.sleep(0.3)
    return f"Released {reservation.reservation_id}"


@activity.defn
async def cancel_shipment(order: OrderInput, shipment: ShippingResult) -> str:
    """Cancel a previously created shipment.
    Compensating for ship_package.
    """
    activity.logger.info(
        f"COMPENSATING: Cancelling shipment {shipment.tracking_number} for order {order.order_id}"
    )
    await asyncio.sleep(0.3)
    return f"Cancelled {shipment.tracking_number}"
