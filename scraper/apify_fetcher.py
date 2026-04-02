import logging
import os
import time
from datetime import datetime, timezone

import cloudinary
import cloudinary.uploader
import requests
from dotenv import load_dotenv
from pathlib import Path

from og_image import extract_og_image

load_dotenv(Path(__file__).parent.parent / ".env")
log = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

APIFY_TOKENS = [t for t in [os.getenv("APIFY_TOKEN"), os.getenv("APIFY_TOKEN_2")] if t]
ACTOR_ID = "apify~facebook-posts-scraper"
BASE_URL = "https://api.apify.com/v2"
POLL_INTERVAL = 5   # seconds between status checks
RUN_TIMEOUT = 120   # max seconds to wait for a run
RATE_LIMIT_SLEEP = 30  # seconds to sleep on 429


class ApifyRunError(Exception):
    pass


class ApifyFetcher:
    def __init__(self):
        if not APIFY_TOKENS:
            raise RuntimeError("APIFY_TOKEN not set in .env")
        self._token_index = 0
        self.headers = {"Authorization": f"Bearer {APIFY_TOKENS[0]}"}

    def _rotate_token(self) -> bool:
        """Switch to next Apify token. Returns True if rotated, False if no more."""
        self._token_index += 1
        if self._token_index >= len(APIFY_TOKENS):
            self._token_index = 0
            return False
        self.headers = {"Authorization": f"Bearer {APIFY_TOKENS[self._token_index]}"}
        log.info(f"Rotated to Apify token {self._token_index + 1}/{len(APIFY_TOKENS)}")
        return True

    def _request(self, method: str, url: str, **kwargs) -> dict:
        resp = requests.request(method, url, headers=self.headers, **kwargs)
        if resp.status_code == 429:
            log.warning(f"Apify rate limit, sleeping {RATE_LIMIT_SLEEP}s")
            time.sleep(RATE_LIMIT_SLEEP)
            resp = requests.request(method, url, headers=self.headers, **kwargs)
        if resp.status_code == 403 and self._rotate_token():
            resp = requests.request(method, url, headers=self.headers, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def check_credit_balance(self) -> float:
        """Log current credit balance. Returns remaining USD."""
        try:
            data = self._request("GET", f"{BASE_URL}/users/me")
            plan = data.get("data", {}).get("plan", {})
            balance = plan.get("monthlyUsage", {}).get("ACTOR_COMPUTE_UNITS", 0)
            limit = plan.get("monthlyUsageCreditsUsd", 5.0)
            # Rough estimate: 1 CU ≈ $0.005
            used_usd = balance * 0.005
            remaining = max(0, limit - used_usd)
            log.info(f"Apify credit: ~${remaining:.2f} remaining of ${limit:.2f}/month")
            if remaining < 1.0:
                log.warning(f"Apify credit LOW: only ~${remaining:.2f} remaining!")
            return remaining
        except Exception as e:
            log.error(f"Could not check credit balance: {e}")
            return 0.0

    def run_actor(self, facebook_url: str, source_id: str, source_name: str) -> list[dict]:
        """
        Run facebook-pages-scraper actor and return normalized items.
        Raises ApifyRunError on failure or timeout.
        """
        log.info(f"Running Apify actor for: {source_name} ({facebook_url})")

        # 1. Start the run
        run_data = self._request(
            "POST",
            f"{BASE_URL}/acts/{ACTOR_ID}/runs",
            json={
                "startUrls": [{"url": facebook_url}],
                "resultsLimit": 10,
            },
        )
        run_id = run_data.get("data", {}).get("id")
        if not run_id:
            raise ApifyRunError(f"No run_id returned for {source_name}")
        log.info(f"Actor run started: {run_id}")

        # 2. Poll until done
        elapsed = 0
        while elapsed < RUN_TIMEOUT:
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            status_data = self._request("GET", f"{BASE_URL}/actor-runs/{run_id}")
            status = status_data.get("data", {}).get("status")
            log.debug(f"Run {run_id} status: {status} ({elapsed}s)")
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise ApifyRunError(f"Actor run {run_id} ended with status: {status}")
        else:
            raise ApifyRunError(f"Actor run {run_id} timed out after {RUN_TIMEOUT}s")

        # 3. Fetch dataset items
        items_data = self._request("GET", f"{BASE_URL}/actor-runs/{run_id}/dataset/items")
        posts = items_data if isinstance(items_data, list) else items_data.get("items", [])
        log.info(f"Actor returned {len(posts)} posts for {source_name}")

        # 4. Normalize to standard format
        return [self._normalize(post, source_id, source_name) for post in posts if self._get_url(post)]

    def _get_url(self, post: dict) -> str | None:
        return post.get("url") or post.get("postUrl") or post.get("link")

    @staticmethod
    def _persist_image(url: str) -> str | None:
        """Download image first (bypass CDN blocks), then upload bytes to Cloudinary."""
        try:
            resp = requests.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://www.facebook.com/",
                },
            )
            resp.raise_for_status()
            result = cloudinary.uploader.upload(
                resp.content, folder="nhatrang/sources", overwrite=False, resource_type="image",
            )
            return result["secure_url"]
        except Exception as e:
            log.warning(f"Failed to persist image to Cloudinary: {e}")
            return None

    def _normalize(self, post: dict, source_id: str, source_name: str) -> dict:
        text = post.get("text") or post.get("message") or post.get("body") or ""
        raw_date = post.get("time") or post.get("date") or post.get("created_time")
        published_date = None
        if raw_date:
            try:
                if isinstance(raw_date, (int, float)):
                    published_date = datetime.fromtimestamp(raw_date, tz=timezone.utc).isoformat()
                else:
                    published_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).isoformat()
            except Exception:
                published_date = datetime.now(timezone.utc).isoformat()

        source_image_url = (
            post.get("imageUrl")
            or post.get("fullPicture")
            or post.get("picture")
        )

        # Extract from media array (Apify facebook-posts-scraper format)
        if not source_image_url:
            media = post.get("media")
            if media and isinstance(media, list) and media:
                first = media[0]
                source_image_url = (
                    first.get("thumbnail")
                    or (first.get("thumbnailImage") or {}).get("uri")
                )

        # Extract from preferred_thumbnail (another Apify field)
        if not source_image_url:
            pref = post.get("preferred_thumbnail")
            if pref:
                source_image_url = (pref.get("image") or {}).get("uri")

        # Fallback: extract og:image from post URL
        if not source_image_url:
            post_url = self._get_url(post)
            if post_url:
                source_image_url = extract_og_image(post_url)

        # Upload to Cloudinary immediately (fbcdn URLs expire in hours)
        if source_image_url:
            source_image_url = self._persist_image(source_image_url)

        return {
            "title": text[:100].strip() if text else "",
            "content": text.strip(),
            "url": self._get_url(post),
            "published_date": published_date,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source_name": source_name,
            "source_id": source_id,
            "fetcher_type": "facebook",
            "source_image_url": source_image_url,
        }
