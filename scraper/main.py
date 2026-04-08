import logging
import sys
from time import sleep

from airtable_client import AirtableClient
from apify_fetcher import ApifyFetcher, ApifyRunError
from deduplicator import Deduplicator
from tier_scheduler import get_eligible_sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


SOURCES_PER_RUN = 3


def run_facebook_pipeline(client: AirtableClient, dedup: Deduplicator) -> dict:
    """Run Facebook scraping with tier-based source selection.

    Returns dict with: new_items, stats (tier info for notifications).
    """
    # Load all active Facebook sources (no limit — tier scheduler will filter)
    all_sources = client.get_active_sources(type_filter="Facebook")
    if not all_sources:
        log.info("No active Facebook sources found")
        return {"new_items": 0, "stats": None}

    # Get latest post dates for tier assignment
    latest_dates = client.get_latest_post_dates()

    # Select eligible sources based on tiers
    sources, stats = get_eligible_sources(all_sources, latest_dates, limit=SOURCES_PER_RUN)
    if not sources:
        log.info("No sources due for scraping this run")
        return {"new_items": 0, "stats": stats}

    fetcher = ApifyFetcher()
    remaining = fetcher.check_credit_balance()
    if remaining < 0.5:
        log.critical(f"Apify credit critically low (${remaining:.2f}), skipping Facebook pipeline")
        return {"new_items": 0, "stats": stats}

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

    return {"new_items": total_new, "stats": stats}


def main():
    log.info("=== Scraper started ===")
    client = AirtableClient()
    dedup = Deduplicator(client)

    result = run_facebook_pipeline(client, dedup)
    fb_count = result["new_items"]
    stats = result["stats"]

    if stats:
        tiers = stats["tier_counts"]
        log.info(
            f"Facebook: {fb_count} new items | "
            f"Tiers: HOT={tiers['HOT']} WARM={tiers['WARM']} COLD={tiers['COLD']} NEW={tiers['NEW']} | "
            f"Eligible: {stats['eligible_count']} | Scraped: {stats['selected_count']}"
        )
    else:
        log.info(f"Facebook: {fb_count} new items")

    log.info(f"=== Done: {fb_count} total new items ===")


if __name__ == "__main__":
    main()
