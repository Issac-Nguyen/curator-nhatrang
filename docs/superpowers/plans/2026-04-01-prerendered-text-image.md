# Pre-rendered Text on Image — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render text overlay lên ảnh trước khi publish Instagram (Cloudinary eager), ưu tiên ảnh từ nguồn gốc thay vì Pexels stock.

**Architecture:** Scrapers extract ảnh từ RSS/Facebook → lưu `Source Image URL` vào Raw Items. Visual Creator dùng ảnh nguồn (fallback Pexels), upload Cloudinary với `eager` transforms → pre-render text overlay → lưu eager URL sạch vào Airtable. Instagram Publisher dùng URL trực tiếp.

**Tech Stack:** Python, Cloudinary SDK (eager transforms), feedparser, Apify, Airtable REST API

---

## File Map

```
scraper/
  rss_fetcher.py           MODIFY  extract image từ RSS entries
  apify_fetcher.py         MODIFY  extract image từ Facebook posts
  airtable_client.py       MODIFY  thêm Source Image URL vào create_raw_items_batch
  visual_creator.py        MODIFY  eager transforms thay URL overlay, source image priority
  instagram_publisher.py   MODIFY  bỏ _get_clean_image_url, dùng Image URL trực tiếp
```

---

## Task 1: Scrapers extract Source Image URL

**Files:**
- Modify: `scraper/rss_fetcher.py`
- Modify: `scraper/apify_fetcher.py`
- Modify: `scraper/airtable_client.py`

- [ ] **Step 1: Thêm extract image vào rss_fetcher.py**

Trong hàm `fetch()`, thêm logic extract image URL từ entry trước dòng `items.append(...)` (line 72):

```python
# Extract image from entry
image_url = None
# Try enclosures (e.g. <enclosure url="..." type="image/jpeg"/>)
for enc in getattr(entry, "enclosures", []):
    if enc.get("type", "").startswith("image/"):
        image_url = enc.get("href") or enc.get("url")
        break
# Try media_content
if not image_url:
    for media in getattr(entry, "media_content", []):
        if media.get("medium") == "image" or media.get("type", "").startswith("image/"):
            image_url = media.get("url")
            break
# Try links with type image
if not image_url:
    for link in getattr(entry, "links", []):
        if link.get("type", "").startswith("image/"):
            image_url = link.get("href")
            break
```

Và thêm field `"source_image_url": image_url` vào dict trong `items.append({...})`.

Code đầy đủ cho `items.append` block (thay thế lines 72-82):

```python
items.append({
    "title": title.strip(),
    "content": content.strip(),
    "url": entry_url.strip(),
    "published_date": _parse_date(entry),
    "collected_at": datetime.now(timezone.utc).isoformat(),
    "source_name": source_name,
    "source_id": source_id,
    "fetcher_type": "rss",
    "source_image_url": image_url,
})
```

- [ ] **Step 2: Thêm extract image vào apify_fetcher.py**

Trong method `_normalize()`, thêm extract image URL. Apify Facebook scraper trả về `imageUrl` hoặc `fullPicture`.

Thay thế method `_normalize` (lines 105-127):

```python
def _normalize(self, post: dict, source_id: str, source_name: str) -> dict:
    text = post.get("text") or post.get("message") or post.get("body") or ""
    raw_date = post.get("time") or post.get("date") or post.get("created_time")
    published_date = None
    if raw_date:
        try:
            if isinstance(raw_date, (int, float)):
                published_date = datetime.fromtimestamp(raw_date, tz=timezone.utc).isoformat()
            else:
                published_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).isoformat()
        except Exception:
            published_date = datetime.now(timezone.utc).isoformat()

    # Extract image URL from Facebook post
    source_image_url = (
        post.get("imageUrl")
        or post.get("fullPicture")
        or post.get("picture")
    )

    return {
        "title": text[:100].strip() if text else "",
        "content": text.strip(),
        "url": self._get_url(post),
        "published_date": published_date,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source_name": source_name,
        "source_id": source_id,
        "fetcher_type": "facebook",
        "source_image_url": source_image_url,
    }
```

- [ ] **Step 3: Thêm Source Image URL vào airtable_client.py**

Trong `create_raw_items_batch()`, thêm field mapping. Thay block `fields = {...}` (lines 106-113):

```python
fields = {
    "Title": data.get("title", "")[:500],
    "Content": data.get("content", ""),
    "URL": data.get("url", ""),
    "Published date": data.get("published_date"),
    "Collected at": data.get("collected_at"),
    "Source Image URL": data.get("source_image_url"),
    "Status": "New",
}
```

- [ ] **Step 4: Commit**

```bash
git add scraper/rss_fetcher.py scraper/apify_fetcher.py scraper/airtable_client.py
git commit -m "feat: scrapers extract Source Image URL from RSS/Facebook"
```

---

## Task 2: Visual Creator dùng eager transforms + source image

**Files:**
- Modify: `scraper/visual_creator.py`

- [ ] **Step 1: Thêm method `_get_source_image_url` để lấy ảnh từ Raw Item**

Thêm method mới sau `_get_pexels_photo_url` (sau line 123):

```python
def _get_source_image_url(self, record: dict) -> str | None:
    """
    Lấy Source Image URL từ Raw Item linked record.
    Content Queue có field Raw Item (linked record) → query Raw Item → Source Image URL.
    """
    raw_item_ids = record["fields"].get("Raw Item", [])
    if not raw_item_ids:
        return None
    raw_records = self.client.get_records(
        "rawItems",
        filter_formula=f'RECORD_ID()="{raw_item_ids[0]}"',
        max_records=1,
    )
    if not raw_records:
        return None
    url = raw_records[0]["fields"].get("Source Image URL", "").strip()
    if url:
        log.info(f"  Found source image: {url[:80]}...")
    return url or None
```

- [ ] **Step 2: Thay thế `_upload_to_cloudinary` để dùng eager transforms**

Thay toàn bộ method `_upload_to_cloudinary` (lines 125-151):

```python
def _upload_to_cloudinary(self, photo_url: str | None, public_id: str,
                          title: str, caption: str) -> str:
    """
    Upload ảnh lên Cloudinary với eager transforms (pre-render text overlay).
    Returns eager URL (ảnh JPEG đã render sẵn với text).
    """
    if photo_url is None:
        log.info(f"No photo, using gradient placeholder for {public_id}")
        self._ensure_placeholder()
        photo_url = f"https://res.cloudinary.com/{self.cloud_name}/image/upload/nhatrang/placeholder"

    eager_transforms = [
        {"width": 1080, "height": 1080, "crop": "fill"},
        {"effect": "brightness:-30"},
    ]

    # Brand name
    eager_transforms.extend([
        {"overlay": {"font_family": "Arial", "font_size": 26, "font_weight": "bold",
                     "text": "NHA TRANG CURATOR"},
         "color": "#2d9e6b", "gravity": "south_west", "x": 50, "y": 280},
        {"flags": "layer_apply"},
    ])

    # Title
    if title:
        eager_transforms.extend([
            {"overlay": {"font_family": "Arial", "font_size": 40, "font_weight": "bold",
                         "text": title[:55]},
             "color": "#ffffff", "gravity": "south_west", "x": 50, "y": 160,
             "width": 980, "crop": "fit"},
            {"flags": "layer_apply"},
        ])

    # Caption / info lines
    if caption:
        eager_transforms.extend([
            {"overlay": {"font_family": "Arial", "font_size": 24,
                         "text": caption[:110]},
             "color": "#cccccc", "gravity": "south_west", "x": 50, "y": 50,
             "width": 980, "crop": "fit"},
            {"flags": "layer_apply"},
        ])

    for attempt in range(2):
        try:
            result = cloudinary.uploader.upload(
                photo_url,
                public_id=public_id,
                overwrite=True,
                resource_type="image",
                eager=[{"transformation": eager_transforms}],
                eager_async=False,
            )
            eager = result.get("eager", [])
            if eager and eager[0].get("secure_url"):
                eager_url = eager[0]["secure_url"]
                log.info(f"  Eager URL: {eager_url[:80]}...")
                return eager_url
            # Fallback: construct URL manually if eager didn't return
            log.warning("Eager transform returned no URL, using base upload URL")
            return result.get("secure_url", "")
        except Exception as e:
            if attempt == 0:
                log.warning(f"Cloudinary upload attempt 1 failed: {e}, retrying...")
                time.sleep(2)
            else:
                raise RuntimeError(f"Cloudinary upload failed after retry: {e}")
```

- [ ] **Step 3: Sửa `process_pending` để dùng source image + eager**

Thay block `try:` trong `process_pending` (lines 81-98):

```python
try:
    title, caption, hashtags = self._extract_text_parts(record)
    category = record["fields"].get("Category", "")
    keywords = title[:30]

    # Priority: source image > Pexels
    photo_url = self._get_source_image_url(record)
    if not photo_url:
        photo_url = self._get_pexels_photo_url(category, keywords)
        time.sleep(0.5)  # respect Pexels rate limit

    public_id = f"nhatrang/{record_id}"
    image_url = self._upload_to_cloudinary(photo_url, public_id, title, caption)

    self.client.update_record("contentQueue", record_id, {
        "Image URL": image_url,
    })
    log.info(f"  [Done] {title_field}")
    stats["processed"] += 1
```

- [ ] **Step 4: Xóa method `_build_image_url`**

Xóa toàn bộ method `_build_image_url` (lines 174-212) — không cần nữa vì eager URL đã có text.

- [ ] **Step 5: Commit**

```bash
git add scraper/visual_creator.py
git commit -m "feat: visual creator uses eager transforms + source image priority"
```

---

## Task 3: Đơn giản hóa Instagram Publisher

**Files:**
- Modify: `scraper/instagram_publisher.py`

- [ ] **Step 1: Bỏ `_get_clean_image_url` và dùng Image URL trực tiếp**

Trong `push_pending_items`, thay 2 dòng:

```python
# Cũ:
clean_url = self._get_clean_image_url(image_url)
media_id = self._publish_photo(caption, clean_url)

# Mới:
media_id = self._publish_photo(caption, image_url)
```

- [ ] **Step 2: Xóa method `_get_clean_image_url`**

Xóa toàn bộ method `_get_clean_image_url` (khoảng 20 dòng) — không cần nữa.

- [ ] **Step 3: Bỏ import cloudinary**

Xóa 2 dòng import ở đầu file:

```python
# Xóa:
import cloudinary
import cloudinary.uploader
```

Và xóa block `cloudinary.config(...)` trong `__init__` (khoảng 6 dòng).

- [ ] **Step 4: Commit**

```bash
git add scraper/instagram_publisher.py
git commit -m "feat: instagram publisher uses pre-rendered image URL directly"
```

---

## Task 4: Test end-to-end và push

- [ ] **Step 1: Test visual creator locally**

```bash
cd scraper && python3 -c "
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
from visual_creator import VisualCreator
creator = VisualCreator()
stats = creator.process_pending(limit=1)
print(stats)
"
```

Expected: `processed: 1`, log cho thấy eager URL (bắt đầu `https://res.cloudinary.com/...`).

- [ ] **Step 2: Test instagram publisher locally**

```bash
cd scraper && python3 -c "
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
from instagram_publisher import InstagramPublisher
publisher = InstagramPublisher()
stats = publisher.push_pending_items(limit=1)
print(stats)
"
```

Expected: `pushed: 1`, post lên Instagram có text overlay trên ảnh.

- [ ] **Step 3: Verify trên Instagram**

Kiểm tra post mới trên https://www.instagram.com/isaacnguyen_w/ — ảnh phải có text overlay (brand + title + info).

- [ ] **Step 4: Push và deploy**

```bash
git push origin main
```

Render auto-deploy từ push.

- [ ] **Step 5: Test endpoint trên Render**

```bash
curl -sf -X POST "https://curator-api-hhau.onrender.com/run-visual" \
  -H "X-API-Key: $(grep '^API_SECRET_KEY=' .env | cut -d= -f2)" | python3 -m json.tool
```

Expected: `{"processed": N, "skipped": M, "errors": 0}`
