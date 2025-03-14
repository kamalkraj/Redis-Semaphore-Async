import asyncio
import logging
import os
import time
from typing import Any, Callable, Coroutine

from redis.asyncio import Redis

from redis_semaphore_async import Semaphore

# Configure logging with more detailed setup
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler("semaphore_test.log", mode="w"), logging.StreamHandler()],
)
logger = logging.getLogger("semaphore_test")

# Global configuration
SEMAPHORE_LIMIT = 5
SEMAPHORE_NAME = "test_semaphore"

# Global counter
value = 1000


# Redis connection setup with better error handling
async def get_redis_connection() -> Redis:
    """Create and test Redis connection."""
    redis = Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        password=os.getenv("REDIS_PASSWORD", None),
        decode_responses=True,
    )
    # Test the connection
    try:
        await redis.ping()
        logger.info("Successfully connected to Redis")
        return redis
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise


async def value_func(increment: int = 1) -> int:
    """Increment global value after sleeping for specified time.

    Args:
        increment: Amount to increment and seconds to sleep

    Returns:
        The new value after incrementing
    """
    global value
    start_time = time.time()
    logger.info(f"Starting increment operation with value {increment}")
    await asyncio.sleep(increment)
    value += increment
    end_time = time.time()

    logger.info(f"Value incremented by {increment}: new value = {value}")
    logger.info(f"Time taken: {end_time - start_time:.2f} seconds")

    return value


async def run_semaphore(increment: int = 1) -> None:
    """Test the semaphore by incrementing a value using context manager.

    Args:
        increment: The increment amount and sleep duration
    """
    logger.debug(f"Attempting to acquire semaphore for increment {increment}")
    await asyncio.sleep(1)  # Simulate initial delay

    async with Semaphore(redis=await get_redis_connection(), task_name=SEMAPHORE_NAME, value=SEMAPHORE_LIMIT):
        logger.debug(f"Acquired semaphore for increment {increment}")
        await value_func(increment)
        logger.debug(f"Releasing semaphore for increment {increment}")


async def time_execution(func: Callable[..., Coroutine[Any, Any, Any]], *args, **kwargs) -> float:
    """Execute a coroutine and measure its execution time.

    Args:
        func: Coroutine function to execute
        args, kwargs: Arguments to pass to the function

    Returns:
        Execution time in seconds
    """
    start_time = time.time()
    await func(*args, **kwargs)
    execution_time = time.time() - start_time
    return execution_time


async def test_semaphore() -> None:
    """Test basic semaphore functionality."""
    logger.info("=== Testing basic semaphore functionality ===")
    execution_time = await time_execution(run_semaphore, 1)
    logger.info(f"Test completed in {execution_time:.2f} seconds")


async def test_semaphore_multiple() -> None:
    """Test semaphore with multiple concurrent tasks."""
    logger.info("=== Testing semaphore with multiple concurrent tasks ===")
    tasks = []
    for i in range(1, 10):
        tasks.append(run_semaphore(i))

    execution_time = await time_execution(asyncio.gather, *tasks)
    logger.info(f"Test completed in {execution_time:.2f} seconds")


async def test_semaphore_without_with() -> None:
    """Test semaphore without context manager."""
    logger.info("=== Testing semaphore without context manager ===")
    redis_conn = await get_redis_connection()
    semaphore = Semaphore(redis=redis_conn, task_name=SEMAPHORE_NAME, value=SEMAPHORE_LIMIT)

    try:
        await semaphore.acquire()
        logger.debug("Semaphore acquired manually")
        await value_func(1)
    finally:
        await semaphore.release()
        logger.debug("Semaphore released manually")


async def test_semaphore_with_multiple() -> None:
    """Test semaphore with shared instance across multiple tasks."""
    logger.info("=== Testing semaphore with shared instance ===")
    redis_conn = await get_redis_connection()
    semaphore = Semaphore(redis=redis_conn, task_name=SEMAPHORE_NAME, value=SEMAPHORE_LIMIT)

    async def run_task(i: int) -> None:
        logger.debug(f"Task {i} attempting to acquire semaphore")
        async with semaphore:
            logger.debug(f"Task {i} acquired semaphore")
            await value_func(i)
            logger.debug(f"Task {i} releasing semaphore")

    tasks = []
    for i in range(1, 10):
        tasks.append(run_task(i))

    execution_time = await time_execution(asyncio.gather, *tasks)
    logger.info(f"Test completed in {execution_time:.2f} seconds")


async def main() -> None:
    """Run all semaphore tests sequentially."""
    global value
    logger.info("Starting semaphore tests")

    # Reset Redis connection for each test to ensure clean state
    try:
        # Run tests sequentially
        await test_semaphore()
        value = 1000  # Reset value between tests

        await test_semaphore_multiple()
        value = 1000

        await test_semaphore_without_with()
        value = 1000

        await test_semaphore_with_multiple()

        logger.info("All tests completed successfully")
    except Exception as e:
        logger.error(f"Error during tests: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
