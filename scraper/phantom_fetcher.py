"""PhantomBuster Facebook Page Posts fetcher.

Requires a "Facebook Page Posts Extractor" phantom set up on each account.
Agent IDs and API keys configured in .env.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import cloudinary
import cloudinary.uploader
import requests
from dotenv import load_dotenv

from og_image import extract_og_image

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=False)
log = logging.getLogger(__name__)

BASE_URL = "https://api.phantombuster.com/api/v2"
POLL_INTERVAL = 5
RUN_TIMEOUT = 120

# Load keys + agent IDs from env
PHANTOM_KEYS = [
    k for k in [
        os.getenv("PHANTOMBUSTER_API_KEY"),
        os.getenv("PHANTOMBUSTER_API_KEY_2"),
    ] if k
]
PHANTOM_AGENT_IDS = [
    a for a in [
        os.getenv("PHANTOMBUSTER_AGENT_ID"),
        os.getenv("PHANTOMBUSTER_AGENT_ID_2"),
    ] if a
]


class PhantomRunError(Exception):
    pass


class PhantomFetcher:
    def __init__(self):
        if not PHANTOM_KEYS or not PHANTOM_AGENT_IDS:
            raise RuntimeError("PHANTOMBUSTER_API_KEY and PHANTOMBUSTER_AGENT_ID must be set in .env")
        self._key_index = 0

    def _headers(self) -> dict:
        return {
            "X-Phantombuster-Key": PHANTOM_KEYS[self._key_index],
            "Content-Type": "application/json",
        }

    def _rotate_key(self) -> bool:
        """Switch to next key+agent pair. Returns True if rotated."""
        self._key_index += 1
        if self._key_index >= min(len(PHANTOM_KEYS), len(PHANTOM_AGENT_IDS)):
            self._key_index = 0
            return False
        log.info(f"Rotated to PhantomBuster key {self._key_index + 1}")
        return True

    @property
    def _agent_id(self) -> str:
        return PHANTOM_AGENT_IDS[self._key_index]

    def is_available(self) -> bool:
        """Check if PhantomBuster is configured and accessible."""
        if not PHANTOM_KEYS or not PHANTOM_AGENT_IDS:
            return False
        try:
            resp = requests.get(
                f"{BASE_URL}/agents/fetch?id={self._agent_id}",
                headers=self._headers(),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def run_actor(self, facebook_url: str, source_id: str, source_name: str) -> list[dict]:
        """
        Launch PhantomBuster agent for a Facebook page URL.
        Raises PhantomRunError on failure.
        """
        log.info(f"Running PhantomBuster for: {source_name} ({facebook_url})")

        # Try current key, then rotate on failure
        for attempt in range(min(len(PHANTOM_KEYS), len(PHANTOM_AGENT_IDS))):
            try:
                return self._run_with_current_key(facebook_url, source_id, source_name)
            except PhantomRunError as e:
                if "403" in str(e) or "401" in str(e):
                    if self._rotate_key():
                        continue
                raise
        raise PhantomRunError(f"All PhantomBuster keys exhausted for {source_name}")

    def _run_with_current_key(self, facebook_url: str, source_id: str, source_name: str) -> list[dict]:
        """Run with the current key+agent pair."""
        # 1. Launch the agent with arguments
        launch_resp = requests.post(
            f"{BASE_URL}/agents/launch",
            headers=self._headers(),
            json={
                "id": self._agent_id,
                "argument": json.dumps({
                    "spreadsheetUrl": facebook_url,
                    "numberofPostsperLaunch": 10,
                }),
            },
            timeout=30,
        )
        if launch_resp.status_code != 200:
            raise PhantomRunError(
                f"PhantomBuster launch failed ({launch_resp.status_code}): {launch_resp.text[:200]}"
            )
        container_id = launch_resp.json().get("containerId")
        if not container_id:
            raise PhantomRunError("No containerId returned from PhantomBuster")
        log.info(f"PhantomBuster launched container: {container_id}")

        # 2. Poll until done
        elapsed = 0
        while elapsed < RUN_TIMEOUT:
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            status_resp = requests.get(
                f"{BASE_URL}/agents/fetch-output?id={self._agent_id}",
                headers=self._headers(),
                timeout=10,
            )
            if status_resp.status_code != 200:
                continue
            output = status_resp.json()
            status = output.get("status")
            if status == "finished":
                break
            if status in ("error", "stopped"):
                raise PhantomRunError(f"PhantomBuster run ended with status: {status}")
        else:
            raise PhantomRunError(f"PhantomBuster timed out after {RUN_TIMEOUT}s")

        # 3. Fetch result data
        result_url = output.get("resultObject")
        if not result_url:
            log.warning(f"PhantomBuster returned no resultObject for {source_name}")
            return []

        try:
            result_resp = requests.get(result_url, timeout=15)
            result_resp.raise_for_status()
            posts = result_resp.json()
            if not isinstance(posts, list):
                posts = [posts]
        except Exception as e:
            log.warning(f"Failed to fetch PhantomBuster results: {e}")
            return []

        log.info(f"PhantomBuster returned {len(posts)} posts for {source_name}")
        return [self._normalize(post, source_id, source_name) for post in posts if self._get_url(post)]

    def _get_url(self, post: dict) -> str | None:
        return post.get("postUrl") or post.get("url") or post.get("link")

    @staticmethod
    def _persist_image(url: str) -> str | None:
        """Upload image to Cloudinary (same as ApifyFetcher)."""
        try:
            resp = requests.get(
                url, timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
        text = post.get("text") or post.get("message") or post.get("content") or ""
        raw_date = post.get("date") or post.get("time") or post.get("timestamp")
        published_date = None
        if raw_date:
            try:
                if isinstance(raw_date, (int, float)):
                    published_date = datetime.fromtimestamp(raw_date, tz=timezone.utc).isoformat()
                else:
                    published_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).isoformat()
            except Exception:
                published_date = datetime.now(timezone.utc).isoformat()

        source_image_url = post.get("imgUrl") or post.get("imageUrl") or post.get("image")

        if not source_image_url:
            post_url = self._get_url(post)
            if post_url:
                source_image_url = extract_og_image(post_url)

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
