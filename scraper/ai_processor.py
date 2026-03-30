"""
AI Processor — dùng Groq (llama-3.3-70b, free tier 30 RPM / 14400 RPD)
với batch processing (5 items/request) để tối ưu throughput.

Logic:
- Lọc nội dung không liên quan (tin chính trị, etc.)
- Tóm tắt song ngữ Việt/Anh
- Phân loại category
- Cập nhật AI Summary (JSON) và Status trong Airtable
"""
import json
import logging
import os
import time
from pathlib import Path

from groq import Groq
from dotenv import load_dotenv

from airtable_client import AirtableClient

load_dotenv(Path(__file__).parent.parent / ".env")
log = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = "llama-3.3-70b-versatile"
BATCH_SIZE = 5       # items per API call
RATE_LIMIT_SLEEP = 2  # seconds between batches (30 RPM = 2s min interval)

SYSTEM_PROMPT = """Bạn là AI assistant cho hệ thống content curation về Nha Trang (du lịch, ẩm thực, địa điểm, sự kiện).

Bạn sẽ nhận một danh sách bài viết dạng JSON array. Với mỗi bài, phân tích và trả về JSON array tương ứng:
[
  {
    "id": "<id của bài>",
    "relevant": true/false,
    "reason": "lý do nếu không relevant (bỏ trống nếu relevant)",
    "category": "Sự kiện|Địa điểm|Ẩm thực|Tin tức|Workshop|Khác",
    "summary_vn": "tóm tắt tiếng Việt 1-2 câu",
    "summary_en": "English summary 1-2 sentences",
    "keywords": ["từ khóa 1", "từ khóa 2"],
    "content_potential": "high|medium|low"
  },
  ...
]

Nội dung KHÔNG relevant (relevant=false):
- Tin chính trị, bầu cử, quân sự, an ninh
- Tin tội phạm, tai nạn nghiêm trọng
- Tin không liên quan Nha Trang/Khánh Hòa/du lịch Việt Nam

content_potential cao (high) khi: địa điểm độc đáo, món ăn đặc sắc, sự kiện lớn, trải nghiệm thú vị cho du khách.

Chỉ trả về JSON array, không có text khác."""


class AIProcessor:
    def __init__(self):
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        self.groq = Groq(api_key=GROQ_API_KEY)
        self.client = AirtableClient()

    def _analyze_batch(self, items: list[dict]) -> list[dict]:
        """Send a batch of items to Groq, return list of analysis results."""
        payload = [
            {
                "id": item["id"],
                "title": item["fields"].get("Title", "")[:200],
                "content": item["fields"].get("Content", "")[:1000],
            }
            for item in items
        ]

        prompt = f"Phân tích các bài viết sau:\n{json.dumps(payload, ensure_ascii=False)}"

        response = self.groq.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )

        text = response.choices[0].message.content.strip()

        # Strip markdown code blocks if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        # Remove trailing ``` if present
        if text.endswith("```"):
            text = text[:-3].strip()

        return json.loads(text)

    def process_new_items(self, limit: int = 50) -> dict:
        """
        Fetch Raw Items with Status='New', analyze with Groq in batches,
        update Airtable. Returns stats dict.
        """
        log.info("Fetching Raw Items with Status=New...")
        records = self.client.get_records(
            "rawItems",
            filter_formula="Status='New'",
            max_records=limit,
        )
        log.info(f"Found {len(records)} New items to process")

        stats = {"processed": 0, "use": 0, "reviewed": 0, "skip": 0, "errors": 0}

        # Process in batches
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            batch_ids = [r["id"] for r in batch]
            log.info(f"Batch {i//BATCH_SIZE + 1}: analyzing {len(batch)} items...")

            try:
                results = self._analyze_batch(batch)

                # Map results by id
                result_map = {r["id"]: r for r in results}

                for record in batch:
                    record_id = record["id"]
                    result = result_map.get(record_id, {})

                    if not result:
                        log.warning(f"No result for {record_id}, skipping")
                        stats["errors"] += 1
                        continue

                    # Determine status
                    if not result.get("relevant", True):
                        new_status = "Skip"
                        stats["skip"] += 1
                        log.info(f"  [Skip] {record['fields'].get('Title','')[:50]} — {result.get('reason','')}")
                    else:
                        potential = result.get("content_potential", "medium")
                        if potential == "high":
                            new_status = "Use"
                            stats["use"] += 1
                        else:
                            new_status = "Reviewed"
                            stats["reviewed"] += 1
                        log.info(f"  [{new_status}] {record['fields'].get('Title','')[:50]} | {result.get('category','')} | {potential}")

                    # Update Airtable
                    update_fields = {
                        "AI Summary": json.dumps(result, ensure_ascii=False),
                        "Status": new_status,
                    }
                    self.client.update_record("rawItems", record_id, update_fields)
                    stats["processed"] += 1

                # Rate limit: 30 RPM = 1 req/2s, sleep between batches
                if i + BATCH_SIZE < len(records):
                    time.sleep(RATE_LIMIT_SLEEP)

            except json.JSONDecodeError as e:
                log.error(f"JSON parse error in batch {i//BATCH_SIZE + 1}: {e}")
                stats["errors"] += len(batch)
                time.sleep(RATE_LIMIT_SLEEP)
            except Exception as e:
                log.error(f"Batch {i//BATCH_SIZE + 1} error: {e}")
                stats["errors"] += len(batch)
                time.sleep(5)

        log.info(f"Processing complete: {stats}")
        return stats


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    processor = AIProcessor()
    processor.process_new_items(limit=50)
