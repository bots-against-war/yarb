import asyncio
import datetime
import json
import logging
import os
import time
from pathlib import Path

from yarb import create_redis, yarb_run

logger = logging.getLogger("backup")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

KEEP_LAST = 24

BACKUPS_DIR = Path(__file__).parent / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)
METADATA_FILE = BACKUPS_DIR / "metadata.json"


async def periodic_backups():
    redis_url = os.environ["REDIS_URL"]
    await create_redis(redis_url).ping()

    logger.info("Starting periodic backups")
    while True:
        try:
            now = datetime.datetime.now()
            hour_from_now = now + datetime.timedelta(hours=1)
            next_backup = datetime.datetime(
                year=hour_from_now.year,
                month=hour_from_now.month,
                day=hour_from_now.day,
                hour=hour_from_now.hour,
                minute=0,
                second=0,
            )
            wait_time = (next_backup - now).total_seconds()
            if wait_time > 0 and not os.environ.get("NO_FIRST_WAIT"):
                logger.info(f"Next backup in {next_backup}, sleeping for {wait_time:2f} sec")
                await asyncio.sleep(wait_time)
            logger.info(f"Starting backup")
            dump_file = BACKUPS_DIR / f"redis-backup-{datetime.datetime.now().isoformat(timespec='seconds')}.resp"
            start_time = time.time()
            key_count = await yarb_run(
                redis_url=redis_url,
                output_filename=str(dump_file),
                keys_match="*",
                db=0,
                workers=20,
                scan_batch_size=100,
                cmd_batch_size=1000,
            )
            dump_metadata = {
                "timestamp": time.time(),
                "dump_time": time.time() - start_time,
                "total_keys": key_count,
                "dump_size_mb": dump_file.stat().st_size / (1024**2),
            }
            if METADATA_FILE.exists():
                metadata = json.loads(METADATA_FILE.read_text())
            else:
                metadata = []
            metadata.append(dump_metadata)
            METADATA_FILE.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))

            all_backup_files = [p for p in BACKUPS_DIR.iterdir() if p.name.startswith("redis-backup")]
            all_backup_files.sort(key=lambda f: f.stat().st_ctime, reverse=True)  # new -> old
            for outdated_backup_file in all_backup_files[KEEP_LAST:]:
                logger.info(f"Deleting outdated {outdated_backup_file}")
                outdated_backup_file.unlink(missing_ok=True)
        except Exception:
            logger.exception("Error creating backup")


if __name__ == "__main__":
    asyncio.run(periodic_backups())
