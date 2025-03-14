import logging
from uuid import uuid4

from redis.asyncio import Redis
from redis.asyncio.lock import Lock

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class _ContextManagerMixin:
    async def __aenter__(self) -> None:
        """
        Context manager entry point. This is called when the
        'with' statement is used. It acquires the semaphore.
        """
        await self.acquire()
        # We have no use for the "as ..."  clause in the with
        # statement for locks.
        return None

    async def __aexit__(self, exc_type, exc, tb):
        """ ""
        Context manager exit point. This is called when the
        with statement exits. It releases the semaphore that was acquired
        when entering the context.
        """
        await self.release()


class Semaphore(_ContextManagerMixin):
    """ "
    A distributed semaphore implementation using Redis for synchronization across distributed processes.

    This class implements a counting semaphore that works across multiple processes or services
    by utilizing Redis as a centralized coordination mechanism. The semaphore maintains a counter
    that limits the number of concurrent accesses to a shared resource.

    The implementation uses a combination of Redis data structures:
    - A key to store the semaphore counter value
    - A list to maintain waiting tasks
    - A pub/sub channel for notifying waiting tasks
    - A lock to ensure atomic operations

    The semaphore supports asynchronous operations and can be used as a context manager.

    Attributes:
        redis (Redis): Redis client instance for communication with Redis server
        _value (int): Maximum number of concurrent accesses allowed by the semaphore
        task_id (str): Unique identifier for the task using this semaphore
        _key (str): Redis key for storing the semaphore counter
        lock_key (str): Redis key for the lock used to ensure atomic operations
        _waiters_key (str): Redis key for the list of waiting tasks
        _pubsub_key (str): Redis key for the pub/sub channel

    Example:
        ```
        redis_client = Redis.from_url("redis://localhost")
        sem = Semaphore(
            redis=redis_client,
            task_name="resource_access",
            value=3,  # Allow 3 concurrent accesses
        )

        async with sem:
            # Access the protected resource
            await perform_limited_operation()
        ```
    """

    def __init__(
        self,
        redis: Redis,
        task_name: str,
        value: int = 1,
        namespace: str = "semaphore",
    ):
        self.redis = redis
        self._value = value
        self._key = f"{namespace}:{task_name}"
        self.lock_key = f"{self._key}:lock"
        self._waiters_key = f"{self._key}:waiters"
        self._pubsub_key = f"{self._key}:channel"

    async def acquire(self) -> bool:
        """
        Acquire the semaphore.
        """
        # acquire lock to set the counter value
        task_id = str(uuid4())
        lock = Lock(self.redis, self.lock_key)
        await lock.acquire()
        logger.debug(f"Acquiring semaphore {self._key} with task id {task_id}")
        pubsub = self.redis.pubsub()
        try:
            # check if the semaphore is available
            exists = await self.redis.exists(self._key)
            if exists == 0:
                # if not, set the counter value
                await self.redis.set(self._key, self._value)
            # get the current value of the semaphore
            current_value = await self.redis.get(self._key)

            if int(current_value) > 0:
                logger.debug(f"Semaphore {self._key} acquired by task id {task_id}")
                # if the semaphore is available, decrement the counter
                await self.redis.decr(self._key)
                return True
            # if the semaphore is not available, wait for it to be released
            # first push the task id to the list of waiters
            await self.redis.lpush(self._waiters_key, task_id)
            # then subscribe to the channel
            await pubsub.subscribe(self._pubsub_key)
            await lock.release()
            # wait for the semaphore to be released
            async for message in pubsub.listen():
                # check if the message received
                if message["type"] == "message":
                    # lindex the list of waiters
                    next_task_id = await self.redis.lindex(self._waiters_key, -1)
                    if next_task_id is None:
                        # Task ID should not be None if we've received a message
                        # Raise exception to prevent silent failures
                        raise RuntimeError(f"Task ID is None for semaphore {self._key}, waiters list may be corrupted")

                    if next_task_id == task_id:
                        await lock.acquire()
                        # if the task id matches, release the semaphore
                        # remove the task id from the list of waiters
                        await self.redis.rpop(self._waiters_key)
                        await self.redis.decr(self._key)
                        await pubsub.unsubscribe(self._pubsub_key)
                        await lock.release()
                        logger.debug(f"Semaphore {self._key} acquired by task id {task_id}")
                        return True
                    else:
                        # if the task id does not match, continue waiting
                        logger.debug(f"Semaphore {self._key} not available, waiting for it to be released")
                        continue

        except Exception as e:
            logger.error(f"Error acquiring semaphore: {e}")
            # unsubscribe from the channel
            await pubsub.unsubscribe(self._pubsub_key)
            # remove the task id from the list of waiters
            await self.redis.lrem(self._waiters_key, 0, task_id)
            # increment the counter value
            await self.redis.incr(self._key)
            # raise the exception
            raise e
        finally:
            await pubsub.aclose()
            # release the lock
            if await lock.owned():
                await lock.release()

    async def release(self) -> None:
        """Release a semaphore, incrementing the internal counter by one."""
        # acquire lock to set the counter value
        lock = Lock(self.redis, self.lock_key)
        await lock.acquire()
        try:
            current_value = await self.redis.get(self._key)
            if (current_value is not None) and int(current_value) < self._value:
                # if the semaphore is available, increment the counter
                await self.redis.incr(self._key)
                await self.redis.publish(self._pubsub_key, "release")
                logger.debug(f"Releasing semaphore {self._key}")
                return
            # send a message to the channel
        except Exception as e:
            logger.error(f"Error releasing semaphore: {e}")
            # raise the exception
            raise e
        finally:
            # release the lock
            if await lock.owned():
                await lock.release()
