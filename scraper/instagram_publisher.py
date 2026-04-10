"""
Instagram Publisher — push Content Queue items (Status=Approved) lên Instagram
qua Instagram Graph API (Content Publishing).

Flow:
1. Auto-refresh token nếu còn < 7 ngày
2. Query Airtable: Status=Approved, có Image URL, chưa có Instagram Post ID
3. POST /{ig_user_id}/media  → tạo container (image_url + caption)
4. POST /{ig_user_id}/media_publish → publish container
5. Update Airtable: Instagram Post ID + Status=Scheduled
"""
import logging
import os
import re
import time
from pathlib import Path

import cloudinary
import cloudinary.uploader
import requests
from dotenv import load_dotenv

from airtable_client import AirtableClient

ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)
log = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.instagram.com/v22.0"

# Số ngày còn lại trước khi tự động refresh token
TOKEN_REFRESH_THRESHOLD_DAYS = 7


def _refresh_token_if_needed() -> str:
    """
    Kiểm tra token còn bao lâu hết hạn. Nếu < 7 ngày → refresh.
    Instagram long-lived token refresh:
      GET /refresh_access_token?grant_type=ig_refresh_token&access_token=<token>
    Token mới có hiệu lực 60 ngày kể từ lúc refresh.
    Token chỉ refresh được nếu >= 24h tuổi và chưa hết hạn.
    Cập nhật .env nếu refresh thành công.
    Return access_token hiện tại (có thể đã được refresh).
    """
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        return token

    # Bước 1: Kiểm tra token expiry
    try:
        resp = requests.get(
            f"{GRAPH_API_BASE}/me",
            params={"fields": "user_id", "access_token": token},
            timeout=10,
        )
        if resp.status_code == 190 or (resp.status_code != 200 and "expired" in resp.text.lower()):
            log.warning("Instagram token đã hết hạn, không thể refresh tự động")
            return token
    except requests.RequestException:
        pass  # network error — thử refresh anyway

    # Bước 2: Kiểm tra data_access_expires_at qua debug endpoint
    try:
        resp = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": token,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            new_token = data.get("access_token", "")
            expires_in = data.get("expires_in", 0)
            expires_days = expires_in // 86400
            if new_token and new_token != token:
                _update_env_token(new_token)
                log.info(f"Instagram token refreshed — hết hạn sau {expires_days} ngày")
                return new_token
            log.info(f"Instagram token vẫn còn hiệu lực — hết hạn sau {expires_days} ngày")
            return token
        else:
            error = resp.json().get("error", {})
            log.warning(f"Token refresh failed: {error.get('message', resp.text[:200])}")
            return token
    except requests.RequestException as e:
        log.warning(f"Token refresh request failed: {e}")
        return token


def _update_env_token(new_token: str) -> None:
    """Cập nhật INSTAGRAM_ACCESS_TOKEN trong .env file."""
    try:
        content = ENV_PATH.read_text()
        updated = re.sub(
            r"^INSTAGRAM_ACCESS_TOKEN=.*$",
            f"INSTAGRAM_ACCESS_TOKEN={new_token}",
            content,
            flags=re.MULTILINE,
        )
        ENV_PATH.write_text(updated)
        # Cập nhật biến môi trường trong process hiện tại
        os.environ["INSTAGRAM_ACCESS_TOKEN"] = new_token
        log.info("Updated INSTAGRAM_ACCESS_TOKEN in .env")
    except Exception as e:
        log.error(f"Failed to update .env: {e}")


class InstagramPublisher:
    def __init__(self):
        # Auto-refresh token trước khi khởi tạo
        self.access_token = _refresh_token_if_needed()
        self.user_id = os.getenv("INSTAGRAM_USER_ID", "")

        if not self.access_token or not self.user_id:
            missing = []
            if not self.user_id:
                missing.append("INSTAGRAM_USER_ID")
            if not self.access_token:
                missing.append("INSTAGRAM_ACCESS_TOKEN")
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

        self.client = AirtableClient()

        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET"),
            secure=True,
        )

    def push_pending_items(self, limit: int = 20) -> dict:
        """
        Fetch Content Queue items: Status=Approved, có Image URL, chưa publish.
        Push lên Instagram, update Airtable.
        """
        log.info("Fetching Content Queue items: Status=Approved, has Image URL, no Buffer ID...")
        records = self.client.get_records(
            "contentQueue",
            filter_formula='AND({Status}="Approved", {Image URL}!="", {Buffer ID}="")',
            max_records=limit,
        )
        log.info(f"Found {len(records)} items to publish to Instagram")

        stats = {"pushed": 0, "skipped": 0, "errors": 0}

        for record in records:
            record_id = record["id"]
            title = record["fields"].get("Title", "")[:50]

            caption = self._build_caption(record)
            if not caption:
                log.warning(f"  [Skip] {title} — no caption")
                stats["skipped"] += 1
                continue

            image_url = record["fields"].get("Image URL", "").strip()
            if not image_url:
                log.warning(f"  [Skip] {title} — no image")
                stats["skipped"] += 1
                continue

            try:
                media_id = self._publish_photo(caption, image_url)
                log.info(f"  [Published] {title} → IG Media ID: {media_id}")
                self._post_hashtag_comment(record, media_id)
                self._post_source_link_comment(record, media_id)
                self._cleanup_after_publish(record, record_id, media_id)
                stats["pushed"] += 1
                time.sleep(2)
            except Exception as e:
                log.error(f"  [Error] {title}: {e}")
                stats["errors"] += 1

        log.info(f"Instagram publish complete: {stats}")
        return stats

    def _build_caption(self, record: dict) -> str:
        """Ghép Draft VN + Draft EN thành caption (hashtags removed — go to first comment)."""
        vn = record["fields"].get("Draft VN", "").strip()
        en = record["fields"].get("Draft EN", "").strip()
        if not vn and not en:
            return ""
        # Strip hashtag lines from caption (they go to first comment now)
        vn_clean = "\n".join(l for l in vn.splitlines() if not l.strip().startswith("#")) if vn else ""
        en_clean = "\n".join(l for l in en.splitlines() if not l.strip().startswith("#")) if en else ""
        parts = [p.strip() for p in [vn_clean, en_clean] if p.strip()]
        return "\n\n".join(parts)

    def _extract_hashtags(self, record: dict) -> str:
        """Extract hashtags from Draft VN + Draft EN for first comment."""
        vn = record["fields"].get("Draft VN", "").strip()
        en = record["fields"].get("Draft EN", "").strip()
        tags = []
        for text in [vn, en]:
            if not text:
                continue
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("#"):
                    tags.append(line)
        return " ".join(tags) if tags else ""

    def _post_hashtag_comment(self, record: dict, media_id: str) -> None:
        """Post hashtags as first comment (cleaner caption, same discoverability)."""
        hashtags = self._extract_hashtags(record)
        if not hashtags:
            return
        try:
            resp = requests.post(
                f"{GRAPH_API_BASE}/{media_id}/comments",
                data={"message": hashtags, "access_token": self.access_token},
                timeout=10,
            )
            if resp.status_code == 200:
                log.info(f"  [Comment] Posted hashtags")
            else:
                log.warning(f"  [Comment] Hashtags failed: {resp.json()}")
        except Exception as e:
            log.warning(f"  [Comment] Hashtags error: {e}")

    def _post_source_link_comment(self, record: dict, media_id: str) -> None:
        """Post a comment with the source URL on the published media."""
        raw_item_ids = record["fields"].get("Raw Item", [])
        if not raw_item_ids:
            return
        try:
            raw_records = self.client.get_records(
                "rawItems",
                filter_formula=f'RECORD_ID()="{raw_item_ids[0]}"',
                max_records=1,
            )
            if not raw_records:
                return
            source_url = raw_records[0]["fields"].get("URL", "").strip()
            if not source_url:
                return

            comment = f"📌 Nguồn / Source: {source_url}"
            resp = requests.post(
                f"{GRAPH_API_BASE}/{media_id}/comments",
                data={"message": comment, "access_token": self.access_token},
                timeout=10,
            )
            if resp.status_code == 200:
                log.info(f"  [Comment] Posted source link")
            else:
                log.warning(f"  [Comment] Failed: {resp.json()}")
        except Exception as e:
            log.warning(f"  [Comment] Error: {e}")

    def _cleanup_after_publish(self, record: dict, record_id: str, media_id: str) -> None:
        """
        Sau khi publish thành công:
        1. Tạo Published record (với permalink từ Instagram)
        2. Xóa Cloudinary image
        3. Xóa Content Queue record
        4. Xóa Raw Item linked record
        Best-effort: log errors nhưng không raise.
        """
        title = record["fields"].get("Title", "")
        image_url = record["fields"].get("Image URL", "")
        raw_item_ids = record["fields"].get("Raw Item", [])

        # 1. Get Instagram permalink
        permalink = ""
        try:
            resp = requests.get(
                f"{GRAPH_API_BASE}/{media_id}",
                params={"fields": "permalink", "access_token": self.access_token},
                timeout=10,
            )
            if resp.status_code == 200:
                permalink = resp.json().get("permalink", "")
        except Exception as e:
            log.warning(f"  [Cleanup] Failed to get permalink: {e}")

        # 2. Create Published record
        try:
            from datetime import datetime, timezone
            self.client.create_record("published", {
                "Title": title,
                "Platform": "Instagram",
                "Post URL": permalink,
                "Published at": datetime.now(timezone.utc).isoformat(),
            })
            log.info(f"  [Cleanup] Created Published record")
        except Exception as e:
            log.warning(f"  [Cleanup] Failed to create Published record: {e}")

        # 3. Delete Cloudinary image
        if image_url and "cloudinary.com" in image_url:
            try:
                parts = image_url.split("/upload/")
                if len(parts) == 2:
                    path = parts[1]
                    if path.startswith("v"):
                        path = path.split("/", 1)[1] if "/" in path else path
                    public_id = path.rsplit(".", 1)[0] if "." in path else path
                    cloudinary.uploader.destroy(public_id)
                    log.info(f"  [Cleanup] Deleted Cloudinary image: {public_id}")
            except Exception as e:
                log.warning(f"  [Cleanup] Failed to delete Cloudinary image: {e}")

        # 4. Delete Content Queue record
        try:
            self.client.delete_record("contentQueue", record_id)
            log.info(f"  [Cleanup] Deleted Content Queue record")
        except Exception as e:
            log.warning(f"  [Cleanup] Failed to delete Content Queue record: {e}")

        # 5. Delete Raw Item linked record
        if raw_item_ids:
            try:
                self.client.delete_record("rawItems", raw_item_ids[0])
                log.info(f"  [Cleanup] Deleted Raw Item")
            except Exception as e:
                log.warning(f"  [Cleanup] Failed to delete Raw Item: {e}")

    def _publish_photo(self, caption: str, image_url: str) -> str:
        """
        Publish ảnh lên Instagram qua 2 bước:
        1. Create media container
        2. Publish container
        Return Instagram Media ID.
        """
        # Step 1: Create container
        log.info(f"  Creating media container...")
        resp = requests.post(
            f"{GRAPH_API_BASE}/{self.user_id}/media",
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": self.access_token,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Create container failed: {resp.json()}")
        container_id = resp.json().get("id")
        if not container_id:
            raise RuntimeError(f"No container ID returned: {resp.json()}")
        log.info(f"  Container created: {container_id}")

        # Đợi container process xong (Instagram cần thời gian render)
        time.sleep(3)

        # Step 2: Publish container
        log.info(f"  Publishing container...")
        resp2 = requests.post(
            f"{GRAPH_API_BASE}/{self.user_id}/media_publish",
            data={
                "creation_id": container_id,
                "access_token": self.access_token,
            },
        )
        if resp2.status_code != 200:
            raise RuntimeError(f"Publish failed: {resp2.json()}")
        media_id = resp2.json().get("id")
        if not media_id:
            raise RuntimeError(f"No media ID returned: {resp2.json()}")

        return media_id


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    publisher = InstagramPublisher()
    stats = publisher.push_pending_items(limit=20)
    print(stats)
