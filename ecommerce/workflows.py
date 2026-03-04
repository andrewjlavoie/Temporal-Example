"""E-Commerce Order Workflow — Saga Pattern with Compensation.

This workflow orchestrates the complete order fulfillment process:
  Payment → Inventory → Shipping → Notification
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ecommerce.activities import (
        cancel_shipment,
        notify_customer,
        process_payment,
        refund_payment,
        release_inventory,
        reserve_inventory,
        ship_package,
    )
    from ecommerce.models import (
        InventoryResult,
        OrderInput,
        OrderStatus,
        PaymentResult,
        ShippingResult,
    )


@workflow.defn
class OrderWorkflow:
    """Orchestrates the complete order fulfillment lifecycle.

    The saga pattern is implemented as a simple try/except: 
    - 'happy path' executes sequentially, and the except block runs compensations in reverse.
    - Temporal guarantees that this workflow completes — either successfully or
      with all compensations executed — even if workers crash mid-execution.
    """

    def __init__(self) -> None:
        self._status = OrderStatus.PENDING
        self._payment: PaymentResult | None = None
        self._inventory: InventoryResult | None = None
        self._shipment: ShippingResult | None = None

    @workflow.query
    def get_status(self) -> str:
        """Query: Returns the current order status.

        Clients can call this at any time to check progress of an order.
        """
        return self._status.value

    @workflow.run
    async def run(self, order: OrderInput) -> dict:
        workflow.logger.info(
            f"Starting order workflow for {order.order_id} (total: ${order.total_amount:.2f})"
        )

        try:
            # Step 1: Process Payment
            self._status = OrderStatus.PENDING
            self._payment = await workflow.execute_activity(
                process_payment,
                order,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=2),
                    backoff_coefficient=2.0,
                    maximum_attempts=3,
                    # Don't retry on business logic errors (e.g., declined card)
                    non_retryable_error_types=["ValueError"],
                ),
            )
            self._status = OrderStatus.PAYMENT_PROCESSED
            workflow.logger.info(f"Payment processed: {self._payment.transaction_id}")

            # Step 2: Reserve Inventory 
            self._inventory = await workflow.execute_activity(
                reserve_inventory,
                order,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_attempts=5,
                ),
            )
            self._status = OrderStatus.INVENTORY_RESERVED
            workflow.logger.info(f"Inventory reserved: {self._inventory.reservation_id}")

            # Step 3: Ship Package
            self._shipment = await workflow.execute_activity(
                ship_package,
                order,
                start_to_close_timeout=timedelta(seconds=120),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                    maximum_attempts=3,
                ),
            )
            self._status = OrderStatus.SHIPPED
            workflow.logger.info(f"Package shipped: {self._shipment.tracking_number}")

            # Step 4: Notify Customer
            try:
                await workflow.execute_activity(
                    notify_customer,
                    args=[order, self._shipment.tracking_number],
                    start_to_close_timeout=timedelta(seconds=15),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=2),
                        backoff_coefficient=2.0,
                        maximum_attempts=10,
                    ),
                )
                workflow.logger.info("Customer notified successfully")
            except Exception as e:
                # Log but don't fail the order — notification can be retried
                workflow.logger.warning(f"Customer notification failed (non-critical): {e}")

            # ── Order Complete ───────────
            self._status = OrderStatus.COMPLETED
            workflow.logger.info(f"Order {order.order_id} completed successfully")

            return {
                "status": "completed",
                "order_id": order.order_id,
                "payment_transaction_id": self._payment.transaction_id,
                "tracking_number": self._shipment.tracking_number,
                "estimated_delivery": self._shipment.estimated_delivery,
            }

        except Exception as e:
            # Saga Compensation
            # Execute compensations in reverse order for any completed steps.
            # Each compensation is its own activity with its own retry policy.
            # Temporal handles the durable execution, it is still on developers
            # to write the compensation logic, Temporal guarantees the 'transaction' actions
            workflow.logger.error(
                f"Order {order.order_id} failed at status {self._status}: {e}. "
                f"Starting compensation..."
            )
            self._status = OrderStatus.FAILED

            compensation_timeout = timedelta(seconds=30)
            compensation_retry = RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=10
            )

            # Compensate shipping (if shipment was created)
            if self._shipment:
                await workflow.execute_activity(
                    cancel_shipment,
                    args=[order, self._shipment],
                    start_to_close_timeout=compensation_timeout,
                    retry_policy=compensation_retry
                )
                workflow.logger.info("Compensation: shipment cancelled")

            # Compensate inventory (if reservation was made)
            if self._inventory:
                await workflow.execute_activity(
                    release_inventory,
                    args=[order, self._inventory],
                    start_to_close_timeout=compensation_timeout,
                    retry_policy=compensation_retry
                )
                workflow.logger.info("Compensation: inventory released")

            # Compensate payment (if charge was made)
            if self._payment:
                await workflow.execute_activity(
                    refund_payment,
                    args=[order, self._payment],
                    start_to_close_timeout=compensation_timeout,
                    retry_policy=compensation_retry
                )
                workflow.logger.info("Compensation: payment refunded")

            self._status = OrderStatus.COMPENSATED
            workflow.logger.info(f"Order {order.order_id} fully compensated")

            return {
                "status": "compensated",
                "order_id": order.order_id,
                "failure_reason": str(e)
            }
