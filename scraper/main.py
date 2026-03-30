import logging
import sys
from time import sleep

from airtable_client import AirtableClient
from apify_fetcher import ApifyFetcher, ApifyRunError
from deduplicator import Deduplicator
import rss_fetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run_rss_pipeline(client: AirtableClient, dedup: Deduplicator) -> int:
    sources = client.get_active_sources(type_filter="RSS")
    if not sources:
        log.info("No active RSS sources found")
        return 0

    all_items = []
    for source in sources:
        items = rss_fetcher.fetch(source)
        new_items = dedup.filter_new_items(items)
        all_items.extend(new_items)

    if all_items:
        client.create_raw_items_batch(all_items)
        for item in all_items:
            dedup.add_url(item["url"])

    return len(all_items)


def run_facebook_pipeline(client: AirtableClient, dedup: Deduplicator) -> int:
    sources = client.get_active_sources(type_filter="Facebook")
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
            if new_items:
                client.create_raw_items_batch(new_items)
                for item in new_items:
                    dedup.add_url(item["url"])
            total_new += len(new_items)
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

    rss_count = run_rss_pipeline(client, dedup)
    log.info(f"RSS: {rss_count} new items")

    fb_count = run_facebook_pipeline(client, dedup)
    log.info(f"Facebook: {fb_count} new items")

    log.info(f"=== Done: {rss_count + fb_count} total new items ===")


if __name__ == "__main__":
    main()
