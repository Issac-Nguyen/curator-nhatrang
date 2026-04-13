"""Direct Facebook scraper using Playwright.

Uses Facebook cookies to scrape page posts via headless browser.
Designed to run on GitHub Actions (Playwright pre-installed).
"""

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

# Webshare proxy API keys (free tier = 1GB/mo each; rotate on exhaustion).
WEBSHARE_API_KEYS = [k for k in [
    os.getenv("WEBSHARE_API_KEY", "").strip(),
    os.getenv("WEBSHARE_API_KEY_2", "").strip(),
] if k]


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


class DirectScrapeError(Exception):
    pass


def check_cookie_health() -> bool:
    """Quick check if Facebook cookies are still valid via HTTP request through proxy.

    Returns True if valid, False if expired. Sends Telegram alert on expiry.
    """
    if not FB_COOKIE_STRING:
        return False
    try:
        import requests as req
        import urllib.parse
        cookies = {}
        for part in FB_COOKIE_STRING.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = urllib.parse.unquote(v.strip())

        proxy_url = _get_proxy()
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}

        resp = req.get(
            "https://www.facebook.com/me",
            cookies=cookies,
            proxies=proxies,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=15,
            allow_redirects=False,
        )
        # If redirected to login → expired
        if resp.status_code in (301, 302) and "/login" in resp.headers.get("Location", ""):
            log.warning("[Direct] Facebook cookies EXPIRED — redirected to login")
            _send_cookie_alert()
            return False
        log.info("[Direct] Facebook cookies valid")
        return True
    except Exception as e:
        log.warning(f"[Direct] Cookie health check failed: {e}")
        return True  # Assume valid if check fails (don't block pipeline)


def _send_cookie_alert():
    """Send Telegram alert when cookies expire."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import requests as req
        req.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": "⚠️ Facebook cookies EXPIRED!\n\nDirect scraper sẽ không hoạt động cho đến khi re-login.\nCần mở browser → login Facebook → extract cookies mới.",
            },
            timeout=10,
        )
    except Exception:
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


def _get_proxy() -> str | None:
    """Fetch a proxy from Webshare.io API. Tries each key until one works.

    Rotation triggers when a key's bandwidth is exhausted: Webshare returns proxies
    but they 402 on use, OR the list API itself starts failing. We detect exhaustion
    by checking the subscription's bandwidth usage before returning a proxy.
    """
    if not WEBSHARE_API_KEYS:
        return None
    import requests as req
    for idx, key in enumerate(WEBSHARE_API_KEYS):
        try:
            # Check bandwidth usage vs limit — free tier = 1GB/mo.
            # If exhausted, proxy tunnel returns 402 (silent failure at browser level).
            sub = req.get(
                "https://proxy.webshare.io/api/v2/subscription/",
                headers={"Authorization": f"Token {key}"},
                timeout=10,
            )
            if sub.status_code == 200:
                sub_data = sub.json()
                if sub_data.get("throttled") or sub_data.get("paused"):
                    log.warning(f"[Direct] Webshare key #{idx+1} throttled/paused, rotating")
                    continue
                plan_id = sub_data.get("plan")
                if plan_id:
                    plan = req.get(
                        f"https://proxy.webshare.io/api/v2/subscription/plan/{plan_id}/",
                        headers={"Authorization": f"Token {key}"},
                        timeout=10,
                    )
                    stats = req.get(
                        "https://proxy.webshare.io/api/v2/stats/aggregate/?timespan=month",
                        headers={"Authorization": f"Token {key}"},
                        timeout=10,
                    )
                    if plan.status_code == 200 and stats.status_code == 200:
                        limit_gb = plan.json().get("bandwidth_limit", 0)  # GB
                        used_bytes = stats.json().get("bandwidth_total", 0)
                        used_gb = used_bytes / (1024 ** 3)
                        log.info(f"[Direct] Webshare key #{idx+1}: {used_gb:.2f}/{limit_gb:.2f} GB used")
                        if limit_gb > 0 and used_gb >= limit_gb * 0.98:
                            log.warning(f"[Direct] Webshare key #{idx+1} exhausted, rotating")
                            continue

            resp = req.get(
                "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page_size=10",
                headers={"Authorization": f"Token {key}"},
                timeout=10,
            )
            resp.raise_for_status()
            proxies = resp.json().get("results", [])
            if not proxies:
                log.warning(f"[Direct] Webshare key #{idx+1}: no proxies, rotating")
                continue
            proxy = next((p for p in proxies if p["country_code"] == "JP"), proxies[0])
            url = f"http://{proxy['username']}:{proxy['password']}@{proxy['proxy_address']}:{proxy['port']}"

            # Live-test proxy: Webshare bandwidth stats can be stale/misleading.
            # A 402 at actual CONNECT time means the key is really dead.
            try:
                test = req.get(
                    "https://httpbin.org/ip",
                    proxies={"http": url, "https": url},
                    timeout=10,
                )
                if test.status_code != 200:
                    log.warning(f"[Direct] Webshare key #{idx+1} proxy test failed: HTTP {test.status_code}, rotating")
                    continue
            except Exception as e:
                log.warning(f"[Direct] Webshare key #{idx+1} proxy test failed: {e}, rotating")
                continue

            if idx > 0:
                log.info(f"[Direct] Using Webshare key #{idx+1} (rotated)")
            return url
        except Exception as e:
            log.warning(f"[Direct] Webshare key #{idx+1} failed: {e}")
            continue
    log.warning("[Direct] All Webshare keys exhausted")
    return None


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

    proxy_server = _get_proxy()

    with sync_playwright() as p:
        launch_args = {"headless": True}
        if proxy_server:
            # Parse http://user:pass@host:port into Playwright proxy format
            import re as _re
            m = _re.match(r'https?://([^:]+):([^@]+)@([^:]+):(\d+)', proxy_server)
            if m:
                launch_args["proxy"] = {
                    "server": f"http://{m.group(3)}:{m.group(4)}",
                    "username": m.group(1),
                    "password": m.group(2),
                }
                log.info(f"[Direct] Using proxy: {m.group(3)}:{m.group(4)}")
            else:
                launch_args["proxy"] = {"server": proxy_server}
                log.info(f"[Direct] Using proxy: {proxy_server}")

        browser = p.chromium.launch(**launch_args)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="vi-VN",
            viewport={"width": 1280, "height": 900},
        )
        context.add_cookies(cookies)

        # Block bandwidth-heavy resources (images/video/fonts) to conserve Webshare 1GB/mo quota.
        # Keep stylesheets (needed for offsetHeight layout) and scripts (FB SPA requires JS).
        def _block_heavy(route):
            if route.request.resource_type in ("image", "media", "font"):
                route.abort()
            else:
                route.continue_()
        context.route("**/*", _block_heavy)

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

            # Extract posts using feed structure
            # Facebook wraps each post in a container with role="article"
            # or in feed items. We look for the feed and extract per-post.
            raw_posts = page.evaluate("""() => {
                const results = [];

                // Strategy: find the feed container, then iterate post blocks.
                // Each post block has a timestamp link that contains the real post URL.
                // The post text is in div[dir="auto"] within that block.
                // We anchor on timestamp links to identify individual posts.

                // Strategy: find all div[dir="auto"] text blocks with substantial content,
                // then for each, walk UP to find its post container and extract the
                // post URL from a timestamp/permalink link WITHIN that container.

                const allDivs = document.querySelectorAll('div[dir="auto"]');
                const seenTextKeys = new Set();
                const seenUrls = new Set();

                for (const div of allDivs) {
                    const rawText = div.innerText?.trim();
                    if (!rawText || rawText.length < 30) continue;

                    // Skip known UI patterns
                    const lower = rawText.toLowerCase();
                    if (lower.startsWith('write a') || lower.startsWith('like') ||
                        lower.startsWith('comment') || lower.startsWith('share') ||
                        lower.startsWith('all reactions') || lower.startsWith('most relevant') ||
                        lower.startsWith('all comments') || lower.includes(' is at ') ||
                        lower.startsWith('see translation') || rawText.length > 5000) continue;

                    // Dedup by first 50 chars
                    const textKey = rawText.substring(0, 50);
                    if (seenTextKeys.has(textKey)) continue;

                    // Clean text
                    let postText = rawText
                        .replace(/\\n… See more$/, '').replace(/… See more$/, '')
                        .replace(/\\n… Xem thêm$/, '').replace(/… Xem thêm$/, '');

                    // Walk UP to find post container (look for a large block with links)
                    let postContainer = null;
                    for (let p = div.parentElement; p && p !== document.body; p = p.parentElement) {
                        // A post container typically:
                        // - Has height > 200px
                        // - Contains a link to a specific post (not nav links)
                        const postLink = p.querySelector(
                            'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"], ' +
                            'a[href*="/photo/?fbid="], a[href*="/videos/"]'
                        );
                        if (postLink && p.offsetHeight > 200) {
                            postContainer = p;
                            break;
                        }
                    }

                    // Extract URL from post-specific links WITHIN the container
                    let url = '';
                    if (postContainer) {
                        // Priority order: posts/ > permalink > story_fbid > photo > videos
                        const urlSelectors = [
                            'a[href*="/posts/"]',
                            'a[href*="/permalink/"]',
                            'a[href*="story_fbid"]',
                            'a[href*="/photo/?fbid="]',
                            'a[href*="/videos/"]',
                        ];
                        for (const sel of urlSelectors) {
                            const link = postContainer.querySelector(sel);
                            if (link && link.href) {
                                // Verify it's a real post link, not a nav link
                                const h = link.href;
                                if (h.includes('fbid=') || h.includes('/posts/') ||
                                    h.includes('/permalink/') || h.includes('story_fbid') ||
                                    h.includes('/videos/')) {
                                    url = h;
                                    break;
                                }
                            }
                        }
                    }

                    // Skip if no valid post URL found
                    if (!url) continue;
                    if (seenUrls.has(url)) continue;

                    // Extract image from container.
                    // Images are blocked at network level (bandwidth savings), so naturalWidth=0.
                    // Filter by URL heuristics instead: FB small thumbnails use p*x* size hints in URL.
                    let image = '';
                    if (postContainer) {
                        const imgs = postContainer.querySelectorAll('img[src*="scontent"]');
                        for (const img of imgs) {
                            const src = img.src || '';
                            // Skip tiny avatars / reaction icons (usually p40x40, p60x60, etc.)
                            if (/\\/p\\d{2,3}x\\d{2,3}\\//.test(src)) continue;
                            image = src;
                            break;
                        }
                    }

                    seenTextKeys.add(textKey);
                    seenUrls.add(url);
                    results.push({
                        text: postText.substring(0, 2000),
                        url: url,
                        image: image,
                    });
                }

                return results;
            }""")

        finally:
            browser.close()

    # Normalize and deduplicate
    posts = []
    seen_texts = set()
    for raw in raw_posts:
        text = raw.get("text", "").strip()
        if not text:
            continue

        # Dedup by text similarity: skip if we already have a post
        # whose text starts with the same 50 chars
        text_key = text[:50]
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)

        url = _clean_url(raw.get("url", ""))
        if not url:
            continue

        posts.append({
            "title": text[:100],
            "content": text,
            "url": url,
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
    """Clean Facebook post URL — remove tracking params."""
    if not url:
        return ""
    url = re.sub(r'[?&]__cft__\[0\]=[^&]*', '', url)
    url = re.sub(r'[?&]__tn__=[^&]*', '', url)
    url = re.sub(r'[?&]mibextid=[^&]*', '', url)
    # Clean trailing ? or &
    url = re.sub(r'[?&]$', '', url)
    return url


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Test with multiple source types
    test_sources = [
        ("https://www.facebook.com/VinWondersNhaTrang", "VinWonders"),
        ("https://www.facebook.com/groups/anvatnhatrang", "Hội Ăn Vặt NT"),
    ]
    for url, name in test_sources:
        print(f"\n{'='*60}")
        print(f"Testing: {name}")
        print(f"{'='*60}")
        posts = scrape_page_posts(url, source_id="test", source_name=name, max_posts=5)
        for p in posts:
            print(f"\n  Title: {p['title'][:80]}")
            print(f"  URL: {p['url'][:100]}")
            print(f"  Image: {'Yes' if p['source_image_url'] else 'No'}")
            print(f"  Content: {len(p['content'])} chars")
