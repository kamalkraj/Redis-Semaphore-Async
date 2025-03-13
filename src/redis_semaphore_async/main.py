import logging
from uuid import UUID

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
        with statement exits.
        """
        await self.release()


class Semaphore(_ContextManagerMixin):

    def __init__(
        self,
        redis: Redis,
        task_name: str,
        task_id: UUID,
        value: int = 1,
        namespace: str = "semaphore",
        delay: float = 0.1,
    ):
        self.redis = redis
        self._value = value
        self.task_id = str(task_id)
        self._delay = delay
        self._key = f"{namespace}:{task_name}"
        self.lock_key = f"{self._key}:lock"
        self._waiters_key = f"{self._key}:waiters"
        self._pubsub_key = f"{self._key}:channel"

    async def acquire(self) -> bool:
        """
        Acquire the semaphore.
        """
        # acquire lock to set the counter value
        lock = Lock(self.redis, self.lock_key)
        await lock.acquire()
        logger.info(f"Acquiring semaphore {self._key} with task id {self.task_id}")
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
                logger.info(f"Semaphore {self._key} acquired by task id {self.task_id}")
                # if the semaphore is available, decrement the counter
                await self.redis.decr(self._key)
                return True
            # if the semaphore is not available, wait for it to be released
            # first push the task id to the list of waiters
            await self.redis.lpush(self._waiters_key, self.task_id)
            # then subscribe to the channel
            await pubsub.subscribe(self._pubsub_key)
            await lock.release()
            # wait for the semaphore to be released
            async for message in pubsub.listen():
                # check if the message received
                if message["type"] == "message":
                    # lindex the list of waiters
                    task_id = await self.redis.lindex(self._waiters_key, -1)
                    if task_id is None:
                        # if the list is empty, break the loop
                        break

                    if task_id == self.task_id:
                        await lock.acquire()
                        # if the task id matches, release the semaphore
                        # remove the task id from the list of waiters
                        await self.redis.rpop(self._waiters_key)
                        await self.redis.decr(self._key)
                        await pubsub.unsubscribe(self._pubsub_key)
                        await lock.release()
                        logger.info(f"Semaphore {self._key} acquired by task id {self.task_id}")
                        return True
                    else:
                        # if the task id does not match, continue waiting
                        logger.info(f"Semaphore {self._key} not available, waiting for it to be released")
                        continue

        except Exception as e:
            logger.error(f"Error acquiring semaphore: {e}")
            # unsubscribe from the channel
            await pubsub.unsubscribe(self._pubsub_key)
            # remove the task id from the list of waiters
            await self.redis.lrem(self._waiters_key, 0, self.task_id)
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
                await self.redis.publish(self._pubsub_key, self.task_id)
                logger.info(f"Releasing semaphore {self._key} with task id {self.task_id}")
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
