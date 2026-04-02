# Smart Overlay — Category-aware Instagram visuals

## Problem

Visual Creator hiện render cùng 1 layout cho tất cả content: brand + title + caption. Không có thông tin cụ thể (ngày, giờ, giá, địa chỉ) nên ảnh Instagram thiếu giá trị thông tin cho người xem.

## Solution

Thêm structured data extraction vào AI Processor và render overlay khác nhau theo category trong Visual Creator.

## Changes

### 1. AI Processor — `ai_processor.py`

Thêm 5 fields vào SYSTEM_PROMPT output schema (tất cả nullable):

```json
{
  "event_date": "dd/mm hoặc dd/mm/yyyy — ngày sự kiện/workshop",
  "event_time": "HH:MM — giờ bắt đầu",
  "price": "string — giá gốc từ bài viết (ví dụ: 500K, 45.000đ, from 200K)",
  "address": "string — địa chỉ cụ thể",
  "opening_hours": "string — giờ mở cửa (ví dụ: 6:00–21:00)"
}
```

AI chỉ điền khi thông tin có trong bài viết. Không bịa.

### 2. Visual Creator — `visual_creator.py`

Thay `_render_text_overlay(img, title, caption)` bằng `_render_overlay(img, category, title, fields)` với dispatcher theo category.

**Chung cho tất cả layout:**
- Bottom gradient overlay (45% → 100% opacity)
- Brand text "NHA TRANG CURATOR" (color `#2d9e6b`, size 9px equivalent, letter-spacing 2px)
- Title (white, bold, max 2 dòng, 60 chars)
- Info pills row: icon + text, color `#aaaaaa`, giá color `#f39c12` bold
- Category tag top-left: rounded pill, color theo bảng dưới

**Category-specific:**

| Category | Tag | Tag color | Top-right badge | Badge content |
|----------|-----|-----------|-----------------|---------------|
| Sự kiện | SỰ KIỆN | `#e74c3c` | Date badge (dark bg) | Ngày to + tháng nhỏ |
| Ẩm thực | ẨM THỰC | `#e67e22` | Price badge (cam bg) | "từ XXK" |
| Địa điểm | ĐỊA ĐIỂM | `#3498db` | Không | — |
| Workshop | WORKSHOP | `#9b59b6` | Date badge (dark bg) | Ngày to + tháng nhỏ |
| Tin tức/Khác | TIN TỨC | `#95a5a6` | Không | — |

**Info pills hiển thị theo category:**

- Sự kiện: 🕐 event_time · 📍 address · 💰 price
- Ẩm thực: 📍 address · 🕐 opening_hours
- Địa điểm: 📍 address · 🕐 opening_hours · 💰 price
- Workshop: 🕐 event_time · 📍 address · 💰 price

Chỉ render pill nếu field có giá trị (not null/empty).

### 3. Data flow

```
Raw Item (Content)
  → AI Processor: extract category + structured fields → AI Summary JSON
  → Content Queue: Status=Approved
  → Visual Creator: read AI Summary → dispatch layout by category → render Pillow overlay
  → Cloudinary upload → Image URL
  → Instagram Publisher: publish
```

Visual Creator đọc structured fields từ Raw Item's AI Summary JSON (đã có code `_get_raw_item_data` trả `ai_summary`).

### 4. Fallback behavior

- Field null/empty → không render pill đó
- Category không nhận diện → dùng layout Địa điểm (generic nhất)
- AI Summary không parse được → render layout cũ (title + caption only)
- Không có title → skip item

### 5. Files to modify

1. `scraper/ai_processor.py` — thêm fields vào SYSTEM_PROMPT
2. `scraper/visual_creator.py` — thay `_render_text_overlay`, thêm category-specific render functions

Không cần thay đổi Airtable schema — structured data nằm trong AI Summary JSON field.
