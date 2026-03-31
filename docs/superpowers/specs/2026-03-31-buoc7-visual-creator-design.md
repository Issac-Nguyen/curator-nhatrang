# Bước 7: Visual Creator — Design Spec

## Goal

Tự động tạo ảnh (1080×1080) và video (1080×1920, 7 giây) từ Content Queue items có Status=Approved và chưa có Image URL/Video URL. Upload lên Cloudinary, lưu URLs vào Airtable để Buffer dùng khi đăng TikTok và Instagram.

## Pipeline Flow

```
Content Queue (Status=Approved, no Image URL)
  → Pexels: search ảnh theo category + "Nha Trang"
  → Pillow: tạo ảnh 1080×1080 với text overlay
  → moviepy: tạo video 1080×1920, 7 giây, slow zoom-in
  → Cloudinary: upload image + video
  → Airtable: update Image URL + Video URL
```

Sau đó `/run-buffer` đọc Video URL → TikTok, Image URL → Instagram.

## Architecture

- **`scraper/visual_creator.py`** — VisualCreator class, chạy toàn bộ pipeline
- **`/run-visual` endpoint** trong `scraper/server.py` — trigger từ n8n hoặc manual
- **2 Airtable fields mới** trong Content Queue: `Image URL`, `Video URL`
- **Buffer Publisher update** — dùng `Image URL` cho Instagram, `Video URL` cho TikTok

## Components

### VisualCreator class (`scraper/visual_creator.py`)

**Methods:**

- `process_pending(limit=10)` → `{"processed": N, "skipped": M, "errors": E}`
  - Query Content Queue: `AND({Status}="Approved", {Image URL}="")`
  - Với mỗi item: fetch ảnh → tạo Instagram image → tạo TikTok video → upload → update Airtable
  - Không fail toàn run khi 1 item lỗi

- `_fetch_pexels_photo(category: str, keywords: str)` → `PIL.Image | None`
  - Search query: `f"{category} Nha Trang {keywords}"`
  - Lấy ảnh đầu tiên, download và trả về PIL.Image
  - Fallback None nếu không tìm được

- `_create_instagram_image(photo: PIL.Image | None, record: dict)` → `bytes`
  - Output: 1080×1080 JPEG
  - Nếu photo là None: dùng gradient xanh lá → xanh dương làm background
  - Text overlay layers:
    1. Brand tag: `✦ NHA TRANG ✦` (nhỏ, xanh lá, trên cùng)
    2. Title: `Draft VN` (bold, 2 dòng)
    3. Caption: 2-3 dòng đầu của `Draft VN`
    4. Hashtags: màu xanh lá, bottom

- `_create_tiktok_image(photo: PIL.Image | None, record: dict)` → `PIL.Image`
  - Output: 1080×1920 với cùng text overlay layout (tỉ lệ điều chỉnh)

- `_create_tiktok_video(base_image: PIL.Image, record: dict)` → `bytes`
  - Output: MP4, 1080×1920, 7 giây, 24fps
  - Effect: slow zoom-in từ 1.0x → 1.15x (Ken Burns effect)
  - Audio: silent
  - Dùng moviepy ImageSequenceClip hoặc VideoClip

- `_upload_to_cloudinary(data: bytes, resource_type: str, public_id: str)` → `str`
  - resource_type: `"image"` hoặc `"video"`
  - Return Cloudinary secure URL
  - Retry 1 lần nếu lỗi

- `_draw_text_overlay(img: PIL.Image, record: dict, size: tuple)` → `PIL.Image`
  - Vẽ dark overlay (rgba 0,0,0,0.5) lên toàn ảnh
  - Vẽ gradient line (xanh lá → xanh dương) ở bottom
  - Vẽ 4 text layers với font DejaVuSans (hỗ trợ Unicode/tiếng Việt)

### Flask endpoint (`scraper/server.py`)

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

### Airtable — fields mới

Tạo 2 fields trong Content Queue qua Metadata API (như đã làm với "Buffer ID"):
- `Image URL` — type: `url`
- `Video URL` — type: `url`

### Buffer Publisher update (`scraper/buffer_publisher.py`)

Cập nhật `push_pending_items` filter: thêm điều kiện `{Image URL}!=""` (chỉ push items đã có media).

Cập nhật `_push_to_buffer` để gửi media:
- Instagram: `media[picture]` = Image URL
- TikTok: upload video qua Buffer media API trước, rồi attach vào post

### n8n workflow update

Thêm HTTP Request node gọi `POST /run-visual` (với API_SECRET_KEY header) trước node `/run-buffer` trong workflow hiện tại.

## Text Overlay Design

Layout (Full overlay — style A):
```
[dark overlay trên toàn ảnh]
┌─────────────────────────┐
│ ✦ NHA TRANG ✦           │  ← brand tag, xanh lá, nhỏ
│                         │
│ [Title bold, 2 dòng]    │  ← Draft VN title
│                         │
│ [Caption 2-3 dòng]      │  ← đầu Draft VN
│                         │
│ #NhaTrang #AmThuc       │  ← hashtags xanh lá
└─────────────────────────┘
[gradient line: xanh lá → xanh dương]
```

Font: DejaVuSans (built-in Linux/Mac, hỗ trợ tiếng Việt)

## Error Handling

| Lỗi | Xử lý |
|-----|-------|
| Pexels không tìm được ảnh | Fallback gradient background, tiếp tục |
| Cloudinary upload lỗi | Retry 1 lần, nếu vẫn lỗi: skip item, log error |
| Draft VN trống | Skip item, log warning |
| moviepy/Pillow exception | Catch, skip item, không crash toàn run |
| Airtable update lỗi | Log error, không retry (tránh duplicate) |

## Constraints

- Pexels free tier: 200 req/giờ → sleep 500ms giữa các request
- Cloudinary free tier: 25 credits/tháng, max 10MB/image, 100MB/video
- Render RAM: moviepy cần ~512MB → process trong temp dir, xóa file sau upload
- Font tiếng Việt: dùng DejaVuSans hoặc download Noto Sans VN nếu cần
- process_pending limit=10 để tránh timeout Render (30s)

## Env Vars

```
PEXELS_API_KEY=Ey7Vm0Jl6BfhrO7hKPF8EgA9KyBswDFAZHe1om55IeX5xAvd9xOVa7ea
CLOUDINARY_CLOUD_NAME=dxgq9cwkv
CLOUDINARY_API_KEY=427642655239869
CLOUDINARY_API_SECRET=nZCVeTTqp9lfbnDQyyHXlbCeonA
```

## Tech Stack

- **Pillow** (PIL) — image creation, text overlay
- **moviepy** — image to video, zoom effect
- **cloudinary** Python SDK — upload
- **requests** — Pexels API calls
- **python-dotenv** — env vars

## Dependencies mới cần thêm vào requirements.txt

```
Pillow>=10.0.0
moviepy>=1.0.3
cloudinary>=1.36.0
```
