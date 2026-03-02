"""Rewards Program Worker — hosts the RewardsWorkflow and its activities."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import (
    apply_reward_redemption,
    process_offboarding,
    send_tier_change_notification,
    send_welcome_email,
)
from .workflows import RewardsWorkflow

TASK_QUEUE = "rewards-program-queue"


async def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    client = await Client.connect("localhost:7233")
    logger.info(f"Connected to Temporal. Starting worker on queue '{TASK_QUEUE}'...")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[RewardsWorkflow],
        activities=[
            send_welcome_email,
            send_tier_change_notification,
            process_offboarding,
            apply_reward_redemption,
        ],
    )

    logger.info("Worker started. Ctrl+C to stop.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
