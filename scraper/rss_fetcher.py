import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser

log = logging.getLogger(__name__)


def _parse_date(entry) -> str | None:
    """Parse published date from feed entry, return ISO string or None."""
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                dt = datetime(*val[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    # Fallback to string parsing
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return parsedate_to_datetime(val).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def fetch(source: dict) -> list[dict]:
    """
    Fetch up to 10 most recent entries from an RSS source.
    Returns list of normalized item dicts.
    """
    url = source.get("URL", "")
    source_id = source.get("id", "")
    source_name = source.get("Name", "")

    if not url:
        log.warning(f"Source '{source_name}' has no URL, skipping")
        return []

    log.info(f"Fetching RSS: {source_name} ({url})")
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        log.warning(f"Failed to fetch RSS {url}: {e}")
        return []

    if feed.bozo and not feed.entries:
        log.warning(f"RSS feed error for {source_name}: {feed.bozo_exception}")
        return []

    items = []
    for entry in feed.entries[:10]:
        entry_url = getattr(entry, "link", None)
        if not entry_url:
            log.debug(f"Skipping entry without URL in {source_name}")
            continue

        title = getattr(entry, "title", "") or ""
        content = (
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
            or ""
        )
        # Some feeds put full content in content[0].value
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", content)

        # Extract image URL from various feed fields
        image_url = None
        enclosures = getattr(entry, "enclosures", None)
        if enclosures:
            for enc in enclosures:
                if enc.get("type", "").startswith("image/"):
                    image_url = enc.get("href") or enc.get("url")
                    break
        if not image_url:
            media_content = getattr(entry, "media_content", None)
            if media_content:
                for mc in media_content:
                    if mc.get("medium") == "image" or mc.get("type", "").startswith("image/"):
                        image_url = mc.get("url")
                        break
        if not image_url:
            links = getattr(entry, "links", None)
            if links:
                for link in links:
                    if link.get("type", "").startswith("image/"):
                        image_url = link.get("href") or link.get("url")
                        break

        items.append({
            "title": title.strip(),
            "content": content.strip(),
            "url": entry_url.strip(),
            "published_date": _parse_date(entry),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source_name": source_name,
            "source_id": source_id,
            "fetcher_type": "rss",
            "source_image_url": image_url,
        })

    log.info(f"RSS {source_name}: fetched {len(items)} entries")
    return items
