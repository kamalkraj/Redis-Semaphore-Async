# Redis-Semaphore-Async

Redis-Semaphore-Async is a Python library that provides an asynchronous semaphore implementation using Redis as the backend. It allows you to manage concurrent access to resources in a distributed environment.

## Installation

To install Redis-Semaphore-Async, you can use pip:

```sh
pip install redis-semaphore-async
```

## Usage

Here is an example of how to use Redis-Semaphore-Async:

```python
import asyncio
from uuid import uuid4
from redis.asyncio import Redis
from redis_semaphore_async import Semaphore

async def main():
    redis = Redis(host='localhost', port=6379, decode_responses=True)
    task_id = uuid4()
    async with Semaphore(redis=redis, task_name="test_semaphore", task_id=task_id, value=5) as sem:
        # Your code here
        pass

if __name__ == "__main__":
    asyncio.run(main())
```

## Contributing

We welcome contributions! Please read our [contributing guidelines](CONTRIBUTING.md) for more information.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
