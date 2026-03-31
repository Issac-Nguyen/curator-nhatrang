# Bước 7: Visual Creator — Design Spec (v2)

## Goal

Tự động tạo ảnh branded (1080×1080) từ Content Queue items có Status=Approved và chưa có Image URL. Dùng Pexels làm ảnh nền, upload lên Cloudinary, dùng Cloudinary URL transformations để overlay text — không cần Pillow hay moviepy local. Lưu Image URL vào Airtable để Buffer dùng khi đăng TikTok (photo) và Instagram.

## Pipeline Flow

```
Content Queue (Status=Approved, no Image URL)
  → Pexels: search ảnh theo category + "Nha Trang"
  → Cloudinary: upload ảnh gốc từ Pexels URL
  → Cloudinary URL: generate transformation URL (crop + dark overlay + text)
  → Airtable: update Image URL
```

Buffer sau đó đọc Image URL → đăng Instagram (photo) + TikTok (photo post).

**Không dùng:** Pillow, moviepy, local image processing.

## Architecture

- **`scraper/visual_creator.py`** — VisualCreator class
- **`/run-visual` endpoint** trong `scraper/server.py`
- **1 Airtable field mới** trong Content Queue: `Image URL`
- **Buffer Publisher update** — dùng `Image URL` cho cả Instagram lẫn TikTok

## How Cloudinary Transformations Work

Upload ảnh Pexels gốc lên Cloudinary → nhận `public_id`. Sau đó tạo URL transformation:

```
https://res.cloudinary.com/{cloud_name}/image/upload/
  c_fill,w_1080,h_1080/
  e_brightness:-40/
  l_text:DejaVu Sans_22_bold_white:✦ NHA TRANG ✦,g_north_west,x_40,y_40,co_rgb:2d9e6b/
  l_text:DejaVu Sans_48_bold_white:{title},g_north_west,x_40,y_90,w_1000,c_fit/
  l_text:DejaVu Sans_28_white:{caption},g_south_west,x_40,y_80,w_1000,c_fit/
  l_text:DejaVu Sans_22_white:{hashtags},g_south_west,x_40,y_40,co_rgb:2d9e6b/
  {public_id}
```

Text được URL-encode trước khi nhúng vào URL.

## Components

### VisualCreator class (`scraper/visual_creator.py`)

**Methods:**

- `process_pending(limit=10)` → `{"processed": N, "skipped": M, "errors": E}`
  - Query: `AND({Status}="Approved", {Image URL}="")`
  - Với mỗi item: fetch Pexels URL → upload → build transform URL → update Airtable
  - Không fail toàn run khi 1 item lỗi

- `_get_pexels_photo_url(category: str, keywords: str)` → `str | None`
  - Search query: `f"{category} Nha Trang {keywords}"`
  - Trả về URL ảnh gốc (large2x hoặc large)
  - Fallback None nếu không tìm được

- `_upload_to_cloudinary(photo_url: str | None, public_id: str)` → `str`
  - Nếu photo_url: `cloudinary.uploader.upload(photo_url, public_id=public_id)`
  - Nếu None (Pexels fail): upload gradient image mặc định (tạo sẵn 1 lần)
  - Retry 1 lần nếu lỗi
  - Trả về public_id đã upload

- `_build_image_url(public_id: str, record: dict)` → `str`
  - Tạo Cloudinary transformation URL từ public_id + text layers
  - Text được lấy từ Draft VN: title (dòng 1) + caption (2-3 dòng tiếp) + hashtags cuối
  - URL-encode tất cả text trước khi nhúng vào URL

- `_extract_text_parts(record: dict)` → `(title, caption, hashtags)`
  - Parse Draft VN: dòng 1 → title, dòng 2-4 → caption, tìm `#` → hashtags
  - Truncate title < 60 ký tự, caption < 120 ký tự

### Flask endpoint

```python
@app.post("/run-visual")
def run_visual():
    err = _check_auth()
    if err: return err
    try:
        from visual_creator import VisualCreator
        creator = VisualCreator()
        stats = creator.process_pending(limit=10)
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-visual error: {e}")
        return jsonify({"error": str(e)}), 500
```

### Airtable — 1 field mới

Tạo field `Image URL` (type: `url`) trong Content Queue qua Metadata API.

### Buffer Publisher update (`scraper/buffer_publisher.py`)

- Filter thêm `{Image URL}!=""` — chỉ push items đã có ảnh
- Gửi `media[picture]` = Image URL cho cả TikTok lẫn Instagram
- TikTok nhận photo post thay vì video (ok cho giai đoạn hiện tại)

### n8n workflow

Thêm HTTP Request node `/run-visual` trước `/run-buffer`.

## Text Layout

```
┌─────────────────────────┐
│ ✦ NHA TRANG ✦  (xanh lá)│  g_north_west, y=40
│                         │
│ [Title, bold, white]    │  g_north_west, y=90
│                         │
│                         │
│ [Caption 2-3 dòng]      │  g_south_west, y=80
│ #Hashtags  (xanh lá)    │  g_south_west, y=40
└─────────────────────────┘
[brightness -40% làm tối ảnh nền]
```

## Error Handling

| Lỗi | Xử lý |
|-----|-------|
| Pexels không tìm được ảnh | Upload placeholder gradient (pre-uploaded) |
| Cloudinary upload lỗi | Retry 1 lần, nếu vẫn lỗi: skip item |
| Draft VN trống | Skip item, log warning |
| Cloudinary API error | Catch, skip item, không crash toàn run |

## Constraints

- Pexels: sleep 500ms giữa các request (200 req/giờ free tier)
- Cloudinary: không lưu processed image (transformation URL on-the-fly) → tiết kiệm storage
- Cloudinary: text URL-encoded đúng cách (urllib.parse.quote)
- Tiếng Việt: Cloudinary hỗ trợ Unicode text overlay
- process_pending limit=10 để tránh timeout Render

## Env Vars

```
PEXELS_API_KEY=Ey7Vm0Jl6BfhrO7hKPF8EgA9KyBswDFAZHe1om55IeX5xAvd9xOVa7ea
CLOUDINARY_CLOUD_NAME=dxgq9cwkv
CLOUDINARY_API_KEY=427642655239869
CLOUDINARY_API_SECRET=nZCVeTTqp9lfbnDQyyHXlbCeonA
```

## Dependencies mới (`requirements.txt`)

```
cloudinary>=1.36.0
```

(Không cần Pillow hay moviepy)
