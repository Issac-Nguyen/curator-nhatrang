# Pre-rendered Text on Image — Design Spec

**Status:** Designed
**Date:** 2026-04-01

---

## Mục tiêu

Render text trực tiếp lên ảnh trước khi publish Instagram, tạo "info card" style thu hút hơn ảnh stock trơn. Đồng thời ưu tiên dùng ảnh từ nguồn gốc (Facebook/RSS) thay vì Pexels stock.

---

## Vấn đề hiện tại

1. `visual_creator.py` tạo Cloudinary transformation URL với text overlay → Instagram API không download được URL phức tạp → `instagram_publisher.py` phải strip overlay → ảnh publish không có text
2. Ảnh Pexels stock generic, không liên quan trực tiếp đến nội dung
3. Scrapers không extract ảnh từ nguồn gốc

---

## Giải pháp

### 1. Ảnh nguồn gốc (Source Image)

Thêm field `Source Image URL` vào Raw Items table. Scrapers extract ảnh khi crawl:

- **RSS**: lấy từ `entry.enclosures`, `entry.media_content`, hoặc `entry.links` có type `image/*`
- **Facebook (Apify)**: lấy từ field `imageUrl` hoặc `fullPicture` trong Apify response

Priority khi chọn ảnh cho visual:
1. Source Image URL (từ nguồn gốc) — link qua Raw Item trong Content Queue
2. Pexels search (fallback) — giữ logic hiện tại

### 2. Pre-rendered text via Cloudinary Eager

Thay vì lưu transformation URL, dùng `eager` parameter khi upload để Cloudinary pre-render ảnh thành file JPEG tĩnh.

**Layout: Bottom Gradient Info Card**

```
┌─────────────────────────┐
│                         │
│     [Ảnh sáng]          │  60% trên
│                         │
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  gradient fade
│ NHA TRANG CURATOR       │  xanh lá #2d9e6b, 13px
│ Title bold trắng        │  trắng, 40px bold
│ ☕ Info bullet 1         │  xám #cccccc, 24px
│ 📍 Info bullet 2         │
│ ⭐ Info bullet 3         │  40% dưới
└─────────────────────────┘
```

**Eager transformation chain:**

```python
eager = [{
    "transformation": [
        {"width": 1080, "height": 1080, "crop": "fill"},
        # Gradient overlay (dark bottom)
        {"effect": "gradient_fade:symmetric_pad", "y": 0.6},
        # hoặc dùng brightness cho đơn giản:
        # Brand name
        {"overlay": {"font_family": "Arial", "font_size": 26, "font_weight": "bold",
                     "text": "NHA TRANG CURATOR"},
         "color": "#2d9e6b", "gravity": "south_west", "x": 50, "y": 280},
        {"flags": "layer_apply"},
        # Title
        {"overlay": {"font_family": "Arial", "font_size": 40, "font_weight": "bold",
                     "text": title},
         "color": "#ffffff", "gravity": "south_west", "x": 50, "y": 160,
         "width": 980, "crop": "fit"},
        {"flags": "layer_apply"},
        # Info line
        {"overlay": {"font_family": "Arial", "font_size": 24,
                     "text": info_text},
         "color": "#cccccc", "gravity": "south_west", "x": 50, "y": 50,
         "width": 980, "crop": "fit"},
        {"flags": "layer_apply"},
    ]
}]
```

Upload trả về `eager[0]["secure_url"]` — URL ảnh JPEG đã render sẵn → lưu vào Airtable `Image URL`.

---

## Components thay đổi

### `scraper/rss_fetcher.py` — extract ảnh từ RSS

Thêm logic extract image URL từ entry:
- `entry.enclosures` (type image/*)
- `entry.media_content` 
- `entry.links` (rel=enclosure, type image/*)
- Lưu vào field `Source Image URL` khi tạo Raw Item record

### `scraper/apify_fetcher.py` — extract ảnh từ Facebook

Apify Facebook scraper trả về `imageUrl` hoặc `fullPicture`. Lưu vào `Source Image URL`.

### `scraper/visual_creator.py` — sửa logic chính

**Thay đổi `_get_image_url()`** (thay thế `_get_pexels_photo_url()`):
1. Check Raw Item linked record → `Source Image URL`
2. Nếu không có → fallback Pexels search (giữ nguyên logic cũ)

**Thay đổi `_upload_to_cloudinary()`:**
- Thêm `eager` parameter với text overlay transformations
- Return `eager[0]["secure_url"]` thay vì `public_id`

**Bỏ `_build_image_url()`** — không cần nữa vì eager URL đã có text.

### `scraper/instagram_publisher.py` — đơn giản hóa

**Bỏ `_get_clean_image_url()`** — Image URL từ Airtable giờ là eager URL sạch, dùng trực tiếp.

---

## Airtable Changes

### Raw Items — thêm field
- `Source Image URL` (URL type) — ảnh gốc từ nguồn RSS/Facebook

### Content Queue — không thay đổi
- `Image URL` vẫn giữ nguyên, chỉ giá trị khác (eager URL thay vì transformation URL)

---

## Text Content cho Overlay

Lấy từ `_extract_text_parts()` hiện tại (đã có):
- **Brand**: "NHA TRANG CURATOR" (hardcoded)
- **Title**: dòng đầu tiên Draft VN (max 55 chars)
- **Info**: 2-3 dòng tiếp theo Draft VN (max 110 chars)

---

## Error Handling

| Lỗi | Xử lý |
|-----|-------|
| Source Image URL không accessible | Fallback Pexels |
| Pexels không tìm được ảnh | Upload placeholder gradient |
| Cloudinary eager fail | Retry 1 lần, nếu vẫn fail → skip item |
| Text quá dài cho overlay | Truncate (đã có trong `_extract_text_parts`) |
| Tiếng Việt Unicode trong eager | Cloudinary hỗ trợ — đã test OK với Arial font |

---

## Constraints

- Cloudinary eager: async=False (đợi render xong) — chậm hơn ~2-3s/ảnh nhưng đảm bảo URL sẵn sàng
- Font: Arial (có sẵn trên Cloudinary, hỗ trợ Unicode/tiếng Việt)
- Kích thước: 1080x1080 (Instagram square format)
- Gradient: dùng brightness:-40 cho phần dưới hoặc `gradient_fade` effect
