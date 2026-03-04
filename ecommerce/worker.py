"""E-Commerce Worker — runs the OrderWorkflow and its activities."""

import asyncio
import logging

from temporalio.client import Client
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
from ecommerce.workflows import OrderWorkflow

TASK_QUEUE = "ecommerce-order-queue"


async def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Connect to the local dev Temporal server
    client = await Client.connect("localhost:7233")
    logger.info(f"Connected to Temporal. Starting worker on queue '{TASK_QUEUE}'...")

    # Create a worker that hosts both workflows and activities
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow],
        activities=[
            # Forward activities
            process_payment,
            reserve_inventory,
            ship_package,
            notify_customer,
            # Compensation activities
            refund_payment,
            release_inventory,
            cancel_shipment,
        ],
    )

    logger.info("Worker started. Ctrl+C to stop.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
