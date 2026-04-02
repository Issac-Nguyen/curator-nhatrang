"""
Content Creator — chuyển Raw Items (Status=Use) sang Content Queue (Status=Approved).

Logic:
- Query Raw Items: Status=Use, có AI Summary
- Tạo Content Queue record với Draft VN/EN từ AI Summary
- Update Raw Item Status → Reviewed (đã xử lý, không tạo lại)
"""
import json
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

from airtable_client import AirtableClient

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=False)

log = logging.getLogger(__name__)


class ContentCreator:
    def __init__(self):
        self.client = AirtableClient()

    def promote_items(self, limit: int = 10) -> dict:
        """
        Move Raw Items with Status=Use to Content Queue.
        Returns stats dict.
        """
        log.info("Fetching Raw Items with Status=Use...")
        records = self.client.get_records(
            "rawItems",
            filter_formula='AND({Status}="Use", {AI Summary}!="")',
            max_records=limit,
        )
        log.info(f"Found {len(records)} items to promote")

        stats = {"promoted": 0, "skipped": 0, "errors": 0}

        for record in records:
            record_id = record["id"]
            fields = record["fields"]
            title = fields.get("Title", "")[:50]

            try:
                ai_raw = fields.get("AI Summary", "")
                if not ai_raw:
                    stats["skipped"] += 1
                    continue

                ai = json.loads(ai_raw)
                draft_vn = ai.get("summary_vn", "")
                draft_en = ai.get("summary_en", "")

                if not draft_vn and not draft_en:
                    log.warning(f"  [Skip] {title} — no draft content")
                    stats["skipped"] += 1
                    continue

                # Create Content Queue record
                cq_fields = {
                    "Title": fields.get("Title", "")[:100],
                    "Raw Item": [record_id],
                    "Draft VN": draft_vn,
                    "Draft EN": draft_en,
                    "Status": "Approved",
                }
                self.client.create_record("contentQueue", cq_fields)

                # Mark Raw Item as processed
                self.client.update_record("rawItems", record_id, {"Status": "Reviewed"})
                log.info(f"  [Promoted] {title}")
                stats["promoted"] += 1
                time.sleep(0.3)

            except Exception as e:
                log.error(f"  [Error] {title}: {e}")
                stats["errors"] += 1

        log.info(f"Content creator complete: {stats}")
        return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    creator = ContentCreator()
    stats = creator.promote_items(limit=10)
    print(stats)
