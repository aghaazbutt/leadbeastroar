"""Worker entrypoint: `python -m leadbeast.pipeline.worker`."""

from __future__ import annotations

import asyncio

from leadbeast.logging import configure_logging
from leadbeast.pipeline.app import app


async def main() -> None:
    configure_logging()
    async with app.open_async():
        await app.run_worker_async(queues=None, concurrency=4)


if __name__ == "__main__":
    asyncio.run(main())
