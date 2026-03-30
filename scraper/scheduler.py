import logging
import logging.handlers
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

from main import run_rss_pipeline, run_facebook_pipeline
from airtable_client import AirtableClient
from deduplicator import Deduplicator

LOG_FILE = Path(__file__).parent.parent / "scraper.log"

# Configure rotating file + stdout logging
log = logging.getLogger()
log.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")

file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=7
)
file_handler.setFormatter(formatter)
log.addHandler(file_handler)

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)
log.addHandler(stdout_handler)

logger = logging.getLogger(__name__)


def rss_job():
    logger.info("=== RSS job started ===")
    client = AirtableClient()
    dedup = Deduplicator(client)
    count = run_rss_pipeline(client, dedup)
    logger.info(f"=== RSS job done: {count} new items ===")


def facebook_job():
    logger.info("=== Facebook job started ===")
    client = AirtableClient()
    dedup = Deduplicator(client)
    count = run_facebook_pipeline(client, dedup)
    logger.info(f"=== Facebook job done: {count} new items ===")


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="Asia/Ho_Chi_Minh")

    # RSS: every day at 7:00 AM
    scheduler.add_job(rss_job, "cron", hour=7, minute=0, id="rss_daily")

    # Facebook: Mon, Wed, Fri at 8:00 AM (save Apify credits)
    scheduler.add_job(facebook_job, "cron", day_of_week="mon,wed,fri", hour=8, minute=0, id="facebook_mwf")

    logger.info("Scheduler started — RSS: daily 7am | Facebook: Mon/Wed/Fri 8am")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped")
