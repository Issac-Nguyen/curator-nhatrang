import logging
import sys
from time import sleep

from airtable_client import AirtableClient
from apify_fetcher import ApifyFetcher, ApifyRunError
from deduplicator import Deduplicator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


SOURCES_PER_RUN = 3  # round-robin: scrape N oldest-checked sources per run


def run_facebook_pipeline(client: AirtableClient, dedup: Deduplicator) -> int:
    sources = client.get_active_sources(type_filter="Facebook", limit=SOURCES_PER_RUN)
    if not sources:
        log.info("No active Facebook sources found")
        return 0

    fetcher = ApifyFetcher()
    remaining = fetcher.check_credit_balance()
    if remaining < 0.5:
        log.critical(f"Apify credit critically low (${remaining:.2f}), skipping Facebook pipeline")
        return 0

    total_new = 0
    for source in sources:
        try:
            items = fetcher.run_actor(
                source["URL"],
                source["id"],
                source["Name"],
            )
            new_items = dedup.filter_new_items(items)
            # Skip items with empty content
            filtered = [i for i in new_items if i.get("content", "").strip()]
            skipped = len(new_items) - len(filtered)
            if skipped:
                log.info(f"  Skipped {skipped} items with empty content from {source['Name']}")
            if filtered:
                client.create_raw_items_batch(filtered)
                for item in filtered:
                    dedup.add_url(item["url"])
            total_new += len(filtered)
            client.update_source_last_checked(source["id"])
            sleep(2)  # avoid spamming Apify
        except ApifyRunError as e:
            log.error(f"Apify failed for {source['Name']}: {e}")
            continue

    return total_new


def main():
    log.info("=== Scraper started ===")
    client = AirtableClient()
    dedup = Deduplicator(client)

    fb_count = run_facebook_pipeline(client, dedup)
    log.info(f"Facebook: {fb_count} new items")

    log.info(f"=== Done: {fb_count} total new items ===")


if __name__ == "__main__":
    main()
