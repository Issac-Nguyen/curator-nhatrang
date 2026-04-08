"""Tier-based source scheduling.

Assigns each source a tier (HOT/WARM/COLD/NEW) based on latest post date,
then filters to sources whose Last checked exceeds their tier's interval.
"""

import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

# Hours between scrapes per tier
TIER_INTERVALS = {
    "HOT": 4,      # post within 7 days → scrape every 4h
    "WARM": 24,     # post within 30 days → scrape every 24h
    "COLD": 168,    # post older than 30 days → scrape every 7 days
    "NEW": 0,       # no data yet → scrape immediately
}


def assign_tier(source_id: str, latest_post_dates: dict[str, str], now: datetime = None) -> str:
    """Assign a tier to a source based on its latest post date.

    Args:
        source_id: Airtable record ID of the source.
        latest_post_dates: {source_id: ISO date string} from AirtableClient.
        now: Current time (injectable for testing).

    Returns:
        One of "HOT", "WARM", "COLD", "NEW".
    """
    if now is None:
        now = datetime.now(timezone.utc)

    latest = latest_post_dates.get(source_id)
    if not latest:
        return "NEW"

    try:
        post_dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        if post_dt.tzinfo is None:
            post_dt = post_dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return "NEW"

    age = now - post_dt

    if age <= timedelta(days=7):
        return "HOT"
    elif age <= timedelta(days=30):
        return "WARM"
    else:
        return "COLD"


def is_eligible(source: dict, tier: str, now: datetime = None) -> bool:
    """Check if a source is due for scraping based on its tier interval.

    Args:
        source: Airtable source record with "Last checked" field.
        tier: The source's assigned tier.
        now: Current time (injectable for testing).

    Returns:
        True if enough time has passed since last check.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    interval_hours = TIER_INTERVALS[tier]

    # NEW sources are always eligible
    if interval_hours == 0:
        return True

    last_checked = source.get("Last checked", "")
    if not last_checked:
        return True

    try:
        checked_dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
        if checked_dt.tzinfo is None:
            checked_dt = checked_dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return True

    elapsed = now - checked_dt
    return elapsed >= timedelta(hours=interval_hours)


def get_eligible_sources(
    all_sources: list[dict],
    latest_post_dates: dict[str, str],
    limit: int = 3,
) -> tuple[list[dict], dict]:
    """Select sources eligible for scraping, prioritized by tier and staleness.

    Args:
        all_sources: All active Facebook sources from Airtable.
        latest_post_dates: {source_id: ISO date} from get_latest_post_dates().
        limit: Max sources to return.

    Returns:
        (eligible_sources, stats_dict) where stats_dict contains tier counts.
    """
    now = datetime.now(timezone.utc)

    tier_counts = {"HOT": 0, "WARM": 0, "COLD": 0, "NEW": 0}
    eligible = []

    for source in all_sources:
        tier = assign_tier(source["id"], latest_post_dates, now)
        tier_counts[tier] += 1

        if is_eligible(source, tier, now):
            eligible.append((source, tier))

    # Sort: NEW first, then HOT, WARM, COLD. Within same tier, oldest checked first.
    tier_priority = {"NEW": 0, "HOT": 1, "WARM": 2, "COLD": 3}
    eligible.sort(key=lambda x: (
        tier_priority[x[1]],
        x[0].get("Last checked", ""),
    ))

    selected = [s for s, _ in eligible[:limit]]
    selected_tiers = [t for _, t in eligible[:limit]]

    log.info(
        f"Tier breakdown: {tier_counts} | "
        f"Eligible: {len(eligible)} | Selected: {len(selected)} "
        f"({', '.join(selected_tiers) if selected_tiers else 'none'})"
    )

    stats = {
        "tier_counts": tier_counts,
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "selected_tiers": selected_tiers,
    }
    return selected, stats
