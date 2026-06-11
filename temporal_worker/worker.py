"""
temporal_worker/worker.py
--------------------------
Temporal worker — registers the workflow and all activities,
connects to the Temporal server, and starts polling for tasks.
"""

import asyncio
import sys
from pathlib import Path
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

sys.path.insert(0, str(Path(__file__).parent.parent))

from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from temporal_worker.workflow import (
    TripBookingWorkflow,
    run_collect_intent,
    run_flight_step,
    run_hotel_step,
    compensate_booking,
)

TEMPORAL_HOST = "localhost:7233"
TASK_QUEUE    = "travel-agent"


async def main():
    client = await Client.connect(TEMPORAL_HOST)
    print(f"Connected to Temporal at {TEMPORAL_HOST}")
    print(f"Worker polling task queue: {TASK_QUEUE}")
    print("Ready. Start a workflow via run.py\n")

    worker = Worker(
        client,
        task_queue = TASK_QUEUE,
        workflows  = [TripBookingWorkflow],
        activities = [
            run_collect_intent,
            run_flight_step,
            run_hotel_step,
            compensate_booking,
        ],
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(
                "shared",
                "pathlib",
                "dataclasses",
                "json",
            )
        ),
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())