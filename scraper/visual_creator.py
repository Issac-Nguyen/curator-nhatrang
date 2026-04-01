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
                keywords = title[:30]

                # Priority: source image > Pexels
                photo_url = self._get_source_image_url(record)
                if not photo_url:
                    photo_url = self._get_pexels_photo_url(category, keywords)
                    time.sleep(0.5)  # respect Pexels rate limit

                public_id = f"nhatrang/{record_id}"
                image_url = self._upload_to_cloudinary(
                    photo_url, public_id, title, caption,
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

    def _get_source_image_url(self, record: dict) -> str | None:
        """Lấy Source Image URL từ Raw Item linked record."""
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

    def _upload_to_cloudinary(self, photo_url: str | None, public_id: str,
                              title: str = "", caption: str = "") -> str:
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
        img = self._render_text_overlay(img, title, caption)

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
    def _render_text_overlay(img: Image.Image, title: str, caption: str) -> Image.Image:
        """
        Bottom gradient info card overlay (~50% ảnh):
        - Gradient đen fade từ giữa xuống dưới
        - Brand "NHA TRANG CURATOR" (xanh lá)
        - Title (trắng, bold, max 3 dòng)
        - Caption/info (xám nhạt, max 3 dòng)
        """
        title = _strip_emoji(title)
        caption = _strip_emoji(caption)

        draw = ImageDraw.Draw(img, "RGBA")
        w, h = img.size

        # Gradient overlay (bottom 55%)
        gradient_start = int(h * 0.45)
        for y in range(gradient_start, h):
            progress = (y - gradient_start) / (h - gradient_start)
            alpha = int(220 * progress)
            draw.rectangle([(0, y), (w, y + 1)], fill=(0, 0, 0, alpha))

        draw = ImageDraw.Draw(img)
        try:
            font_brand = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            font_caption = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except OSError:
            try:
                font_brand = ImageFont.truetype("Arial Bold", 24)
                font_title = ImageFont.truetype("Arial Bold", 36)
                font_caption = ImageFont.truetype("Arial", 24)
            except OSError:
                font_brand = ImageFont.load_default()
                font_title = font_brand
                font_caption = font_brand

        margin = 40

        # Brand name (top of text area)
        draw.text((margin, h - 420), "NHA TRANG CURATOR", fill="#2d9e6b", font=font_brand)

        # Title (bold, max 3 lines)
        if title:
            _draw_wrapped_text(draw, title[:80], (margin, h - 380), font_title,
                               fill="white", max_width=w - 2 * margin)

        # Caption (max 3 lines)
        if caption:
            _draw_wrapped_text(draw, caption[:150], (margin, h - 200), font_caption,
                               fill="#cccccc", max_width=w - 2 * margin)

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
