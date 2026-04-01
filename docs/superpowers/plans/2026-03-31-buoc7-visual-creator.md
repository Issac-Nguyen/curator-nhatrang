# Bước 7: Visual Creator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Tự động tạo ảnh branded từ Pexels + Cloudinary transformations cho Content Queue items, update Airtable Image URL, Instagram Publisher dùng URL đó để đăng.

**Architecture:** Fetch ảnh Pexels gốc → upload lên Cloudinary → build Cloudinary transformation URL (crop + dark overlay + text layers) → lưu URL vào Airtable. Instagram Publisher dùng Image URL (clean, strip overlay) để publish.

**Tech Stack:** Python, cloudinary SDK, requests (Pexels API), AirtableClient (existing), Flask (existing).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `scraper/visual_creator.py` | Create | VisualCreator class: fetch Pexels, upload Cloudinary, build URL |
| `scraper/server.py` | Modify | Add `/run-visual` endpoint |
| `scraper/instagram_publisher.py` | Modify | Clean Image URL (strip overlay), publish via Instagram API |
| `scraper/requirements.txt` | Modify | Add `cloudinary>=1.36.0` |
| `render.yaml` | Modify | Add PEXELS_API_KEY, CLOUDINARY_* env vars |

---

## Task 1: Tạo Airtable field `Image URL` trong Content Queue

**Files:**
- No file changes — gọi Airtable Metadata API trực tiếp qua curl

- [x] **Step 1: Kiểm tra field `Image URL` đã tồn tại chưa**

```bash
curl -s "https://api.airtable.com/v0/meta/bases/app8VMuhpjzSw25YF/tables" \
  -H "Authorization: Bearer $(grep AIRTABLE_TOKEN .env | cut -d= -f2)" \
  | python3 -c "
import json,sys
data=json.load(sys.stdin)
tbl=[t for t in data['tables'] if t['id']=='tblwjOxiCWhUEoKEP'][0]
fields=[f['name'] for f in tbl['fields']]
print('Fields:', fields)
print('Has Image URL:', 'Image URL' in fields)
"
```

Expected: `Has Image URL: False` (nếu chưa có)

- [x] **Step 2: Tạo field `Image URL`**

```bash
curl -s -X POST "https://api.airtable.com/v0/meta/bases/app8VMuhpjzSw25YF/tables/tblwjOxiCWhUEoKEP/fields" \
  -H "Authorization: Bearer $(grep AIRTABLE_TOKEN .env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"name": "Image URL", "type": "url"}'
```

Expected: JSON response với `"name": "Image URL"` và `"type": "url"`

- [x] **Step 3: Verify field tồn tại**

Chạy lại lệnh Step 1, expected: `Has Image URL: True`

---

## Task 2: Thêm `cloudinary` vào requirements và render.yaml

**Files:**
- Modify: `scraper/requirements.txt`
- Modify: `render.yaml`

- [x] **Step 1: Thêm cloudinary vào requirements.txt**

File `scraper/requirements.txt` sau khi sửa:

```
feedparser==6.0.11
requests==2.31.0
python-dotenv==1.0.0
apscheduler==3.10.4
google-genai
groq
flask==3.0.3
gunicorn==22.0.0
cloudinary>=1.36.0
```

- [x] **Step 2: Thêm env vars vào render.yaml**

File `render.yaml` sau khi sửa (thêm 4 keys vào envVars):

```yaml
services:
  - type: web
    name: curator-api
    runtime: python
    rootDir: scraper
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn server:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1
    envVars:
      - key: AIRTABLE_TOKEN
        sync: false
      - key: APIFY_TOKEN
        sync: false
      - key: GROQ_API_KEY
        sync: false
      - key: API_SECRET_KEY
        sync: false
      - key: INSTAGRAM_ACCESS_TOKEN
        sync: false
      - key: INSTAGRAM_USER_ID
        sync: false
      - key: INSTAGRAM_APP_SECRET
        sync: false
      - key: PEXELS_API_KEY
        sync: false
      - key: CLOUDINARY_CLOUD_NAME
        sync: false
      - key: CLOUDINARY_API_KEY
        sync: false
      - key: CLOUDINARY_API_SECRET
        sync: false
```

- [x] **Step 3: Commit**

```bash
git add scraper/requirements.txt render.yaml
git commit -m "feat: add cloudinary dep and env vars for visual creator"
```

---

## Task 3: Tạo `visual_creator.py` — core logic

**Files:**
- Create: `scraper/visual_creator.py`

- [x] **Step 1: Tạo file với skeleton và test `_extract_text_parts`**

Tạo file `scraper/tests_visual.py` để test pure functions:

```python
"""Quick smoke tests cho visual_creator pure functions. Chạy: python scraper/tests_visual.py"""
import sys
sys.path.insert(0, "scraper")

from visual_creator import VisualCreator

vc = VisualCreator.__new__(VisualCreator)  # skip __init__

# Test 1: extract từ Draft VN có hashtags
record = {"fields": {
    "Draft VN": "Sao Thái mê bánh căn Nha Trang\n\nĐến Nha Trang là phải thử nước dừa tươi mát 🌴🍹\nBánh căn giòn rụm, chấm mắm nêm\n\n#NhaTrang #AmThuc #BanhCan",
    "Category": "Ẩm thực",
}}
title, caption, hashtags = vc._extract_text_parts(record)
assert "Sao Thái" in title, f"title wrong: {title}"
assert "nước dừa" in caption, f"caption wrong: {caption}"
assert "#NhaTrang" in hashtags, f"hashtags wrong: {hashtags}"
assert len(title) <= 60, f"title too long: {len(title)}"
print(f"✓ Test 1 passed: title={title!r}, hashtags={hashtags!r}")

# Test 2: Draft VN trống
record2 = {"fields": {"Draft VN": "", "Category": "Sự kiện"}}
result2 = vc._extract_text_parts(record2)
assert result2 == ("", "", ""), f"empty should return ('','',''): {result2}"
print("✓ Test 2 passed: empty Draft VN returns empty tuple")

# Test 3: build_image_url returns valid URL string
vc.cloud_name = "dxgq9cwkv"
url = vc._build_image_url("nhatrang/test123", "Bánh căn Nha Trang", "Thử ngay hôm nay 🍴", "#NhaTrang")
assert url.startswith("https://res.cloudinary.com/dxgq9cwkv/image/upload/"), f"bad URL: {url}"
assert "nhatrang/test123" in url, f"public_id missing: {url}"
print(f"✓ Test 3 passed: URL starts correctly")

print("\n✅ All tests passed")
```

- [x] **Step 2: Chạy test — phải fail (file chưa tồn tại)**

```bash
python scraper/tests_visual.py
```

Expected: `ModuleNotFoundError: No module named 'visual_creator'`

- [x] **Step 3: Tạo `scraper/visual_creator.py`**

```python
"""
Visual Creator — tạo ảnh branded cho Content Queue items.

Logic:
- Query Content Queue: Status=Approved AND Image URL trống
- Với mỗi item: fetch ảnh Pexels → upload Cloudinary → build transform URL
- Update Airtable: Image URL
- Không fail toàn run khi 1 item lỗi
"""
import logging
import os
import time
import urllib.parse
from pathlib import Path

import cloudinary
import cloudinary.uploader
import requests
from dotenv import load_dotenv

from airtable_client import AirtableClient

load_dotenv(Path(__file__).parent.parent / ".env")
log = logging.getLogger(__name__)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

PEXELS_API_BASE = "https://api.pexels.com/v1"


class VisualCreator:
    def __init__(self):
        missing = [
            k for k, v in {
                "PEXELS_API_KEY": PEXELS_API_KEY,
                "CLOUDINARY_CLOUD_NAME": CLOUDINARY_CLOUD_NAME,
                "CLOUDINARY_API_KEY": CLOUDINARY_API_KEY,
                "CLOUDINARY_API_SECRET": CLOUDINARY_API_SECRET,
            }.items() if not v
        ]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True,
        )
        self.cloud_name = CLOUDINARY_CLOUD_NAME
        self.client = AirtableClient()

    def process_pending(self, limit: int = 10) -> dict:
        """
        Fetch Content Queue items với Status=Approved và Image URL trống,
        tạo ảnh, update Airtable. Returns stats dict.
        """
        log.info("Fetching Content Queue items with Status=Approved and no Image URL...")
        records = self.client.get_records(
            "contentQueue",
            filter_formula='AND({Status}="Approved", {Image URL}="")',
            max_records=limit,
        )
        log.info(f"Found {len(records)} items to process")

        stats = {"processed": 0, "skipped": 0, "errors": 0}

        for record in records:
            record_id = record["id"]
            title_field = record["fields"].get("Title", "")[:40]

            draft_vn = record["fields"].get("Draft VN", "").strip()
            if not draft_vn:
                log.warning(f"  [Skip] {title_field} — no Draft VN")
                stats["skipped"] += 1
                continue

            try:
                title, caption, hashtags = self._extract_text_parts(record)
                category = record["fields"].get("Category", "")
                keywords = title[:30]

                photo_url = self._get_pexels_photo_url(category, keywords)
                time.sleep(0.5)  # respect Pexels rate limit

                public_id = f"nhatrang/{record_id}"
                self._upload_to_cloudinary(photo_url, public_id)

                image_url = self._build_image_url(public_id, title, caption, hashtags)

                self.client.update_record("contentQueue", record_id, {
                    "Image URL": image_url,
                })
                log.info(f"  [Done] {title_field}")
                stats["processed"] += 1

            except Exception as e:
                log.error(f"  [Error] {title_field}: {e}")
                stats["errors"] += 1

        log.info(f"Visual creator complete: {stats}")
        return stats

    def _get_pexels_photo_url(self, category: str, keywords: str) -> str | None:
        """Search Pexels for a photo. Returns URL of largest size or None."""
        query = f"{category} Nha Trang {keywords}".strip()
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": 1, "orientation": "square"}
        try:
            resp = requests.get(f"{PEXELS_API_BASE}/search", headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if not photos:
                log.warning(f"Pexels: no results for '{query}'")
                return None
            src = photos[0]["src"]
            return src.get("large2x") or src.get("large") or src.get("original")
        except Exception as e:
            log.warning(f"Pexels fetch failed: {e}")
            return None

    def _upload_to_cloudinary(self, photo_url: str | None, public_id: str) -> str:
        """
        Upload ảnh lên Cloudinary.
        Nếu photo_url là None: dùng placeholder gradient (public_id cố định).
        Retry 1 lần nếu lỗi. Returns public_id.
        """
        if photo_url is None:
            # Dùng placeholder đã upload sẵn — không upload lại
            log.info(f"No Pexels photo, using gradient placeholder for {public_id}")
            self._ensure_placeholder()
            return "nhatrang/placeholder"

        for attempt in range(2):
            try:
                result = cloudinary.uploader.upload(
                    photo_url,
                    public_id=public_id,
                    overwrite=True,
                    resource_type="image",
                )
                log.info(f"Uploaded to Cloudinary: {result['public_id']}")
                return result["public_id"]
            except Exception as e:
                if attempt == 0:
                    log.warning(f"Cloudinary upload attempt 1 failed: {e}, retrying...")
                    time.sleep(2)
                else:
                    raise RuntimeError(f"Cloudinary upload failed after retry: {e}")

    def _ensure_placeholder(self) -> None:
        """Upload gradient placeholder nếu chưa tồn tại."""
        try:
            # Check if exists
            import cloudinary.api
            cloudinary.api.resource("nhatrang/placeholder")
        except Exception:
            # Upload a solid color gradient via URL (public domain SVG → Cloudinary)
            gradient_url = (
                "https://res.cloudinary.com/demo/image/upload/"
                "e_colorize,co_rgb:1a6b4a/w_1080,h_1080/sample"
            )
            try:
                cloudinary.uploader.upload(
                    gradient_url,
                    public_id="nhatrang/placeholder",
                    overwrite=False,
                    resource_type="image",
                )
                log.info("Uploaded gradient placeholder to Cloudinary")
            except Exception as e:
                log.warning(f"Could not create placeholder: {e}")

    def _build_image_url(self, public_id: str, title: str, caption: str, hashtags: str) -> str:
        """
        Build Cloudinary transformation URL với text overlays.
        Text được URL-encoded đúng cách.
        """
        def enc(text: str) -> str:
            """URL-encode text cho Cloudinary overlay (encode slash và comma)."""
            return urllib.parse.quote(text, safe="")

        transformations = [
            "c_fill,w_1080,h_1080",         # crop vuông
            "e_brightness:-40",              # làm tối ảnh nền
        ]

        if title:
            t = enc(title[:55])
            transformations.append(
                f"l_text:DejaVu%20Sans_40_bold,co_rgb:ffffff,g_north_west,x_50,y_60,w_980,c_fit/{t}/fl_layer_apply"
            )

        if caption:
            c = enc(caption[:110])
            transformations.append(
                f"l_text:DejaVu%20Sans_28,co_rgb:dddddd,g_south_west,x_50,y_100,w_980,c_fit/{c}/fl_layer_apply"
            )

        if hashtags:
            h = enc(hashtags[:80])
            transformations.append(
                f"l_text:DejaVu%20Sans_24,co_rgb:2d9e6b,g_south_west,x_50,y_55,w_980,c_fit/{h}/fl_layer_apply"
            )

        # Brand tag cố định
        brand = enc("NHA TRANG")
        transformations.append(
            f"l_text:DejaVu%20Sans_22_bold,co_rgb:2d9e6b,g_north_west,x_50,y_20/{brand}/fl_layer_apply"
        )

        transform_str = "/".join(transformations)
        return f"https://res.cloudinary.com/{self.cloud_name}/image/upload/{transform_str}/{public_id}"

    def _extract_text_parts(self, record: dict) -> tuple[str, str, str]:
        """
        Parse Draft VN thành (title, caption, hashtags).
        - title: dòng đầu tiên không rỗng, truncate 60 chars
        - caption: các dòng tiếp theo không phải hashtag, join bằng space, truncate 120 chars
        - hashtags: dòng/cụm bắt đầu bằng '#', truncate 80 chars
        Returns ("", "", "") nếu Draft VN trống.
        """
        draft = record["fields"].get("Draft VN", "").strip()
        if not draft:
            return ("", "", "")

        lines = [l.strip() for l in draft.splitlines() if l.strip()]

        title = ""
        caption_lines = []
        hashtag_lines = []

        for i, line in enumerate(lines):
            if line.startswith("#"):
                hashtag_lines.append(line)
            elif i == 0 or not title:
                title = line
            else:
                caption_lines.append(line)

        title = title[:60]
        caption = " ".join(caption_lines)[:120]
        hashtags = " ".join(hashtag_lines)[:80]

        return (title, caption, hashtags)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    creator = VisualCreator()
    stats = creator.process_pending(limit=5)
    print(stats)
```

- [x] **Step 4: Chạy tests — phải pass**

```bash
python scraper/tests_visual.py
```

Expected:
```
✓ Test 1 passed: title='Sao Thái mê bánh căn Nha Trang', hashtags='#NhaTrang #AmThuc #BanhCan'
✓ Test 2 passed: empty Draft VN returns empty tuple
✓ Test 3 passed: URL starts correctly
✅ All tests passed
```

- [x] **Step 5: Commit**

```bash
git add scraper/visual_creator.py scraper/tests_visual.py
git commit -m "feat: add VisualCreator class with Pexels + Cloudinary transforms"
```

---

## Task 4: Thêm `/run-visual` endpoint vào server.py

**Files:**
- Modify: `scraper/server.py`

- [x] **Step 1: Thêm endpoint sau `/run-newsletter`**

Trong `scraper/server.py`, thêm sau block `run_newsletter`:

```python
@app.post("/run-visual")
def run_visual():
    err = _check_auth()
    if err:
        return err
    try:
        from visual_creator import VisualCreator
        creator = VisualCreator()
        stats = creator.process_pending(limit=10)
        log.info(f"/run-visual: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-visual error: {e}")
        return jsonify({"error": str(e)}), 500
```

- [x] **Step 2: Test endpoint locally**

```bash
cd /Users/phatnguyen/Projects/curator-nhatrang
API_SECRET_KEY="" python -c "
from scraper.server import app
with app.test_client() as c:
    resp = c.get('/health')
    print('health:', resp.json)
    # run-visual sẽ fail vì missing env vars nhưng endpoint phải exist
    resp2 = c.post('/run-visual')
    print('run-visual status:', resp2.status_code)
    print('run-visual body:', resp2.json)
"
```

Expected: `health: {'status': 'ok'}` và `run-visual status: 500` (endpoint exists, fails because no env vars locally)

- [x] **Step 3: Commit**

```bash
git add scraper/server.py
git commit -m "feat: add /run-visual endpoint"
```

---

## Task 5: Instagram Publisher dùng Image URL

**Note:** Đã chuyển từ Buffer sang Instagram Graph API (2026-04-01). Xem `scraper/instagram_publisher.py`.

- [x] **Step 1: InstagramPublisher clean Image URL**

`_get_clean_image_url()` strip Cloudinary text overlay → URL đơn giản `c_fill,w_1080,h_1080/{public_id}.jpg`.

- [x] **Step 2: Publish qua Instagram Graph API**

`_publish_photo()`: create container → wait 3s → publish. Lưu `ig:{media_id}` vào `Buffer ID` field.

- [x] **Step 3: Auto-refresh token**

`_refresh_token_if_needed()` tự refresh long-lived token (60 ngày) và cập nhật `.env`.

- [x] **Step 4: Test publish với ảnh**

```bash
cd scraper && python3 -c "
from instagram_publisher import InstagramPublisher
publisher = InstagramPublisher()
stats = publisher.push_pending_items(limit=1)
print(stats)
"
```

---

## Task 6: Push env vars lên Render và deploy

**Files:**
- No file changes — gọi Render API

- [x] **Step 1: Update env vars trên Render**

```bash
python3 << 'PYEOF'
import requests, os
from pathlib import Path

# Load .env
env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

SERVICE_ID = "srv-d75498ffte5s73bmgb00"
RENDER_API_KEY = env["RENDER_API_KEY"]

new_vars = [
    {"key": "PEXELS_API_KEY", "value": env["PEXELS_API_KEY"]},
    {"key": "CLOUDINARY_CLOUD_NAME", "value": env["CLOUDINARY_CLOUD_NAME"]},
    {"key": "CLOUDINARY_API_KEY", "value": env["CLOUDINARY_API_KEY"]},
    {"key": "CLOUDINARY_API_SECRET", "value": env["CLOUDINARY_API_SECRET"]},
]

# Get existing env vars
resp = requests.get(
    f"https://api.render.com/v1/services/{SERVICE_ID}/env-vars",
    headers={"Authorization": f"Bearer {RENDER_API_KEY}"},
)
existing = {item["envVar"]["key"]: item["envVar"]["value"] for item in resp.json()}
existing.update({v["key"]: v["value"] for v in new_vars})

all_vars = [{"key": k, "value": v} for k, v in existing.items()]
resp2 = requests.put(
    f"https://api.render.com/v1/services/{SERVICE_ID}/env-vars",
    headers={"Authorization": f"Bearer {RENDER_API_KEY}", "Content-Type": "application/json"},
    json=all_vars,
)
print("Status:", resp2.status_code)
print("OK" if resp2.status_code == 200 else resp2.text[:300])
PYEOF
```

Expected: `Status: 200` và `OK`

- [x] **Step 2: Trigger redeploy**

```bash
python3 << 'PYEOF'
import requests
from pathlib import Path

env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

SERVICE_ID = "srv-d75498ffte5s73bmgb00"
resp = requests.post(
    f"https://api.render.com/v1/services/{SERVICE_ID}/deploys",
    headers={"Authorization": f"Bearer {env['RENDER_API_KEY']}", "Content-Type": "application/json"},
    json={"clearCache": "do_not_clear"},
)
print("Deploy status:", resp.status_code)
print(resp.json().get("id", resp.text[:200]))
PYEOF
```

Expected: `Deploy status: 201` và deploy ID

- [x] **Step 3: Commit render.yaml**

```bash
git add render.yaml
git commit -m "chore: add Pexels and Cloudinary env vars to render.yaml"
```

---

## Task 7: Test end-to-end

**Files:**
- No changes

- [x] **Step 1: Đợi Render deploy xong (~3-5 phút)**

```bash
python3 << 'PYEOF'
import requests
from pathlib import Path

env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

resp = requests.get(
    f"{env['CURATOR_API_URL']}/health",
    headers={"X-API-Key": env["API_SECRET_KEY"]},
)
print("Health:", resp.json())
PYEOF
```

Expected: `Health: {'status': 'ok'}`

- [x] **Step 2: Chạy `/run-visual` thật**

```bash
python3 << 'PYEOF'
import requests
from pathlib import Path

env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

resp = requests.post(
    f"{env['CURATOR_API_URL']}/run-visual",
    headers={"X-API-Key": env["API_SECRET_KEY"]},
)
print("Status:", resp.status_code)
print("Result:", resp.json())
PYEOF
```

Expected: `{"processed": N, "skipped": M, "errors": 0}`

Nếu processed=0 và skipped=0: kiểm tra Airtable Content Queue có item nào Status=Approved không.

- [x] **Step 3: Kiểm tra Image URL trong Airtable**

Vào Airtable → Content Queue → tìm item vừa processed → copy Image URL → mở trong browser.

Expected: Ảnh 1080×1080 với text overlay hiển thị đúng.

- [x] **Step 4: Chạy `/run-instagram` với ảnh**

```bash
python3 << 'PYEOF'
import requests
from pathlib import Path

env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

resp = requests.post(
    f"{env['CURATOR_API_URL']}/run-instagram",
    headers={"X-API-Key": env["API_SECRET_KEY"]},
)
print("Status:", resp.status_code)
print("Result:", resp.json())
PYEOF
```

Expected: `{"pushed": N, "skipped": 0, "errors": 0}` và item Status=Scheduled trong Airtable.

---

## Task 8: Update n8n workflow

**Files:**
- n8n workflow (qua n8n UI tại https://curator-n8n.onrender.com)

- [x] **Step 1: Mở n8n và edit workflow hiện tại**

Vào https://curator-n8n.onrender.com → Workflows → mở workflow có `/run-instagram` node (trước đó là `/run-buffer`).

- [x] **Step 2: Thêm HTTP Request node `/run-visual`**

Thêm node mới **trước** node `/run-instagram`:
- Type: HTTP Request
- Method: POST
- URL: `{{$env.CURATOR_API_URL}}/run-visual` hoặc hardcode `https://curator-api-hhau.onrender.com/run-visual`
- Headers: `X-API-Key: {{$env.API_SECRET_KEY}}`
- Connect: node trước → `/run-visual` → `/run-instagram`

- [x] **Step 3: Test workflow**

Chạy manual trigger → kiểm tra tất cả nodes màu xanh.

Expected: `/run-visual` node trả `{"processed": N, ...}`, rồi `/run-instagram` chạy tiếp.

- [x] **Step 4: Save và Activate workflow**

Click Save → đảm bảo Active toggle ON.
