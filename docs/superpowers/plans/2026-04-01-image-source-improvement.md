# Image Source Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lấy ảnh chính xác hơn cho Instagram posts: og:image từ URL gốc khi crawl, Pexels search bằng tiếng Anh thay tiếng Việt.

**Architecture:** Helper function `extract_og_image(url)` dùng chung cho RSS + Facebook scrapers. Visual creator lấy `summary_en` từ AI Summary làm Pexels search keywords.

**Tech Stack:** Python, requests, regex, feedparser, Airtable REST API

---

## File Map

```
scraper/
  og_image.py              CREATE  helper function extract_og_image(url)
  rss_fetcher.py           MODIFY  gọi extract_og_image khi crawl
  apify_fetcher.py         MODIFY  fallback extract_og_image nếu post không có ảnh
  visual_creator.py        MODIFY  Pexels search dùng summary_en, lấy summary_en từ Raw Item
```

---

## Task 1: Tạo og_image helper module

**Files:**
- Create: `scraper/og_image.py`

- [ ] **Step 1: Tạo og_image.py**

```python
"""Extract og:image from article URLs."""
import logging
import re

import requests

log = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; NhaTrangCurator/1.0)"


def extract_og_image(url: str) -> str | None:
    """
    Fetch URL and extract <meta property="og:image" content="..."> value.
    Returns image URL or None. Never raises — logs warnings on failure.
    """
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        # Try both attribute orders: property then content, or content then property
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']',
            resp.text[:50000],  # only scan first 50KB
        )
        if not match:
            match = re.search(
                r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:image["\']',
                resp.text[:50000],
            )
        if match:
            img_url = match.group(1).strip()
            if img_url.startswith("http"):
                log.debug(f"  og:image found: {img_url[:80]}...")
                return img_url
        return None
    except Exception as e:
        log.debug(f"  og:image extraction failed for {url[:60]}: {e}")
        return None
```

- [ ] **Step 2: Commit**

```bash
git add scraper/og_image.py
git commit -m "feat: add og_image helper to extract og:image from article URLs"
```

---

## Task 2: RSS fetcher dùng og:image

**Files:**
- Modify: `scraper/rss_fetcher.py`

- [ ] **Step 1: Thêm import và gọi extract_og_image**

Thêm import ở đầu file (sau `import feedparser`):

```python
from og_image import extract_og_image
```

Trong `fetch()`, sau block extract image từ enclosures/media_content/links (line 72-93), thêm og:image fallback trước `items.append`:

```python
        # Fallback: extract og:image from article URL
        if not image_url:
            image_url = extract_og_image(entry_url)
```

Đặt giữa dòng 93 (end of links block) và dòng 95 (`items.append`).

- [ ] **Step 2: Commit**

```bash
git add scraper/rss_fetcher.py
git commit -m "feat: rss fetcher extracts og:image from article URLs"
```

---

## Task 3: Apify fetcher dùng og:image

**Files:**
- Modify: `scraper/apify_fetcher.py`

- [ ] **Step 1: Thêm import và fallback og:image**

Thêm import ở đầu file (sau `from pathlib import Path`):

```python
from og_image import extract_og_image
```

Trong `_normalize()`, sau block extract `source_image_url` (line 118-122), thêm fallback:

```python
        # Fallback: extract og:image from post URL
        if not source_image_url:
            post_url = self._get_url(post)
            if post_url:
                source_image_url = extract_og_image(post_url)
```

Đặt giữa dòng 122 (end of source_image_url block) và dòng 124 (`return {`).

- [ ] **Step 2: Commit**

```bash
git add scraper/apify_fetcher.py
git commit -m "feat: apify fetcher falls back to og:image from post URLs"
```

---

## Task 4: Visual creator dùng summary_en cho Pexels

**Files:**
- Modify: `scraper/visual_creator.py`

- [ ] **Step 1: Sửa `_get_source_image_url` để cũng trả summary_en**

Thay method `_get_source_image_url` (line 165-178) để trả cả image URL và summary_en:

```python
    def _get_raw_item_data(self, record: dict) -> tuple[str | None, str]:
        """
        Lấy Source Image URL và summary_en từ Raw Item linked record.
        Returns (image_url, summary_en).
        """
        raw_item_ids = record["fields"].get("Raw Item", [])
        if not raw_item_ids:
            return None, ""
        raw_records = self.client.get_records(
            "rawItems",
            filter_formula=f'RECORD_ID()="{raw_item_ids[0]}"',
            max_records=1,
        )
        if not raw_records:
            return None, ""
        fields = raw_records[0]["fields"]

        # Source image
        img_url = fields.get("Source Image URL", "").strip() or None
        if img_url:
            log.info(f"  Found source image: {img_url[:80]}...")

        # summary_en from AI Summary JSON
        summary_en = ""
        ai_summary = fields.get("AI Summary", "")
        if ai_summary:
            try:
                import json
                data = json.loads(ai_summary)
                summary_en = data.get("summary_en", "")
            except Exception:
                pass

        return img_url, summary_en
```

- [ ] **Step 2: Sửa `process_pending` để dùng `_get_raw_item_data`**

Thay block trong `process_pending` (lines 118-127):

```python
            try:
                title, caption, hashtags = self._extract_text_parts(record)
                category = record["fields"].get("Category", "")

                # Get source image + summary_en from Raw Item
                source_img, summary_en = self._get_raw_item_data(record)

                # Priority: source image > Pexels (with English keywords)
                photo_url = source_img
                if not photo_url:
                    pexels_keywords = summary_en[:50] if summary_en else category
                    photo_url = self._get_pexels_photo_url(pexels_keywords)
                    time.sleep(0.5)  # respect Pexels rate limit

                public_id = f"nhatrang/{record_id}"
                image_url = self._upload_to_cloudinary(
                    photo_url, public_id, title, caption,
                )
```

- [ ] **Step 3: Sửa `_get_pexels_photo_url` — bỏ param category**

Thay signature và query build (lines 147-149):

```python
    def _get_pexels_photo_url(self, keywords: str) -> str | None:
        """Search Pexels for a photo. Returns URL of largest size or None."""
        query = f"Nha Trang {keywords}".strip()
```

Phần còn lại giữ nguyên.

- [ ] **Step 4: Commit**

```bash
git add scraper/visual_creator.py
git commit -m "feat: visual creator uses summary_en for Pexels search, gets raw item data"
```

---

## Task 5: Test và push

- [ ] **Step 1: Test og:image extraction**

```bash
cd scraper && python3 -c "
from og_image import extract_og_image
# Test with a Vietnamese news article
url = 'https://vnexpress.net'
result = extract_og_image(url)
print(f'og:image: {result}')
"
```

Expected: một URL ảnh (hoặc None nếu trang chính không có og:image).

- [ ] **Step 2: Test Pexels search với summary_en**

```bash
cd scraper && python3 -c "
import os
from dotenv import load_dotenv
load_dotenv('../.env')
import requests

query = 'Nha Trang party DJ nightlife celebration'
resp = requests.get('https://api.pexels.com/v1/search',
    headers={'Authorization': os.getenv('PEXELS_API_KEY')},
    params={'query': query, 'per_page': 1, 'orientation': 'square'})
photos = resp.json().get('photos', [])
if photos:
    print(f'Alt: {photos[0].get(\"alt\", \"\")[:80]}')
    print(f'URL: {photos[0][\"src\"][\"medium\"][:80]}')
else:
    print('No results')
"
```

Expected: ảnh liên quan đến party/nightlife thay vì office meeting.

- [ ] **Step 3: Push và deploy**

```bash
git push origin main
```
