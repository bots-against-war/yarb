import argparse
import asyncio
import datetime
import json
import logging
import os
import socket
import time
from pathlib import Path

from telebot_components.utils.alerts import configure_alerts

from yarb import YarbOptions, create_redis, yarb_run

logger = logging.getLogger("backup")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

backups_dir = Path(__file__).parent / "backups"
backups_dir.mkdir(exist_ok=True)


async def periodic_backup(
    redis_url: str,
    backups_dir: Path,
    period_hrs: float,
    keep_last: int,
    first_wait: bool,
    yarb_options: YarbOptions,
) -> None:
    backups_dir.mkdir(exist_ok=True, parents=True)
    has_backed_up = False

    start_time = time.time()
    await create_redis(redis_url).ping()
    logger.info(f"Redis ping returned in {time.time() - start_time}")

    logger.info("Starting periodic backups")
    while True:
        try:
            period_sec = period_hrs * 3600
            last_backup_epoch = time.time() // period_sec
            next_backup_time = (last_backup_epoch + 1) * period_sec
            wait_time = next_backup_time - time.time()
            if wait_time > 0 and (has_backed_up or first_wait):
                next_backup_dt = datetime.datetime.fromtimestamp(next_backup_time)
                logger.info(f"Next backup in {next_backup_dt}, sleeping for {wait_time:.2f} sec")
                await asyncio.sleep(wait_time)
            logger.info(f"Starting backup")
            dump_file = backups_dir / f"redis-backup-{datetime.datetime.now().isoformat(timespec='seconds')}.resp"
            start_time = time.time()
            try:
                key_count = await yarb_run(
                    redis_url=redis_url,
                    output_filename=str(dump_file),
                    options=yarb_options,
                )
            except Exception:
                logger.exception("Error running yarb backup")
                dump_file.unlink(missing_ok=True)
                continue

            metadata_entry = {
                "timestamp": time.time(),
                "filename": dump_file.name,
                "dump_time": time.time() - start_time,
                "total_keys": key_count,
                "dump_size_mb": dump_file.stat().st_size / (1024**2),
            }
            has_backed_up = True
            metadata_file = backups_dir / "metadata.json"
            if metadata_file.exists():
                metadata = json.loads(metadata_file.read_text())
            else:
                metadata = []
            metadata.append(metadata_entry)
            metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))

            all_backup_files = [p for p in backups_dir.iterdir() if p.name.startswith("redis-backup")]
            all_backup_files.sort(key=lambda f: f.stat().st_ctime, reverse=True)  # new -> old
            for outdated_backup_file in all_backup_files[keep_last:]:
                logger.info(f"Deleting outdated {outdated_backup_file}")
                outdated_backup_file.unlink(missing_ok=True)
        except Exception:
            logger.exception("Error creating backup, will try next time")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--redis-url", default="_env", help="Redis URL; defaults to REDIS_URL environment variable")
    parser.add_argument("--backups-dir", default="backups", help="Directory to store backups and metadata")
    parser.add_argument("--period", default="1", type=float, help="Backup period in hours")
    parser.add_argument("--keep-last", default="24", type=int, help="Number of most recent backups to store")
    parser.add_argument(
        "--no-first-wait", action="store_true", help="Start first backup immediately, not on the next epoch"
    )
    YarbOptions.add_argparse_options(parser)

    args = parser.parse_args()

    redis_url = args.redis_url
    if redis_url == "_env":
        redis_url = os.environ.get("REDIS_URL")
        if redis_url is None:
            raise RuntimeError("REDIS_URL env var is not set")

    bot_token = os.environ.get("BOT_TOKEN")
    alerts_channel_id = os.environ.get("ALERTS_CHANNEL_ID")
    if bot_token is not None and alerts_channel_id is not None:
        configure_alerts(
            token=bot_token,
            alerts_channel_id=alerts_channel_id,
            app_name=f"Periodic redis backup ({socket.gethostname()})",
        )
    
    # TEMP
    logger.error("ERROR EXAMPLE")

    asyncio.run(
        periodic_backup(
            redis_url=redis_url,
            backups_dir=Path(args.backups_dir),
            period_hrs=float(args.period),
            keep_last=int(args.keep_last),
            first_wait=not bool(args.no_first_wait),
            yarb_options=YarbOptions.from_args(args),
        )
    )
