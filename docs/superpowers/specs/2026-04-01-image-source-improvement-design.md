# Image Source Improvement — Design Spec

**Status:** Designed
**Date:** 2026-04-01

---

## Mục tiêu

Lấy ảnh chính xác cho Instagram posts bằng cách: (1) scrape og:image từ URL bài viết gốc khi crawl, (2) cải thiện Pexels search bằng summary_en thay vì title tiếng Việt.

---

## Vấn đề hiện tại

- Facebook (Apify) và RSS (Google News) không trả ảnh trong feed data
- Pexels search dùng `title[:30]` tiếng Việt + emoji → kết quả không liên quan (ví dụ: post về party DJ nhưng ảnh là người họp office)
- Field `Source Image URL` trong Raw Items luôn trống

---

## Giải pháp

### Priority chain chọn ảnh (trong visual_creator.py)

```
1. Source Image URL từ Raw Item (og:image — chính xác nhất)
2. Pexels search bằng summary_en (fallback — stock nhưng liên quan)
```

### 1. Scrape og:image khi crawl

Thêm helper function `_extract_og_image(url)` dùng chung cho cả RSS và Facebook:
- GET URL bài viết gốc (timeout 10s)
- Parse HTML, tìm `<meta property="og:image" content="...">`
- Return URL ảnh hoặc None
- Không dùng BeautifulSoup — regex đủ cho meta tag đơn giản

Gọi trong `rss_fetcher.fetch()` và `apify_fetcher._normalize()` trước khi append item.

Lưu kết quả vào field `source_image_url` → Airtable `Source Image URL`.

### 2. Cải thiện Pexels search

Trong `visual_creator.py`, thay đổi cách build Pexels query:
- Lấy `summary_en` từ AI Summary (JSON) trong Raw Item linked record
- Search: `"Nha Trang " + summary_en[:50]` (tiếng Anh)
- Fallback: dùng category + "Nha Trang" nếu không có summary_en

---

## Components thay đổi

### Helper function `_extract_og_image(url)` — dùng chung

```python
def _extract_og_image(url: str) -> str | None:
    resp = requests.get(url, timeout=10, headers={"User-Agent": "..."})
    match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', resp.text)
    return match.group(1) if match else None
```

### `scraper/rss_fetcher.py`

- Import helper
- Trong `fetch()`, sau extract content: gọi `_extract_og_image(entry_url)`
- Lưu vào `source_image_url` field (đã có trong items dict từ task trước)
- Try/except — nếu fail thì None, không block crawl

### `scraper/apify_fetcher.py`

- Import helper
- Trong `_normalize()`: nếu `imageUrl`/`fullPicture`/`picture` đều None → gọi `_extract_og_image(post_url)`
- Lưu vào `source_image_url`

### `scraper/visual_creator.py`

- Trong `process_pending()`: lấy `summary_en` từ Raw Item AI Summary
- Truyền `summary_en` vào `_get_pexels_photo_url()` thay vì `title[:30]`
- Sửa `_get_pexels_photo_url(category, keywords)`: keywords giờ là summary_en tiếng Anh

---

## Error Handling

| Lỗi | Xử lý |
|-----|-------|
| og:image URL timeout | Return None, fallback Pexels |
| og:image URL trả 403/404 | Return None |
| Trang không có og:image meta tag | Return None |
| AI Summary không có summary_en | Fallback Pexels với category + "Nha Trang" |
| Pexels không tìm được ảnh | Dùng placeholder gradient (giữ logic hiện tại) |

---

## Constraints

- `_extract_og_image` thêm 1 HTTP request/bài khi crawl (~200ms-2s)
- Timeout 10s cho og:image request — không block pipeline nếu trang chậm
- User-Agent header cần set để tránh bị block bởi news sites
- Regex cho og:image — không cần BeautifulSoup (tránh thêm dependency)
