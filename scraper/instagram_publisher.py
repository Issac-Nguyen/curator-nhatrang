"""
Instagram Publisher — push Content Queue items (Status=Approved) lên Instagram
qua Instagram Graph API (Content Publishing).

Flow:
1. Auto-refresh token nếu còn < 7 ngày
2. Query Airtable: Status=Approved, có Image URL, chưa có Instagram Post ID
3. Pre-render Cloudinary URL → clean URL (Instagram không hỗ trợ complex transform URL)
4. POST /{ig_user_id}/media  → tạo container (image_url + caption)
5. POST /{ig_user_id}/media_publish → publish container
6. Update Airtable: Instagram Post ID + Status=Scheduled
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
                missing.append("self.user_id")
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
                clean_url = self._get_clean_image_url(image_url)
                media_id = self._publish_photo(caption, clean_url)
                # Update Buffer ID field as dedup guard (reuse existing field)
                self.client.update_record("contentQueue", record_id, {
                    "Buffer ID": f"ig:{media_id}",
                })
                self.client.update_record("contentQueue", record_id, {
                    "Status": "Scheduled",
                })
                log.info(f"  [Published] {title} → IG Media ID: {media_id}")
                stats["pushed"] += 1
                # Rate limit: Instagram cho phép 50 posts/24h
                time.sleep(2)
            except Exception as e:
                log.error(f"  [Error] {title}: {e}")
                stats["errors"] += 1

        log.info(f"Instagram publish complete: {stats}")
        return stats

    def _build_caption(self, record: dict) -> str:
        """Ghép Draft VN + Draft EN thành caption."""
        vn = record["fields"].get("Draft VN", "").strip()
        en = record["fields"].get("Draft EN", "").strip()
        if not vn and not en:
            return ""
        parts = [p for p in [vn, en] if p]
        return "\n\n".join(parts)

    def _get_clean_image_url(self, image_url: str) -> str:
        """
        Cloudinary transformation URLs (với text overlay tiếng Việt)
        không hoạt động với Instagram API. Trích xuất public_id từ URL
        và build lại URL đơn giản chỉ với c_fill,w_1080,h_1080.
        """
        # URL format: .../image/upload/{transforms}/{public_id}
        # Extract public_id: phần sau "fl_layer_apply/" cuối cùng, hoặc sau transform cuối
        parts = image_url.split("/image/upload/")
        if len(parts) != 2:
            return image_url  # không phải Cloudinary URL

        cloud_base = parts[0]
        transform_and_id = parts[1]

        # public_id là phần cuối sau tất cả transformations
        # Cloudinary transformations kết thúc tại segment cuối chứa public_id
        # Tìm public_id bằng cách lấy phần sau "fl_layer_apply/" cuối cùng
        if "/fl_layer_apply/" in transform_and_id:
            last_apply_idx = transform_and_id.rfind("/fl_layer_apply/")
            public_id = transform_and_id[last_apply_idx + len("/fl_layer_apply/"):]
        else:
            # Fallback: tách transforms (chứa dấu ,) khỏi public_id
            segments = transform_and_id.split("/")
            non_transform = [s for s in segments if "," not in s and not s.startswith("e_") and not s.startswith("l_")]
            public_id = "/".join(non_transform) if non_transform else transform_and_id

        clean_url = f"{cloud_base}/image/upload/c_fill,w_1080,h_1080/{public_id}.jpg"
        log.info(f"  Clean image URL: {clean_url}")
        return clean_url

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
