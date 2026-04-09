"""Direct Facebook scraper using Playwright.

Uses Facebook cookies to scrape page posts via headless browser.
Designed to run on GitHub Actions (Playwright pre-installed).
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=False)
log = logging.getLogger(__name__)

# Cookie string from env: "c_user=XXX; xs=YYY; fr=ZZZ; datr=WWW"
FB_COOKIE_STRING = os.getenv("FACEBOOK_COOKIES", "")


class DirectScrapeError(Exception):
    pass


def _parse_cookies(cookie_str: str) -> list[dict]:
    """Parse cookie string into Playwright cookie format."""
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": ".facebook.com",
            "path": "/",
        })
    return cookies


def scrape_page_posts(page_url: str, source_id: str, source_name: str, max_posts: int = 10) -> list[dict]:
    """Scrape posts from a Facebook page using Playwright.

    Args:
        page_url: Facebook page URL (e.g. https://facebook.com/VinWondersNhaTrang)
        source_id: Airtable source record ID
        source_name: Display name for logging
        max_posts: Max posts to return

    Returns:
        List of normalized post dicts (same format as ApifyFetcher).
    """
    if not FB_COOKIE_STRING:
        raise DirectScrapeError("FACEBOOK_COOKIES not set in env")

    from playwright.sync_api import sync_playwright

    cookies = _parse_cookies(FB_COOKIE_STRING)
    if not cookies:
        raise DirectScrapeError("No valid cookies parsed from FACEBOOK_COOKIES")

    log.info(f"[Direct] Scraping: {source_name} ({page_url})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="vi-VN",
            viewport={"width": 1280, "height": 900},
        )
        context.add_cookies(cookies)

        page = context.new_page()
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)

            # Check if redirected to login
            if "/login" in page.url:
                raise DirectScrapeError("Cookies expired — redirected to login")

            # Scroll to load posts
            for _ in range(5):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(2000)

            # Extract posts from rendered DOM
            raw_posts = page.evaluate("""() => {
                const results = [];
                const seen = new Set();
                const allDivs = document.querySelectorAll('div[dir="auto"]');

                for (const div of allDivs) {
                    const text = div.innerText?.trim();
                    if (!text || text.length < 30 || seen.has(text)) continue;
                    // Skip UI elements
                    if (text.startsWith('Write a comment') || text.startsWith('Like') || text.length > 5000) continue;
                    seen.add(text);

                    // Clean "See more" suffix
                    const cleanText = text.replace(/\\n… See more$/, '').replace(/… See more$/, '');

                    // Find post URL by walking up
                    let url = '';
                    for (let p = div; p && p !== document.body; p = p.parentElement) {
                        const link = p.querySelector('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"], a[href*="/reel/"], a[href*="/photo"]');
                        if (link) { url = link.href; break; }
                    }

                    // Find image
                    let image = '';
                    for (let p = div; p && p !== document.body; p = p.parentElement) {
                        const img = p.querySelector('img[src*="scontent"]');
                        if (img && img.naturalWidth > 100) { image = img.src; break; }
                    }

                    // Find timestamp text
                    let timeText = '';
                    for (let p = div; p && p !== document.body; p = p.parentElement) {
                        const timeEl = p.querySelector('a[role="link"] span[id]');
                        if (timeEl) { timeText = timeEl.innerText; break; }
                    }

                    results.push({ text: cleanText, url, image, timeText });
                }
                return results;
            }""")

        finally:
            browser.close()

    # Normalize to standard format
    posts = []
    seen_texts = set()
    for raw in raw_posts:
        text = raw.get("text", "").strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)

        posts.append({
            "title": text[:100],
            "content": text,
            "url": _clean_url(raw.get("url", "")),
            "published_date": datetime.now(timezone.utc).isoformat(),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source_name": source_name,
            "source_id": source_id,
            "fetcher_type": "facebook",
            "source_image_url": raw.get("image", "") or None,
        })
        if len(posts) >= max_posts:
            break

    log.info(f"[Direct] Got {len(posts)} posts from {source_name}")
    return posts


def _clean_url(url: str) -> str:
    """Remove tracking params from Facebook URLs."""
    if not url:
        return ""
    # Remove __cft__ and other tracking
    url = re.sub(r'[?&]__cft__\[0\]=[^&]*', '', url)
    url = re.sub(r'[?&]__tn__=[^&]*', '', url)
    return url


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    posts = scrape_page_posts(
        "https://www.facebook.com/VinWondersNhaTrang",
        source_id="test",
        source_name="VinWonders Nha Trang",
        max_posts=5,
    )
    for p in posts:
        print(f"\n--- Post ---")
        print(f"Title: {p['title']}")
        print(f"URL: {p['url']}")
        print(f"Image: {p['source_image_url'][:80] if p['source_image_url'] else 'None'}")
