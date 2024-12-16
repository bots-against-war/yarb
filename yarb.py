import argparse
import asyncio
import itertools
import logging
import time
from dataclasses import dataclass
from typing import Callable, Generator, Sequence, TextIO, TypeVar
from urllib.parse import urlparse

import tenacity
from redis.asyncio import Redis  # type: ignore
from tqdm import tqdm  # type: ignore

logger = logging.getLogger("yarb")


WrappedFuncT = TypeVar("WrappedFuncT")


def redis_retry() -> Callable[[WrappedFuncT], WrappedFuncT]:
    return tenacity.retry(  # type: ignore
        wait=tenacity.wait.wait_random_exponential(multiplier=1, max=30, exp_base=2, min=0.5),
        stop=tenacity.stop.stop_after_delay(max_delay=60),
        retry=tenacity.retry_if_exception_type(),
        after=tenacity.after.after_log(logger, log_level=logging.WARNING),
    )


def create_redis(redis_url: str) -> Redis:
    url_parsed = urlparse(redis_url)
    return Redis(
        host=url_parsed.hostname,
        port=url_parsed.port,
        username=url_parsed.username,
        password=url_parsed.password,
        decode_responses=True,  # we expect all data to be strings
        ssl=True,
        ssl_cert_reqs=None,  # this is required for Heroku-managed redis, full SSL config TBD
    )


ItemT = TypeVar("ItemT")


def batches(seq: Sequence[ItemT], size: int) -> Generator[Sequence[ItemT], None, None]:
    return (seq[pos : pos + size] for pos in range(0, len(seq), size))


@redis_retry()
async def key_value_cmds(r: Redis, key: str, cmd_batch_size: int, scan_batch_size: int) -> list[list[str]]:
    """Port of https://github.com/upstash/upstash-redis-dump/blob/7ac7c7ebb1b72726cef19df56831327dbc4e0fc8/redisdump/redisdump.go#L148"""
    key_type = await r.type(key)
    logger.debug(f"Key {key!r} has type {key_type!r}")
    match key_type:
        case "string":
            if (value := await r.get(key)) is not None:
                return [["SET", key, value]]
            else:
                return []  # preventing race condition, key could be deleted already
        case "list":
            values = await r.lrange(key, 0, -1)
            return [["RPUSH", key, *value_batch] for value_batch in batches(values, size=cmd_batch_size)]
        case "set":
            values = []
            cursor = "0"
            while cursor != 0:
                cursor, values_batch = await r.sscan(key, cursor=cursor, count=scan_batch_size)
                values.extend(values_batch)
            return [["SADD", key, *value_batch] for value_batch in batches(values, size=cmd_batch_size)]
        case "hash":
            key_value_pairs = dict()
            cursor = "0"
            while cursor != 0:
                cursor, batch = await r.hscan(key, cursor=cursor, count=scan_batch_size)
                key_value_pairs.update(batch)
            return [
                ["HSET", key, *list(itertools.chain.from_iterable(key_value_pairs_batch))]
                for key_value_pairs_batch in batches(list(key_value_pairs.items()), size=cmd_batch_size)
            ]
        case "zset":
            logger.error("Zsets are not supported")
            return []
        case "none":
            return []
        case _:
            logger.error(f"Unexpected keys type: {key_type}")
            return []


@redis_retry()
async def key_ttl_cmd(r: Redis, key: str) -> list[str]:
    ttl = await r.ttl(key)
    if ttl > 0:
        return ["EXPIREAT", key, str(int(time.time() + ttl))]
    else:
        return []


def write_cmd_resp(cmd: list[str], file: TextIO) -> None:
    """Port of https://github.com/upstash/upstash-redis-dump/blob/7ac7c7ebb1b72726cef19df56831327dbc4e0fc8/redisdump/redisdump.go#L139"""
    file.write(f"*{len(cmd)}\r\n")
    for arg in cmd:
        file.write(f"${len(arg.encode('utf-8'))}\r\n{arg}\r\n")


async def dump_key_batch(r: Redis, file: TextIO, keys: list[str], cmd_batch_size: int, scan_batch_size: int) -> bool:
    try:
        for key in keys:
            cmds = await key_value_cmds(r, key, cmd_batch_size=cmd_batch_size, scan_batch_size=scan_batch_size)
            cmds.append(await key_ttl_cmd(r, key))
            for cmd in cmds:
                write_cmd_resp(cmd, file)
        return True
    except Exception:
        logger.exception("Error dumping key batch")
        return False


@dataclass
class YarbOptions:
    keys_match: str
    db: int
    workers: int
    scan_batch_size: int
    cmd_batch_size: int

    @classmethod
    def add_argparse_options(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--keys", default="*", help="Match pattern for Redis SCAN command")
        parser.add_argument("--db", default="0", type=int, help="Redis DB to dump")
        parser.add_argument("--workers", default="1", type=int, help="Number of parallel requests to Redis")
        parser.add_argument(
            "--scan-batch-size",
            default="100",
            type=int,
            help="Batch size for scanning Redis keys, sets and hsets",
        )
        parser.add_argument(
            "--cmd-batch-size",
            default="1000",
            type=int,
            help="Batch size for generated backup commands (RPUSH, SADD, HSET)",
        )

    @classmethod
    def from_args(cls, args: argparse.Namespace):
        return YarbOptions(
            keys_match=args.keys,
            db=int(args.db),
            workers=int(args.workers),
            scan_batch_size=int(args.scan_batch_size),
            cmd_batch_size=int(args.cmd_batch_size),
        )


async def yarb_run(
    redis_url: str,
    output_filename: str,
    options: YarbOptions,
) -> int:
    logger.info(f"Running yarb with options: {options}, writing output to {output_filename}")

    r = create_redis(redis_url)
    start_time = time.time()
    await r.ping()
    logger.info(f"Redis ping returned in {time.time() - start_time:.4f} sec")

    await r.select(options.db)
    logger.info(f"Redis DB #{options.db} selected")

    total_keys = await r.dbsize()
    logger.info(f"Total keys in the database: {total_keys}")

    worker_tasks: set[asyncio.Task[bool]] = set()
    cursor = "0"
    dumped_keys = 0
    with tqdm() as progress_bar, open(output_filename, "w") as file:
        while cursor != 0:
            cursor, key_batch = await r.scan(cursor=cursor, match=options.keys_match, count=options.scan_batch_size)
            if worker_tasks and len(worker_tasks) >= options.workers:
                for earliest in asyncio.as_completed(worker_tasks):
                    is_success = await earliest
                    if not is_success:
                        raise RuntimeError("Backup is broken, one of the workers failed to dump its batch")
                    break
            task = asyncio.create_task(
                dump_key_batch(
                    r=r,
                    file=file,
                    keys=key_batch,
                    cmd_batch_size=options.cmd_batch_size,
                    scan_batch_size=options.scan_batch_size,
                )
            )
            worker_tasks.add(task)
            task.add_done_callback(worker_tasks.discard)
            progress_bar.update(n=len(key_batch))
            dumped_keys += len(key_batch)
        for earliest in asyncio.as_completed(worker_tasks):
            is_success = await earliest
            if not is_success:
                raise RuntimeError("Backup is broken, one of the workers failed to dump its batch")
    logger.info(f"Done, {dumped_keys} out of total {total_keys} keys were matched and dumped!")
    return dumped_keys


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("redis_url")
    parser.add_argument("output_filename")
    YarbOptions.add_argparse_options(parser)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    args = parser.parse_args()

    asyncio.run(
        yarb_run(
            redis_url=args.redis_url,
            output_filename=args.output_filename,
            options=YarbOptions.from_args(args),
        )
    )
