# Post-Publish Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tự động cleanup Cloudinary images + Airtable records sau khi publish Instagram, và weekly cleanup old records để giữ dưới Airtable free tier limit.

**Architecture:** Instagram Publisher thêm cleanup logic sau mỗi publish thành công (tạo Published record → xóa Cloudinary → xóa Content Queue → xóa Raw Item). Endpoint `/run-cleanup` xóa records cũ. GitHub Actions cron weekly.

**Tech Stack:** Python, Cloudinary SDK, Airtable REST API, Flask, GitHub Actions

---

## File Map

```
scraper/
  airtable_client.py        MODIFY  thêm delete_record, delete_records_batch
  instagram_publisher.py     MODIFY  thêm cleanup sau publish, thêm cloudinary import
  server.py                  MODIFY  thêm /run-cleanup endpoint
.github/workflows/
  weekly-cleanup.yml         CREATE  cron weekly cleanup job
```

---

## Task 1: Thêm delete methods vào AirtableClient

**Files:**
- Modify: `scraper/airtable_client.py`

- [ ] **Step 1: Thêm `delete_record` method**

Thêm sau method `update_source_last_checked` (cuối file):

```python
def delete_record(self, table_key: str, record_id: str) -> None:
    """Delete a single record."""
    table_id = _config["tables"][table_key]
    _request("DELETE", f"{BASE_URL}/{table_id}/{record_id}")
    log.info(f"Deleted {record_id} from {table_key}")

def delete_records_batch(self, table_key: str, record_ids: list[str]) -> int:
    """Delete up to 10 records per batch. Returns count deleted."""
    table_id = _config["tables"][table_key]
    deleted = 0
    for i in range(0, len(record_ids), 10):
        batch = record_ids[i:i + 10]
        params = "&".join(f"records[]={rid}" for rid in batch)
        _request("DELETE", f"{BASE_URL}/{table_id}?{params}")
        deleted += len(batch)
        log.info(f"Batch deleted {len(batch)} records from {table_key}")
    return deleted
```

- [ ] **Step 2: Commit**

```bash
git add scraper/airtable_client.py
git commit -m "feat: add delete_record and delete_records_batch to AirtableClient"
```

---

## Task 2: Instagram Publisher cleanup sau publish

**Files:**
- Modify: `scraper/instagram_publisher.py`

- [ ] **Step 1: Thêm cloudinary import**

Thêm sau `import requests`:

```python
import cloudinary
import cloudinary.uploader
```

Thêm cloudinary config vào `__init__`, sau `self.client = AirtableClient()`:

```python
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)
```

- [ ] **Step 2: Thêm `create_record` vào AirtableClient**

Thêm vào `scraper/airtable_client.py`, sau `delete_records_batch`:

```python
def create_record(self, table_key: str, fields: dict) -> dict:
    """Create a single record in any table. Returns created record."""
    table_id = _config["tables"][table_key]
    fields = {k: v for k, v in fields.items() if v is not None}
    result = _request("POST", f"{BASE_URL}/{table_id}", json={"records": [{"fields": fields}]})
    log.info(f"Created record in {table_key}")
    return result["records"][0]
```

- [ ] **Step 3: Thêm method `_cleanup_after_publish` vào instagram_publisher.py**

Thêm sau method `_build_caption`:

```python
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
```

- [ ] **Step 4: Sửa `push_pending_items` để gọi cleanup thay vì update Status**

Trong `push_pending_items`, thay block sau `media_id = self._publish_photo(...)`:

```python
# Cũ:
media_id = self._publish_photo(caption, image_url)
self.client.update_record("contentQueue", record_id, {
    "Buffer ID": f"ig:{media_id}",
})
self.client.update_record("contentQueue", record_id, {
    "Status": "Scheduled",
})
log.info(f"  [Published] {title} → IG Media ID: {media_id}")
stats["pushed"] += 1
time.sleep(2)

# Mới:
media_id = self._publish_photo(caption, image_url)
log.info(f"  [Published] {title} → IG Media ID: {media_id}")
self._cleanup_after_publish(record, record_id, media_id)
stats["pushed"] += 1
time.sleep(2)
```

- [ ] **Step 5: Commit**

```bash
git add scraper/airtable_client.py scraper/instagram_publisher.py
git commit -m "feat: auto cleanup after Instagram publish"
```

---

## Task 3: Weekly cleanup endpoint và GitHub Actions

**Files:**
- Modify: `scraper/server.py`
- Create: `.github/workflows/weekly-cleanup.yml`

- [ ] **Step 1: Thêm `/run-cleanup` endpoint vào server.py**

Thêm trước `if __name__` block:

```python
@app.post("/run-cleanup")
def run_cleanup():
    err = _check_auth()
    if err:
        return err
    try:
        client = AirtableClient()
        stats = {"published_deleted": 0, "raw_skip_deleted": 0, "raw_old_deleted": 0}

        # 1. Delete Published records > 30 days
        old_published = client.get_records(
            "published",
            filter_formula='IS_BEFORE({Published at}, DATEADD(TODAY(), -30, "days"))',
            max_records=100,
        )
        if old_published:
            ids = [r["id"] for r in old_published]
            stats["published_deleted"] = client.delete_records_batch("published", ids)

        # 2. Delete Raw Items Status=Skip
        skip_items = client.get_records(
            "rawItems",
            filter_formula='{Status}="Skip"',
            max_records=100,
        )
        if skip_items:
            ids = [r["id"] for r in skip_items]
            stats["raw_skip_deleted"] = client.delete_records_batch("rawItems", ids)

        # 3. Delete Raw Items Status=New older than 30 days
        old_new_items = client.get_records(
            "rawItems",
            filter_formula='AND({Status}="New", IS_BEFORE({Collected at}, DATEADD(TODAY(), -30, "days")))',
            max_records=100,
        )
        if old_new_items:
            ids = [r["id"] for r in old_new_items]
            stats["raw_old_deleted"] = client.delete_records_batch("rawItems", ids)

        log.info(f"/run-cleanup: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-cleanup error: {e}")
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Tạo weekly-cleanup.yml**

```yaml
name: Weekly Cleanup
on:
  schedule:
    - cron: '0 3 * * 0'
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Call /run-cleanup
        id: api
        run: |
          RESULT=$(curl -sf --max-time 300 -X POST \
            "${{ secrets.CURATOR_API_URL }}/run-cleanup" \
            -H "X-API-Key: ${{ secrets.API_SECRET_KEY }}")
          echo "$RESULT"
          echo "result=$RESULT" >> "$GITHUB_OUTPUT"

      - name: Telegram Notification
        if: always()
        run: |
          if [ "${{ steps.api.outcome }}" = "success" ]; then
            PUB=$(echo '${{ steps.api.outputs.result }}' | jq -r '.published_deleted // 0')
            SKIP=$(echo '${{ steps.api.outputs.result }}' | jq -r '.raw_skip_deleted // 0')
            OLD=$(echo '${{ steps.api.outputs.result }}' | jq -r '.raw_old_deleted // 0')
            MSG="✅ Weekly Cleanup: published ${PUB} | skip ${SKIP} | old_new ${OLD} deleted"
          else
            MSG="❌ Weekly Cleanup: API call failed"
          fi
          curl -sf -X POST \
            "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=${MSG}"
```

- [ ] **Step 3: Commit**

```bash
git add scraper/server.py .github/workflows/weekly-cleanup.yml
git commit -m "feat: add /run-cleanup endpoint and weekly GitHub Actions cron"
```

---

## Task 4: Test và push

- [ ] **Step 1: Test cleanup endpoint locally**

```bash
cd scraper && python3 -c "
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
from instagram_publisher import InstagramPublisher
publisher = InstagramPublisher()
stats = publisher.push_pending_items(limit=1)
print('Result:', stats)
"
```

Expected: publish thành công, log cho thấy cleanup steps (Created Published, Deleted Cloudinary, Deleted Content Queue, Deleted Raw Item).

- [ ] **Step 2: Push và deploy**

```bash
git push origin main
```

- [ ] **Step 3: Test cleanup endpoint trên Render**

```bash
curl -sf -X POST "https://curator-api-hhau.onrender.com/run-cleanup" \
  -H "X-API-Key: $(grep '^API_SECRET_KEY=' .env | cut -d= -f2)" | python3 -m json.tool
```

Expected: `{"published_deleted": 0, "raw_skip_deleted": N, "raw_old_deleted": M}`
