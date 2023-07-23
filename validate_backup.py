
import asyncio
from typing import Any
from yarb import create_redis, Redis
from tqdm import tqdm

import os


async def get_key_value(redis: Redis, key: str) -> Any:
    key_type = await redis.type(key)
    match key_type:
        case "string":
            return await redis.get(key)
        case "list":
            return await redis.lrange(key, 0, -1)
        case "set":
            return await redis.smembers(key)
        case "hash":
            return await redis.hgetall(key)
        case "zset":
            return None
        case "none":
            return None
        case _:
            return None


async def main():
    prod_redis = create_redis(os.environ["REDIS_URL"])
    await prod_redis.ping()
    print("Prod redis ping ok")

    local_redis = Redis.from_url("redis://localhost:6379", decode_responses=True)
    await local_redis.ping()
    print("Local redis ping ok")

    keys = await local_redis.keys()
    print(f"Retrieved {len(keys)} keys")

    with tqdm(total=len(keys)) as progress_bar, open("backup-validation.log", "w") as file:
        for key in keys:
            local_value = await get_key_value(local_redis, key)
            prod_value = await get_key_value(prod_redis, key)
            if local_value != prod_value:
                print(f"\n{key!r}\n{local_value = }\n{prod_value = }\n\n", file=file)
            progress_bar.update()


asyncio.run(main())
