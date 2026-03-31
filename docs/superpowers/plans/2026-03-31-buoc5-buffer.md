# Bước 5: Buffer Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tự động push Content Queue items (Status=Approved) lên Buffer để schedule đăng TikTok và Instagram mỗi 30 phút.

**Architecture:** `BufferPublisher` class query Airtable lấy items Approved chưa có Buffer ID, gọi Buffer API để create updates, update Airtable với Status=Scheduled và Buffer ID. Flask endpoint `/run-buffer` expose class này. n8n workflow poll mỗi 30 phút và gửi Telegram khi xong.

**Tech Stack:** Python, requests, Buffer API v1, Airtable REST API, Flask, n8n

---

## File Map

```
scraper/
  buffer_publisher.py   CREATE  BufferPublisher class
  server.py             MODIFY  thêm /run-buffer endpoint (line 91-95)

.env                    MODIFY  thêm 3 biến Buffer
```

---

## Task 1: Chuẩn bị Buffer credentials

**Files:**
- Modify: `.env`

- [ ] **Step 1: Lấy Buffer Access Token**

Vào https://buffer.com → Settings → Apps → Create an App (hoặc dùng personal access token).

Lấy 2 Profile IDs (TikTok và Instagram):
```bash
curl -s "https://api.bufferapp.com/1/profiles.json?access_token=YOUR_TOKEN" | python3 -m json.tool | grep -E '"id"|"service"'
```
Expected output:
```json
"id": "abc123",
"service": "tiktok",
...
"id": "def456",
"service": "instagram",
```

- [ ] **Step 2: Thêm vào .env**

```
BUFFER_ACCESS_TOKEN=your_token_here
BUFFER_TIKTOK_PROFILE_ID=abc123
BUFFER_INSTAGRAM_PROFILE_ID=def456
```

- [ ] **Step 3: Thêm Status option "Scheduled" vào Airtable**

Vào Airtable → Content Queue table → field `Status` → Edit field → thêm option `Scheduled`.

Thêm field `Buffer ID` (Single line text) nếu chưa có.

- [ ] **Step 4: Verify Buffer API hoạt động**

```bash
cd scraper && source venv/bin/activate
python3 -c "
import os, requests
from dotenv import load_dotenv
load_dotenv('../.env')
token = os.getenv('BUFFER_ACCESS_TOKEN')
resp = requests.get(f'https://api.bufferapp.com/1/profiles.json?access_token={token}')
print(resp.status_code, [p['service'] for p in resp.json()])
"
# Expected: 200 ['tiktok', 'instagram']  (order may vary)
```

---

## Task 2: Tạo BufferPublisher

**Files:**
- Create: `scraper/buffer_publisher.py`

- [ ] **Step 1: Tạo scraper/buffer_publisher.py**

```python
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
            return updates[0]["id"]

        raise RuntimeError("Buffer API rate limit exceeded after retry")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    publisher = BufferPublisher()
    stats = publisher.push_pending_items(limit=20)
    print(stats)
```

- [ ] **Step 2: Chạy thử với 1 Approved item**

Đảm bảo có ít nhất 1 Content Queue item có Status=Approved trước khi chạy.

```bash
cd scraper && source venv/bin/activate
python buffer_publisher.py
# Expected:
# Found N items to push to Buffer
#   [Pushed] <title> → Buffer ID: abc123
# Buffer push complete: {'pushed': 1, 'skipped': 0, 'errors': 0}
```

- [ ] **Step 3: Verify trên Buffer dashboard**

Vào https://buffer.com → Queue. Kiểm tra post xuất hiện trong TikTok và Instagram queues.

- [ ] **Step 4: Verify Airtable update**

```bash
python3 -c "
from airtable_client import AirtableClient
client = AirtableClient()
records = client.get_records('contentQueue', filter_formula='{Status}=\"Scheduled\"', max_records=5)
for r in records:
    print(r['fields'].get('Title','')[:40], '|', r['fields'].get('Buffer ID','NO_ID'), '|', r['fields'].get('Status',''))
"
# Expected: title | buffer_id | Scheduled
```

- [ ] **Step 5: Commit**

```bash
git add scraper/buffer_publisher.py
git commit -m "feat: BufferPublisher push Content Queue Approved items lên TikTok/Instagram"
```

---

## Task 3: Thêm /run-buffer endpoint vào server.py

**Files:**
- Modify: `scraper/server.py`

- [ ] **Step 1: Thêm endpoint sau /run-ai-processor (line 91)**

Mở `scraper/server.py`, thêm sau block `/run-ai-processor` (trước `if __name__ == "__main__":`):

```python
@app.post("/run-buffer")
def run_buffer():
    err = _check_auth()
    if err:
        return err
    try:
        from buffer_publisher import BufferPublisher
        publisher = BufferPublisher()
        stats = publisher.push_pending_items(limit=20)
        log.info(f"/run-buffer: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-buffer error: {e}")
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Test endpoint locally**

```bash
cd scraper && source venv/bin/activate
python server.py &
sleep 2
curl -s -X POST http://localhost:8000/run-buffer | python3 -m json.tool
# Expected: {"pushed": 0, "skipped": 0, "errors": 0}
# (0 vì đã push hết ở Task 2)
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add scraper/server.py
git commit -m "feat: thêm /run-buffer endpoint vào Flask server"
```

---

## Task 4: Deploy lên Render

**Files:**
- No file changes — deploy code hiện tại

- [ ] **Step 1: Push lên GitHub**

```bash
git push origin main
```

- [ ] **Step 2: Verify Render deploy thành công**

Vào Render dashboard → curator-api service → Deploys. Chờ deploy hoàn thành (2-3 phút).

Check health:
```bash
curl https://curator-api.onrender.com/health
# Expected: {"status": "ok"}
```

- [ ] **Step 3: Test /run-buffer trên Render**

```bash
curl -s -X POST https://curator-api.onrender.com/run-buffer \
  -H "X-API-Key: YOUR_API_SECRET_KEY" | python3 -m json.tool
# Expected: {"pushed": 0, "skipped": 0, "errors": 0}
```

---

## Task 5: Tạo n8n workflow "Buffer Publisher"

**Files:**
- Cấu hình trong n8n UI tại https://curator-n8n.onrender.com

- [ ] **Step 1: Tạo workflow mới, đặt tên "Buffer Publisher"**

n8n UI → New Workflow → đặt tên "Buffer Publisher".

- [ ] **Step 2: Thêm Schedule Trigger node**

- Node type: Schedule Trigger
- Interval: Every 30 minutes

- [ ] **Step 3: Thêm HTTP Request node — /run-buffer**

- Node type: HTTP Request
- Method: POST
- URL: `https://curator-api.onrender.com/run-buffer`
- Authentication: Header Auth
  - Name: `X-API-Key`
  - Value: `{{ $env.API_SECRET_KEY }}` (hoặc điền trực tiếp)

- [ ] **Step 4: Thêm Telegram node**

- Node type: Telegram
- Credentials: dùng credentials đã có từ Bước 4
- Operation: Send Message
- Chat ID: chat ID đã config từ Bước 4
- Text:
```
✅ Buffer Publisher: pushed {{ $json.pushed }} items
⏩ Skipped: {{ $json.skipped }} | Errors: {{ $json.errors }}
```

- [ ] **Step 5: Activate workflow và test manual run**

Toggle Activate → bật workflow.

Click "Test workflow" để chạy thử. Kiểm tra Telegram nhận được message và Buffer queue không bị spam.

- [ ] **Step 6: Commit ghi chú vào PROCESS.md**

Cập nhật PROCESS.md (hoặc tạo nếu chưa có) để ghi lại Bước 5 đã hoàn thành:

```bash
# Thêm vào cuối PROCESS.md
echo "- [x] Bước 5: Buffer Publisher workflow" >> PROCESS.md
git add PROCESS.md
git commit -m "docs: mark Bước 5 Buffer Publisher complete"
```

---

## Ghi chú kỹ thuật

- Buffer API v1 dùng `access_token` trong request body (form data), không phải Bearer header
- `profile_ids[]` pass dạng list trong form data để push cả 2 platforms cùng lúc
- `updates[0]["id"]` là TikTok update ID — dùng làm dedup key trong Airtable
- Nếu Airtable update Buffer ID thành công nhưng update Status fail → lần poll sau sẽ thấy Buffer ID không trống → skip item (không push duplicate)
- `_get_link` fetch Raw Item record riêng vì Airtable linked fields chỉ trả về record ID, không trả về fields của linked record
