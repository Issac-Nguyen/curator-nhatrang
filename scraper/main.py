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


def _init_providers() -> list[tuple[str, object]]:
    """Initialize available scraping providers in priority order.

    Returns list of (name, fetcher) tuples. Skips providers that aren't configured.
    """
    providers = []

    # Apify (primary)
    try:
        fetcher = ApifyFetcher()
        remaining = fetcher.check_credit_balance()
        if remaining >= 0.5:
            providers.append(("Apify", fetcher))
        else:
            log.warning(f"Apify credit low (${remaining:.2f}), skipping")
    except Exception as e:
        log.warning(f"Apify not available: {e}")

    # Direct scraper via Playwright + Facebook cookies (fallback)
    try:
        from fb_direct_scraper import FB_COOKIE_STRING, check_cookie_health
        if FB_COOKIE_STRING:
            if check_cookie_health():
                providers.append(("Direct", _DirectProvider()))
            else:
                log.warning("Direct scraper skipped: Facebook cookies expired (Telegram alert sent)")
        else:
            log.info("Direct scraper not available: FACEBOOK_COOKIES not set")
    except Exception as e:
        log.info(f"Direct scraper not available: {e}")

    return providers


class _DirectProvider:
    """Wrapper to match the run_actor() interface for fb_direct_scraper."""

    def run_actor(self, facebook_url: str, source_id: str, source_name: str) -> list[dict]:
        from fb_direct_scraper import scrape_page_posts
        return scrape_page_posts(facebook_url, source_id, source_name, max_posts=10)


def _fetch_with_fallback(providers: list, facebook_url: str, source_id: str, source_name: str) -> list[dict]:
    """Try each provider in order until one succeeds.

    Returns list of normalized post items. Raises if all providers fail.
    """
    last_error = None
    for name, fetcher in providers:
        try:
            items = fetcher.run_actor(facebook_url, source_id, source_name)
            log.info(f"  [{name}] Got {len(items)} items from {source_name}")
            return items
        except Exception as e:
            log.warning(f"  [{name}] Failed for {source_name}: {e}")
            last_error = e
            continue

    raise ApifyRunError(f"All providers failed for {source_name}: {last_error}")


def run_facebook_pipeline(client: AirtableClient, dedup: Deduplicator) -> dict:
    """Run Facebook scraping with tier-based source selection and multi-provider fallback.

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

    # Init providers (Apify → PhantomBuster)
    providers = _init_providers()
    if not providers:
        log.critical("No scraping providers available")
        return {"new_items": 0, "stats": stats}

    provider_names = [name for name, _ in providers]
    log.info(f"Active providers: {', '.join(provider_names)}")

    total_new = 0
    providers_used = []
    for source in sources:
        try:
            items = _fetch_with_fallback(providers, source["URL"], source["id"], source["Name"])
            new_items = dedup.filter_new_items(items)
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
            sleep(2)
        except ApifyRunError as e:
            log.error(f"All providers failed for {source['Name']}: {e}")
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
