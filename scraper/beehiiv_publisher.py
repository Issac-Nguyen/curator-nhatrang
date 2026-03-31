"""
Beehiiv Publisher — push Content Queue items (Status=Approved) lên Beehiiv
để publish newsletter.

Logic:
- Query Airtable Content Queue: Status=Approved AND Beehiiv ID trống
- Với mỗi item: build HTML content từ Draft HTML, gọi Beehiiv API
- Update Airtable: Beehiiv ID (trước) rồi Status=Published
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

BEEHIIV_API_KEY = os.getenv("BEEHIIV_API_KEY")
BEEHIIV_PUBLICATION_ID = os.getenv("BEEHIIV_PUBLICATION_ID")

BEEHIIV_API_BASE = "https://api.beehiiv.com/v1"


class BeehiivPublisher:
    def __init__(self):
        missing = [
            k for k, v in {
                "BEEHIIV_API_KEY": BEEHIIV_API_KEY,
                "BEEHIIV_PUBLICATION_ID": BEEHIIV_PUBLICATION_ID,
            }.items() if not v
        ]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")
        self.client = AirtableClient()

    def publish_pending_items(self, limit: int = 20) -> dict:
        """
        Fetch Content Queue items với Status=Approved và Beehiiv ID trống,
        publish lên Beehiiv, update Airtable. Returns stats dict.
        """
        log.info("Fetching Content Queue items with Status=Approved and no Beehiiv ID...")
        records = self.client.get_records(
            "contentQueue",
            filter_formula='AND({Status}="Approved", {Beehiiv ID}="")',
            max_records=limit,
        )
        log.info(f"Found {len(records)} items to publish to Beehiiv")

        stats = {"published": 0, "skipped": 0, "errors": 0}

        for record in records:
            record_id = record["id"]
            title = record["fields"].get("Title", "")[:50]

            # Get content
            content_html = record["fields"].get("Draft HTML", "").strip()
            if not content_html:
                log.warning(f"  [Skip] {title} — no Draft HTML content")
                stats["skipped"] += 1
                continue

            try:
                beehiiv_id = self._publish_to_beehiiv(
                    title=record["fields"].get("Title", "Untitled"),
                    content_html=content_html,
                )
                # Update Beehiiv ID first (dedup guard)
                self.client.update_record("contentQueue", record_id, {
                    "Beehiiv ID": beehiiv_id,
                })
                # Then update Status
                self.client.update_record("contentQueue", record_id, {
                    "Status": "Published",
                })
                log.info(f"  [Published] {title} → Beehiiv ID: {beehiiv_id}")
                stats["published"] += 1
            except Exception as e:
                log.error(f"  [Error] {title}: {e}")
                stats["errors"] += 1

        log.info(f"Beehiiv publish complete: {stats}")
        return stats

    def _publish_to_beehiiv(self, title: str, content_html: str) -> str:
        """
        Publish email lên Beehiiv API.
        Return Beehiiv email ID.
        Retry 1 lần nếu gặp 429.
        """
        headers = {
            "Authorization": f"Bearer {BEEHIIV_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "publication_id": BEEHIIV_PUBLICATION_ID,
            "subject": title,
            "content": content_html,
        }

        for attempt in range(2):
            resp = requests.post(
                f"{BEEHIIV_API_BASE}/emails",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 429:
                log.warning("Beehiiv rate limit, sleeping 5s...")
                time.sleep(5)
                continue
            resp.raise_for_status()
            result = resp.json()
            email_id = result.get("data", {}).get("id")
            if not email_id:
                raise RuntimeError(f"Beehiiv returned no email ID: {result}")
            return email_id

        raise RuntimeError("Beehiiv API rate limit exceeded after retry")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    publisher = BeehiivPublisher()
    stats = publisher.publish_pending_items(limit=20)
    print(stats)
