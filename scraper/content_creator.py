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


def _similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity (Jaccard). Returns 0.0-1.0."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


class ContentCreator:
    def __init__(self):
        self.client = AirtableClient()

    def _get_recent_titles(self) -> list[str]:
        """Get titles from Content Queue + recent Instagram posts to check duplicates."""
        titles = []
        # Content Queue titles
        cq = self.client.get_records("contentQueue", max_records=50)
        for r in cq:
            t = r["fields"].get("Title", "")
            if t:
                titles.append(t)
        # Recent published titles (last 30 days)
        pub = self.client.get_records("published", max_records=50)
        for r in pub:
            t = r["fields"].get("Title", "")
            if t:
                titles.append(t)
        return titles

    def _is_duplicate(self, title: str, existing_titles: list[str], threshold: float = 0.5) -> bool:
        """Check if title is too similar to any existing title."""
        for existing in existing_titles:
            if _similarity(title, existing) > threshold:
                log.info(f"  Duplicate detected: '{title[:40]}' ~ '{existing[:40]}'")
                return True
        return False

    def promote_items(self, limit: int = 10) -> dict:
        """
        Move Raw Items with Status=Use to Content Queue.
        Skips items with titles too similar to existing content.
        Returns stats dict.
        """
        log.info("Fetching Raw Items with Status=Use...")
        records = self.client.get_records(
            "rawItems",
            filter_formula='AND({Status}="Use", {AI Summary}!="")',
            max_records=limit,
        )
        log.info(f"Found {len(records)} items to promote")

        existing_titles = self._get_recent_titles()
        stats = {"promoted": 0, "skipped": 0, "duplicates": 0, "errors": 0}

        for record in records:
            record_id = record["id"]
            fields = record["fields"]
            title = fields.get("Title", "")
            title_short = title[:50]

            try:
                ai_raw = fields.get("AI Summary", "")
                if not ai_raw:
                    stats["skipped"] += 1
                    continue

                ai = json.loads(ai_raw)
                draft_vn = ai.get("summary_vn", "")
                draft_en = ai.get("summary_en", "")

                if not draft_vn and not draft_en:
                    log.warning(f"  [Skip] {title_short} — no draft content")
                    stats["skipped"] += 1
                    continue

                # Check duplicate
                if self._is_duplicate(title, existing_titles):
                    log.info(f"  [Dup] {title_short}")
                    self.client.update_record("rawItems", record_id, {"Status": "Skip"})
                    stats["duplicates"] += 1
                    continue

                # Create Content Queue record
                cq_fields = {
                    "Title": title[:100],
                    "Raw Item": [record_id],
                    "Draft VN": draft_vn,
                    "Draft EN": draft_en,
                    "Status": "Approved",
                }
                self.client.create_record("contentQueue", cq_fields)

                # Mark Raw Item as processed + add to existing titles
                self.client.update_record("rawItems", record_id, {"Status": "Reviewed"})
                existing_titles.append(title)
                log.info(f"  [Promoted] {title_short}")
                stats["promoted"] += 1
                time.sleep(0.3)

            except Exception as e:
                log.error(f"  [Error] {title_short}: {e}")
                stats["errors"] += 1

        log.info(f"Content creator complete: {stats}")
        return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    creator = ContentCreator()
    stats = creator.promote_items(limit=10)
    print(stats)
