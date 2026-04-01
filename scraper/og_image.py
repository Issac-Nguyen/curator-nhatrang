"""Extract og:image from article URLs."""
import logging
import re

import requests

log = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; NhaTrangCurator/1.0)"


def extract_og_image(url: str) -> str | None:
    """
    Fetch URL and extract <meta property="og:image" content="..."> value.
    Returns image URL or None. Never raises — logs warnings on failure.
    """
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        # Try both attribute orders: property then content, or content then property
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']',
            resp.text[:50000],
        )
        if not match:
            match = re.search(
                r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:image["\']',
                resp.text[:50000],
            )
        if match:
            img_url = match.group(1).strip()
            if img_url.startswith("http"):
                log.debug(f"  og:image found: {img_url[:80]}...")
                return img_url
        return None
    except Exception as e:
        log.debug(f"  og:image extraction failed for {url[:60]}: {e}")
        return None
