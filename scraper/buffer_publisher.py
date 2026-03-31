"""
Buffer Publisher — push Content Queue items (Status=Approved) lên Buffer
để schedule đăng TikTok + Instagram.

Logic:
- Query Airtable Content Queue: Status=Approved AND Buffer ID trống
- Với mỗi item: build caption + link, gọi Buffer API
- Update Airtable: Buffer ID (trước) rồi Status=Scheduled
- Không fail toàn run khi 1 item lỗi
"""
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from airtable_client import AirtableClient

load_dotenv(Path(__file__).parent.parent / ".env")
log = logging.getLogger(__name__)

BUFFER_ACCESS_TOKEN = os.getenv("BUFFER_ACCESS_TOKEN")
BUFFER_TIKTOK_PROFILE_ID = os.getenv("BUFFER_TIKTOK_PROFILE_ID")
BUFFER_INSTAGRAM_PROFILE_ID = os.getenv("BUFFER_INSTAGRAM_PROFILE_ID")

BUFFER_API_BASE = "https://api.bufferapp.com/1"


class BufferPublisher:
    def __init__(self):
        missing = [
            k for k, v in {
                "BUFFER_ACCESS_TOKEN": BUFFER_ACCESS_TOKEN,
                "BUFFER_TIKTOK_PROFILE_ID": BUFFER_TIKTOK_PROFILE_ID,
                "BUFFER_INSTAGRAM_PROFILE_ID": BUFFER_INSTAGRAM_PROFILE_ID,
            }.items() if not v
        ]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")
        self.client = AirtableClient()

    def push_pending_items(self, limit: int = 20) -> dict:
        """
        Fetch Content Queue items với Status=Approved và Buffer ID trống,
        push lên Buffer, update Airtable. Returns stats dict.
        """
        log.info("Fetching Content Queue items with Status=Approved and no Buffer ID...")
        records = self.client.get_records(
            "contentQueue",
            filter_formula='AND({Status}="Approved", {Buffer ID}="")',
            max_records=limit,
        )
        log.info(f"Found {len(records)} items to push to Buffer")

        stats = {"pushed": 0, "skipped": 0, "errors": 0}

        for record in records:
            record_id = record["id"]
            title = record["fields"].get("Title", "")[:50]

            caption = self._build_caption(record)
            if not caption:
                log.warning(f"  [Skip] {title} — no caption")
                stats["skipped"] += 1
                continue

            link = self._get_link(record)

            try:
                buffer_id = self._push_to_buffer(caption, link)
                # Update Buffer ID first (dedup guard)
                self.client.update_record("contentQueue", record_id, {
                    "Buffer ID": buffer_id,
                })
                # Then update Status
                self.client.update_record("contentQueue", record_id, {
                    "Status": "Scheduled",
                })
                log.info(f"  [Pushed] {title} → Buffer ID: {buffer_id}")
                stats["pushed"] += 1
            except Exception as e:
                log.error(f"  [Error] {title}: {e}")
                stats["errors"] += 1

        log.info(f"Buffer push complete: {stats}")
        return stats

    def _build_caption(self, record: dict) -> str:
        """Ghép Draft VN + Draft EN thành caption. Return '' nếu cả 2 trống."""
        vn = record["fields"].get("Draft VN", "").strip()
        en = record["fields"].get("Draft EN", "").strip()
        if not vn and not en:
            return ""
        parts = [p for p in [vn, en] if p]
        return "\n\n".join(parts)

    def _get_link(self, record: dict) -> str:
        """
        Lấy link để đính kèm vào Buffer post.
        Priority: Affiliate link > URL từ Raw Item > empty string.
        """
        affiliate = record["fields"].get("Affiliate link", "").strip()
        if affiliate:
            return affiliate

        # Raw Item là linked record — Airtable trả về array of record IDs
        raw_item_ids = record["fields"].get("Raw Item", [])
        if raw_item_ids:
            raw_records = self.client.get_records(
                "rawItems",
                filter_formula=f'RECORD_ID()="{raw_item_ids[0]}"',
                max_records=1,
            )
            if raw_records:
                return raw_records[0]["fields"].get("URL", "")
        return ""

    def _push_to_buffer(self, text: str, link: str) -> str:
        """
        Push update lên Buffer cho cả TikTok và Instagram profiles.
        Return Buffer update ID (ID của update đầu tiên trong response).
        Retry 1 lần nếu gặp 429.
        """
        profile_ids = [BUFFER_TIKTOK_PROFILE_ID, BUFFER_INSTAGRAM_PROFILE_ID]
        data = {
            "access_token": BUFFER_ACCESS_TOKEN,
            "text": text,
            "profile_ids[]": profile_ids,
            "shorten": "false",
        }
        if link:
            data["media[link]"] = link

        for attempt in range(2):
            resp = requests.post(f"{BUFFER_API_BASE}/updates/create.json", data=data)
            if resp.status_code == 429:
                log.warning("Buffer rate limit, sleeping 5s...")
                time.sleep(5)
                continue
            resp.raise_for_status()
            result = resp.json()
            updates = result.get("updates", [])
            if not updates:
                raise RuntimeError(f"Buffer returned no updates: {result}")
            buffer_id = updates[0].get("id")
            if not buffer_id:
                raise RuntimeError(f"Buffer update missing id: {updates[0]}")
            return buffer_id

        raise RuntimeError("Buffer API rate limit exceeded after retry")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    publisher = BufferPublisher()
    stats = publisher.push_pending_items(limit=20)
    print(stats)
