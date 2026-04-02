"""
Visual Creator — tạo ảnh branded cho Content Queue items.

Logic:
- Query Content Queue: Status=Approved AND Image URL trống
- Với mỗi item: lấy ảnh nguồn (priority) hoặc Pexels (fallback)
  → upload Cloudinary với eager transforms (pre-render text overlay)
  → lưu eager URL (ảnh JPEG đã render) vào Airtable
- Không fail toàn run khi 1 item lỗi
"""
import io
import logging
import os
import re
import time
from pathlib import Path

import cloudinary
import cloudinary.uploader
import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

from airtable_client import AirtableClient

load_dotenv(Path(__file__).parent.parent / ".env")
log = logging.getLogger(__name__)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

PEXELS_API_BASE = "https://api.pexels.com/v1"

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


def _strip_emoji(text: str) -> str:
    """Remove emoji characters that can't be rendered by standard fonts."""
    return re.sub(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF'
        r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF'
        r'\U0000FE0F\U0000200D]+', '', text
    ).strip()


def _draw_wrapped_text(draw, text, pos, font, fill, max_width):
    """Draw text with word wrapping."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    x, y = pos
    for line in lines[:4]:  # max 4 lines
        draw.text((x, y), line, fill=fill, font=font)
        bbox = draw.textbbox((0, 0), line, font=font)
        y += bbox[3] - bbox[1] + 6


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

    def _get_pexels_photo_url(self, keywords: str) -> str | None:
        """Search Pexels for a photo using English keywords. Returns URL or None."""
        query = f"Nha Trang {keywords}".strip()
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

    def _upload_to_cloudinary(self, photo_url: str | None, public_id: str,
                              title: str = "", category: str = "", ai_data: dict = None) -> str:
        """
        Download ảnh, render text overlay bằng Pillow, upload lên Cloudinary.
        Cloudinary text overlay không hỗ trợ tiếng Việt có dấu → dùng Pillow.
        Returns clean secure_url.
        """
        if photo_url is None:
            log.info(f"No photo, using gradient placeholder for {public_id}")
            self._ensure_placeholder()
            photo_url = f"https://res.cloudinary.com/{self.cloud_name}/image/upload/nhatrang/placeholder"

        # Step 1: Download ảnh
        resp = requests.get(photo_url, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")

        # Step 2: Crop/resize to 1080x1080
        img = self._crop_square(img, 1080)

        # Step 3: Render text overlay
        img = self._render_overlay(img, title, category, ai_data or {})

        # Step 4: Upload to Cloudinary
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)

        for attempt in range(2):
            try:
                result = cloudinary.uploader.upload(
                    buf,
                    public_id=public_id,
                    overwrite=True,
                    resource_type="image",
                    format="jpg",
                )
                url = result["secure_url"]
                log.info(f"  Uploaded rendered image: {url[:80]}...")
                return url
            except Exception as e:
                if attempt == 0:
                    log.warning(f"Upload attempt 1 failed: {e}, retrying...")
                    buf.seek(0)
                    time.sleep(2)
                else:
                    raise RuntimeError(f"Cloudinary upload failed after retry: {e}")

    @staticmethod
    def _crop_square(img: Image.Image, size: int) -> Image.Image:
        """Center crop to square, then resize."""
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        return img.resize((size, size), Image.LANCZOS)

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

    def _ensure_placeholder(self) -> None:
        """Upload gradient placeholder nếu chưa tồn tại."""
        try:
            import cloudinary.api
            cloudinary.api.resource("nhatrang/placeholder")
        except Exception:
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

    def _extract_text_parts(self, record: dict) -> tuple[str, str, str]:
        """
        Parse Draft VN thành (title, caption, hashtags).
        - title: dòng đầu tiên không phải hashtag, truncate 60 chars
        - caption: các dòng tiếp theo không phải hashtag, join bằng space, truncate 120 chars
        - hashtags: dòng bắt đầu bằng '#', truncate 80 chars
        Returns ("", "", "") nếu Draft VN trống.
        """
        draft = record["fields"].get("Draft VN", "").strip()
        if not draft:
            return ("", "", "")

        lines = [l.strip() for l in draft.splitlines() if l.strip()]

        title = ""
        caption_lines = []
        hashtag_lines = []
        title_set = False

        for line in lines:
            if line.startswith("#"):
                hashtag_lines.append(line)
            elif not title_set:
                title = line
                title_set = True
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
