# Smart Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured data extraction to AI Processor and render category-specific overlays on Instagram images.

**Architecture:** AI Processor extracts event_date, event_time, price, address, opening_hours into AI Summary JSON. Visual Creator reads these fields + category from Raw Item, dispatches to category-specific Pillow render functions that draw date badges, price badges, category tags, and info pills.

**Tech Stack:** Python, Pillow (PIL), Groq (llama-3.3-70b), Cloudinary

---

### Task 1: Add structured fields to AI Processor SYSTEM_PROMPT

**Files:**
- Modify: `scraper/ai_processor.py:30-59` (SYSTEM_PROMPT)

- [ ] **Step 1: Update SYSTEM_PROMPT**

In `scraper/ai_processor.py`, replace the existing `SYSTEM_PROMPT` string (lines 30-59) with:

```python
SYSTEM_PROMPT = """Bạn là AI assistant cho kênh Instagram curator về Nha Trang (du lịch, ẩm thực, địa điểm, sự kiện TẠI NHA TRANG / KHÁNH HÒA).

Bạn sẽ nhận một danh sách bài viết dạng JSON array. Với mỗi bài, phân tích và trả về JSON array tương ứng:
[
  {
    "id": "<id của bài>",
    "relevant": true/false,
    "reason": "lý do nếu không relevant",
    "category": "Sự kiện|Địa điểm|Ẩm thực|Tin tức|Workshop|Khác",
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
- Nếu không có thông tin → để null.
- price: giữ nguyên format gốc từ bài (500K, 45.000đ, từ 200K, free, miễn phí).
- event_date: chuyển sang dd/mm hoặc dd/mm/yyyy.
- opening_hours: format HH:MM-HH:MM hoặc giữ nguyên từ bài.

keywords: PHẢI bằng tiếng Anh, mô tả nội dung ảnh phù hợp (dùng cho tìm ảnh stock). Ví dụ: ["beach sunset", "Vietnamese street food", "night market"]

content_potential cao (high) khi: địa điểm cụ thể ở Nha Trang, món ăn đặc sắc Nha Trang, sự kiện đang diễn ra, có thông tin chi tiết (giá, địa chỉ, giờ).

Chỉ trả về JSON array, không có text khác."""
```

- [ ] **Step 2: Increase max_tokens for longer output**

In `scraper/ai_processor.py`, in the `_analyze_batch` method (around line 89), change `max_tokens=2000` to `max_tokens=3000`:

```python
            temperature=0.2,
            max_tokens=3000,
```

- [ ] **Step 3: Commit**

```bash
git add scraper/ai_processor.py
git commit -m "feat: add structured fields (date, price, address) to AI processor prompt"
```

---

### Task 2: Update `_get_raw_item_data` to return full AI Summary dict

**Files:**
- Modify: `scraper/visual_creator.py:168-201`

Currently `_get_raw_item_data` returns `(image_url, summary_en)`. We need the full AI Summary dict for category + structured fields.

- [ ] **Step 1: Change return type to include AI Summary dict**

In `scraper/visual_creator.py`, replace the `_get_raw_item_data` method (lines 168-201) with:

```python
    def _get_raw_item_data(self, record: dict) -> tuple[str | None, dict]:
        """
        Lấy Source Image URL và AI Summary dict từ Raw Item linked record.
        Returns (image_url, ai_summary_dict).
        """
        raw_item_ids = record["fields"].get("Raw Item", [])
        if not raw_item_ids:
            return None, {}
        raw_records = self.client.get_records(
            "rawItems",
            filter_formula=f'RECORD_ID()="{raw_item_ids[0]}"',
            max_records=1,
        )
        if not raw_records:
            return None, {}
        fields = raw_records[0]["fields"]

        # Source image
        img_url = fields.get("Source Image URL", "").strip() or None
        if img_url:
            log.info(f"  Found source image: {img_url[:80]}...")

        # Parse AI Summary JSON
        ai_data = {}
        ai_summary = fields.get("AI Summary", "")
        if ai_summary:
            try:
                import json
                ai_data = json.loads(ai_summary)
            except Exception:
                pass

        return img_url, ai_data
```

- [ ] **Step 2: Update `process_pending` to use new return type**

In `scraper/visual_creator.py`, in the `process_pending` method, replace lines 122-135 (from `# Get source image` to `_upload_to_cloudinary` call) with:

```python
                # Get source image + AI summary from Raw Item
                source_img, ai_data = self._get_raw_item_data(record)

                # Chỉ dùng source image, skip nếu không có
                photo_url = source_img
                if not photo_url:
                    log.warning(f"  [Skip] {title_field} — no source image")
                    stats["skipped"] += 1
                    continue

                # Use category from AI data, fallback to Content Queue field
                overlay_category = ai_data.get("category", "") or category

                public_id = f"nhatrang/{record_id}"
                image_url = self._upload_to_cloudinary(
                    photo_url, public_id, title, overlay_category, ai_data,
                )
```

- [ ] **Step 3: Commit**

```bash
git add scraper/visual_creator.py
git commit -m "refactor: _get_raw_item_data returns full AI summary dict"
```

---

### Task 3: Replace `_render_text_overlay` with category-aware overlay

**Files:**
- Modify: `scraper/visual_creator.py`

This replaces the old `_render_text_overlay` static method and updates `_upload_to_cloudinary` to call the new rendering.

- [ ] **Step 1: Add category config constants**

At the top of `visual_creator.py`, after the existing imports and before the `_strip_emoji` function (around line 36), add:

```python
# Category overlay config: (tag_text, tag_color_hex, badge_type)
# badge_type: "date", "price", or None
CATEGORY_CONFIG = {
    "Sự kiện":  ("SỰ KIỆN",  "#e74c3c", "date"),
    "Ẩm thực":  ("ẨM THỰC",  "#e67e22", "price"),
    "Địa điểm": ("ĐỊA ĐIỂM", "#3498db", None),
    "Workshop":  ("WORKSHOP",  "#9b59b6", "date"),
    "Tin tức":   ("TIN TỨC",   "#95a5a6", None),
    "Khác":      ("KHÁC",      "#95a5a6", None),
}

# Info pills per category: list of (icon, field_key) tuples
CATEGORY_PILLS = {
    "Sự kiện":  [("🕐", "event_time"), ("📍", "address"), ("💰", "price")],
    "Ẩm thực":  [("📍", "address"), ("🕐", "opening_hours")],
    "Địa điểm": [("📍", "address"), ("🕐", "opening_hours"), ("💰", "price")],
    "Workshop":  [("🕐", "event_time"), ("📍", "address"), ("💰", "price")],
    "Tin tức":   [("📍", "address")],
    "Khác":      [("📍", "address")],
}

MONTHS_VN = ["", "THG 1", "THG 2", "THG 3", "THG 4", "THG 5", "THG 6",
             "THG 7", "THG 8", "THG 9", "THG 10", "THG 11", "THG 12"]
```

- [ ] **Step 2: Replace `_render_text_overlay` with `_render_overlay`**

In `scraper/visual_creator.py`, replace the entire `_render_text_overlay` static method (lines 262-313) with:

```python
    @staticmethod
    def _render_overlay(img: Image.Image, title: str, category: str, ai_data: dict) -> Image.Image:
        """
        Render category-aware overlay:
        - Category tag (top-left)
        - Date or price badge (top-right, category-dependent)
        - Bottom gradient with brand, title, info pills
        """
        title = _strip_emoji(title)
        draw = ImageDraw.Draw(img, "RGBA")
        w, h = img.size

        # Load fonts
        try:
            font_brand = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
            font_pill = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
            font_tag = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            font_badge_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
            font_badge_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except OSError:
            try:
                font_brand = ImageFont.truetype("Arial Bold", 20)
                font_title = ImageFont.truetype("Arial Bold", 32)
                font_pill = ImageFont.truetype("Arial", 22)
                font_tag = ImageFont.truetype("Arial Bold", 18)
                font_badge_big = ImageFont.truetype("Arial Bold", 48)
                font_badge_sm = ImageFont.truetype("Arial", 16)
            except OSError:
                font_brand = ImageFont.load_default()
                font_title = font_brand
                font_pill = font_brand
                font_tag = font_brand
                font_badge_big = font_brand
                font_badge_sm = font_brand

        config = CATEGORY_CONFIG.get(category, CATEGORY_CONFIG["Khác"])
        tag_text, tag_color, badge_type = config

        margin = 32

        # --- Category tag (top-left) ---
        tag_bbox = draw.textbbox((0, 0), tag_text, font=font_tag)
        tag_w = tag_bbox[2] - tag_bbox[0] + 20
        tag_h = tag_bbox[3] - tag_bbox[1] + 12
        draw.rounded_rectangle(
            [(margin, margin), (margin + tag_w, margin + tag_h)],
            radius=tag_h // 2,
            fill=tag_color,
        )
        draw.text((margin + 10, margin + 4), tag_text, fill="white", font=font_tag)

        # --- Badge (top-right) ---
        if badge_type == "date":
            event_date = ai_data.get("event_date", "")
            if event_date:
                parts = event_date.split("/")
                day = parts[0] if parts else ""
                month_idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                month_str = MONTHS_VN[month_idx] if 0 < month_idx <= 12 else ""
                if day:
                    badge_w, badge_h = 80, 76
                    bx = w - margin - badge_w
                    by = margin
                    draw.rounded_rectangle(
                        [(bx, by), (bx + badge_w, by + badge_h)],
                        radius=10,
                        fill=(0, 0, 0, 180),
                    )
                    day_bbox = draw.textbbox((0, 0), day, font=font_badge_big)
                    day_w = day_bbox[2] - day_bbox[0]
                    draw.text((bx + (badge_w - day_w) // 2, by + 2), day, fill="white", font=font_badge_big)
                    if month_str:
                        mo_bbox = draw.textbbox((0, 0), month_str, font=font_badge_sm)
                        mo_w = mo_bbox[2] - mo_bbox[0]
                        draw.text((bx + (badge_w - mo_w) // 2, by + 54), month_str, fill="#cccccc", font=font_badge_sm)

        elif badge_type == "price":
            price = ai_data.get("price", "")
            if price:
                price_text = price if price.startswith("từ") else f"từ {price}" if len(price) < 10 else price
                pb = draw.textbbox((0, 0), price_text, font=font_tag)
                pw = pb[2] - pb[0] + 24
                ph = pb[3] - pb[1] + 14
                px = w - margin - pw
                py = margin
                draw.rounded_rectangle(
                    [(px, py), (px + pw, py + ph)],
                    radius=10,
                    fill="#e67e22",
                )
                draw.text((px + 12, py + 5), price_text, fill="white", font=font_tag)

        # --- Bottom gradient ---
        gradient_start = int(h * 0.45)
        for y in range(gradient_start, h):
            progress = (y - gradient_start) / (h - gradient_start)
            alpha = int(235 * progress)
            draw.rectangle([(0, y), (w, y + 1)], fill=(0, 0, 0, alpha))

        # Switch to non-RGBA draw for text on gradient
        draw = ImageDraw.Draw(img)
        text_bottom = h - 28

        # --- Info pills ---
        pills_config = CATEGORY_PILLS.get(category, CATEGORY_PILLS["Khác"])
        pills = []
        for icon, key in pills_config:
            val = ai_data.get(key, "")
            if val:
                pills.append((icon, val, key == "price"))

        if pills:
            pill_y = text_bottom - 24
            pill_x = margin
            for icon, val, is_price in pills:
                text = f"{icon} {val}"
                color = "#f39c12" if is_price else "#aaaaaa"
                draw.text((pill_x, pill_y), _strip_emoji(val), fill=color, font=font_pill)
                bbox = draw.textbbox((0, 0), _strip_emoji(val), font=font_pill)
                pill_x += (bbox[2] - bbox[0]) + 28
            text_bottom = pill_y - 12

        # --- Title ---
        if title:
            title_y = text_bottom - 40
            _draw_wrapped_text(draw, title[:60], (margin, title_y), font_title,
                               fill="white", max_width=w - 2 * margin)
            text_bottom = title_y - 8

        # --- Brand ---
        draw.text((margin, text_bottom - 20), "NHA TRANG CURATOR", fill="#2d9e6b", font=font_brand)

        return img
```

- [ ] **Step 3: Update `_upload_to_cloudinary` signature and call**

In `scraper/visual_creator.py`, replace the `_upload_to_cloudinary` method signature and the rendering call. Change the method from:

```python
    def _upload_to_cloudinary(self, photo_url: str | None, public_id: str,
                              title: str = "", caption: str = "") -> str:
```

to:

```python
    def _upload_to_cloudinary(self, photo_url: str | None, public_id: str,
                              title: str = "", category: str = "", ai_data: dict = None) -> str:
```

And inside that method, replace the line:

```python
        img = self._render_text_overlay(img, title, caption)
```

with:

```python
        img = self._render_overlay(img, title, category, ai_data or {})
```

- [ ] **Step 4: Remove old `_render_text_overlay` method**

Delete the old `_render_text_overlay` static method entirely (it was replaced in Step 2).

- [ ] **Step 5: Commit**

```bash
git add scraper/visual_creator.py
git commit -m "feat: category-aware overlay with date badges, price badges, and info pills"
```

---

### Task 4: Test full pipeline locally

**Files:** None (manual test)

- [ ] **Step 1: Test AI Processor with a sample post**

Run a quick test to verify the AI processor returns structured fields. Wait for Groq rate limit to reset if needed.

```bash
cd /Users/phatnguyen/Projects/curator-nhatrang
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scraper')
from ai_processor import AIProcessor
import json

processor = AIProcessor()
# Process just the existing raw items
stats = processor.process_new_items(limit=3)
print(json.dumps(stats, indent=2))
"
```

Expected: items processed with new fields (event_date, price, etc.) in AI Summary.

- [ ] **Step 2: Check AI Summary contains structured fields**

```bash
.venv/bin/python -c "
import sys, json; sys.path.insert(0, 'scraper')
from airtable_client import AirtableClient
client = AirtableClient()
records = client.get_records('rawItems', filter_formula='{Status}=\"Use\"', max_records=3)
for r in records:
    summary = r['fields'].get('AI Summary', '')
    if summary:
        data = json.loads(summary)
        print(f'Title: {r[\"fields\"].get(\"Title\",\"\")[:50]}')
        print(f'  category: {data.get(\"category\")}')
        print(f'  event_date: {data.get(\"event_date\")}')
        print(f'  price: {data.get(\"price\")}')
        print(f'  address: {data.get(\"address\")}')
        print()
"
```

Expected: structured fields populated where available, null where not.

- [ ] **Step 3: Test Visual Creator overlay rendering**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scraper')
from visual_creator import VisualCreator
creator = VisualCreator()
stats = creator.process_pending(limit=1)
print(stats)
"
```

Expected: `{'processed': 1, ...}` — check Airtable for the generated image URL and verify the overlay looks correct.

- [ ] **Step 4: Commit and push**

```bash
git push
```

This deploys to Render automatically.
