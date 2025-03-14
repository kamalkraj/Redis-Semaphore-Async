import asyncio
import logging
import os
import time
from uuid import uuid4

from redis.asyncio import Redis

from redis_semaphore_async import Semaphore

logging.basicConfig(
    level=logging.INFO,  # Set the minimum log level
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler("semaphore_test.log", mode="w"), logging.StreamHandler()],
)

redis = Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=os.getenv("REDIS_PORT", 6379),
    password=os.getenv("REDIS_PASSWORD", None),
    decode_responses=True,
)

value = 1000


async def value_func(increment: int = 1):
    global value
    start_time = time.time()
    print(increment)
    await asyncio.sleep(increment)
    value += increment
    print(f"Value incremented by {increment}: {value}")
    end_time = time.time()
    print(f"Time taken to increment value by {increment}: {end_time - start_time:.2f} seconds")


async def run_semaphore(increment: int = 1):
    """
    Test the semaphore by incrementing a value.
    """
    await asyncio.sleep(1)
    task_id = uuid4()
    async with Semaphore(redis=redis, task_name="test_semaphore", task_id=task_id, value=5) as sem:  # noqa: F841
        await value_func(increment)


async def test_semaphore():
    """
    Test the semaphore by incrementing a value.
    """
    await run_semaphore(1)


async def test_semaphore_multiple():
    """
    Test the semaphore by incrementing a value.
    """
    tasks = []
    for i in range(1, 10):
        tasks.append(run_semaphore(i))
    await asyncio.gather(*tasks)


async def main():
    """
    Main function to run the tests.
    """
    await test_semaphore()
    await test_semaphore_multiple()


if __name__ == "__main__":
    asyncio.run(main())
