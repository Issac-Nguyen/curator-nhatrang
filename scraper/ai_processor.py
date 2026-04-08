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

GROQ_API_KEYS = [k for k in [os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY_2")] if k]
MODEL = "llama-3.3-70b-versatile"
BATCH_SIZE = 5       # items per API call
RATE_LIMIT_SLEEP = 2  # seconds between batches (30 RPM = 2s min interval)

SYSTEM_PROMPT = """Bạn là AI assistant cho kênh Instagram curator về Nha Trang (du lịch, ẩm thực, địa điểm, sự kiện TẠI NHA TRANG / KHÁNH HÒA).

Bạn sẽ nhận một danh sách bài viết dạng JSON array. Với mỗi bài, phân tích và trả về JSON array tương ứng:
[
  {
    "id": "<id của bài>",
    "relevant": true/false,
    "reason": "lý do nếu không relevant",
    "category": "Sự kiện|Địa điểm|Ẩm thực|Tin tức|Workshop|Khác",
    "title_short": "Tiêu đề NGẮN GỌN tối đa 50 ký tự cho overlay ảnh. Chỉ giữ tên địa điểm/sự kiện + 1 chi tiết nổi bật. Ví dụ: 'Nhà hát Đỏ — Suất diễn mới tại Libera', 'Cà phê trứng béo mịn tại Hòn Kiên'.",
    "summary_vn": "Viết caption Instagram tiếng Việt 3-4 câu: mô tả địa điểm/sự kiện cụ thể, thông tin hữu ích (địa chỉ, giá, giờ mở cửa nếu có), kết bằng câu gợi mở. Thêm hashtag #NhaTrang #KhanhHoa và hashtag liên quan.",
    "summary_en": "Write Instagram caption in English 2-3 sentences: describe the specific place/event, useful info, end with engaging question. Add hashtags #NhaTrang #Vietnam #Travel.",
    "keywords": ["English keyword 1", "English keyword 2", "English keyword 3"],
    "content_potential": "high|medium|low",
    "event_date": "dd/mm hoặc dd/mm/yyyy nếu có ngày sự kiện/workshop, null nếu không",
    "event_time": "HH:MM nếu có giờ bắt đầu, null nếu không",
    "price": "giá gốc từ bài (ví dụ: 500K, 45.000đ, từ 200K), null nếu không có",
    "address": "địa chỉ cụ thể nếu có, null nếu không",
    "opening_hours": "giờ mở cửa (ví dụ: 6:00-21:00), null nếu không có"
  },
  ...
]

QUAN TRỌNG — Nội dung KHÔNG relevant (relevant=false):
- Bài KHÔNG NẰM Ở Nha Trang hoặc Khánh Hòa (ví dụ: Quy Nhơn, Đà Nẵng, Phú Quốc = KHÔNG relevant)
- Bài chỉ nhắc Nha Trang thoáng qua nhưng nội dung chính ở nơi khác = KHÔNG relevant
- Tin chính trị, tội phạm, tai nạn
- Bài quảng cáo thuần túy không có thông tin hữu ích

CHỈ relevant khi bài viết CỤ THỂ về một địa điểm, quán ăn, sự kiện, hoặc trải nghiệm TẠI Nha Trang/Khánh Hòa.

QUAN TRỌNG — Structured fields (event_date, event_time, price, address, opening_hours):
- CHỈ điền khi thông tin CÓ TRONG bài viết gốc. KHÔNG được bịa hoặc suy đoán.
- Nếu không có thông tin trong bài viết NHƯNG có source_address → dùng source_address cho field address.
- price: giữ nguyên format gốc từ bài (500K, 45.000đ, từ 200K, free, miễn phí).
- event_date: chuyển sang dd/mm hoặc dd/mm/yyyy.
- opening_hours: format HH:MM-HH:MM hoặc giữ nguyên từ bài.

keywords: PHẢI bằng tiếng Anh, mô tả nội dung ảnh phù hợp (dùng cho tìm ảnh stock). Ví dụ: ["beach sunset", "Vietnamese street food", "night market"]

content_potential cao (high) khi: địa điểm cụ thể ở Nha Trang, món ăn đặc sắc Nha Trang, sự kiện đang diễn ra, có thông tin chi tiết (giá, địa chỉ, giờ).

Chỉ trả về JSON array, không có text khác."""


class AIProcessor:
    def __init__(self):
        if not GROQ_API_KEYS:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        self._key_index = 0
        self.groq = Groq(api_key=GROQ_API_KEYS[0])
        self.client = AirtableClient()

    def _rotate_key(self) -> bool:
        """Switch to next API key. Returns True if rotated, False if no more keys."""
        self._key_index += 1
        if self._key_index >= len(GROQ_API_KEYS):
            self._key_index = 0
            return False
        self.groq = Groq(api_key=GROQ_API_KEYS[self._key_index])
        log.info(f"Rotated to Groq API key {self._key_index + 1}/{len(GROQ_API_KEYS)}")
        return True

    def _get_source_address(self, item: dict) -> str:
        """Lookup Address from linked Source record."""
        source_ids = item["fields"].get("Source", [])
        if not source_ids:
            return ""
        try:
            records = self.client.get_records(
                "sources",
                filter_formula=f'RECORD_ID()="{source_ids[0]}"',
                max_records=1,
            )
            if records:
                return records[0]["fields"].get("Address", "")
        except Exception:
            pass
        return ""

    def _analyze_batch(self, items: list[dict], source_addresses: dict = None) -> list[dict]:
        """Send a batch of items to Groq, return list of analysis results."""
        source_addresses = source_addresses or {}
        payload = [
            {
                "id": item["id"],
                "title": item["fields"].get("Title", "")[:200],
                "content": item["fields"].get("Content", "")[:1000],
                "source_address": source_addresses.get(item["id"], ""),
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
            max_tokens=3000,
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

        # Lookup source addresses for all items
        source_addresses = {}
        for r in records:
            addr = self._get_source_address(r)
            if addr:
                source_addresses[r["id"]] = addr

        # Pre-filter: skip items with empty content (no need for AI)
        empty = [r for r in records if not r["fields"].get("Content", "").strip()]
        if empty:
            for r in empty:
                self.client.update_record("rawItems", r["id"], {"Status": "Skip"})
                log.info(f"  [Skip] {r['fields'].get('Title','')[:50]} — Nội dung trống")
                stats["skip"] += 1
            records = [r for r in records if r["fields"].get("Content", "").strip()]
            log.info(f"Pre-filtered {len(empty)} empty items, {len(records)} remaining for AI")

        # Process in batches
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            batch_ids = [r["id"] for r in batch]
            log.info(f"Batch {i//BATCH_SIZE + 1}: analyzing {len(batch)} items...")

            try:
                results = self._analyze_batch(batch, source_addresses)

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
                if "429" in str(e) and self._rotate_key():
                    log.warning(f"Rate limited, retrying batch with next key...")
                    try:
                        results = self._analyze_batch(batch, source_addresses)
                        result_map = {r["id"]: r for r in results}
                        for record in batch:
                            record_id = record["id"]
                            result = result_map.get(record_id, {})
                            if not result:
                                stats["errors"] += 1
                                continue
                            if not result.get("relevant", True):
                                new_status = "Skip"
                                stats["skip"] += 1
                            else:
                                potential = result.get("content_potential", "medium")
                                new_status = "Use" if potential == "high" else "Reviewed"
                                if potential == "high":
                                    stats["use"] += 1
                                else:
                                    stats["reviewed"] += 1
                            self.client.update_record("rawItems", record_id, {
                                "AI Summary": json.dumps(result, ensure_ascii=False),
                                "Status": new_status,
                            })
                            stats["processed"] += 1
                    except Exception as e2:
                        log.error(f"Batch {i//BATCH_SIZE + 1} retry failed: {e2}")
                        stats["errors"] += len(batch)
                else:
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
