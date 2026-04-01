# Bước 5: Instagram Publisher — Design Spec

**Status:** Implemented  
**Date:** 2026-03-31 (updated 2026-04-01: chuyển từ Buffer sang Instagram Graph API)

---

## Mục tiêu

Tự động push Content Queue items (Status=Approved) lên Instagram qua Instagram Graph API (Content Publishing). n8n poll mỗi 30 phút, gọi `/run-instagram` endpoint, Python xử lý Instagram API + cập nhật Airtable.

---

## Kiến trúc

```
n8n (every 30 min)
  → POST /run-instagram (curator-api)
      → InstagramPublisher (auto-refresh token nếu gần hết hạn)
          → Airtable: query Content Queue (Status=Approved, Buffer ID trống)
          → loop items:
              → Cloudinary: clean image URL (strip text overlay)
              → Instagram API: create media container (image + caption)
              → Instagram API: publish container
              → Airtable: update Status=Scheduled, Buffer ID = ig:{media_id}
      → return {pushed: N, errors: M}
  → Telegram: "✅ Instagram: pushed N items"
```

---

## Components

### `InstagramPublisher` (`scraper/instagram_publisher.py`)

Class xử lý Instagram Graph API calls và Airtable updates.

**Methods:**
- `__init__()` — auto-refresh token via `_refresh_token_if_needed()`, load `INSTAGRAM_ACCESS_TOKEN` và `INSTAGRAM_USER_ID` từ `.env`, config Cloudinary. Raise `RuntimeError` nếu thiếu env vars.
- `push_pending_items(limit=20)` — fetch Content Queue records với `Status=Approved`, `Image URL` có, và `Buffer ID` trống. Loop qua từng item, gọi `_publish_photo()`, trả về stats dict.
- `_build_caption(record)` — ghép `Draft VN` + `"\n\n"` + `Draft EN`. Return empty string nếu cả 2 đều trống.
- `_get_clean_image_url(image_url)` — strip Cloudinary text overlay transformations, build URL đơn giản `c_fill,w_1080,h_1080/{public_id}.jpg`.
- `_publish_photo(caption, image_url)` — 2 bước: create container → publish. Return media ID.

**Token auto-refresh:**
- `_refresh_token_if_needed()` — gọi `GET /refresh_access_token?grant_type=ig_refresh_token`, cập nhật `.env` tự động.
- `_update_env_token(new_token)` — regex replace `INSTAGRAM_ACCESS_TOKEN` trong `.env`.

**Instagram API calls:**
```
Step 1: POST https://graph.instagram.com/v22.0/{ig_user_id}/media
        Body: image_url, caption, access_token
        → Returns: container_id

Step 2: POST https://graph.instagram.com/v22.0/{ig_user_id}/media_publish
        Body: creation_id={container_id}, access_token
        → Returns: media_id
```

### `server.py` — endpoints

```python
@app.post("/run-instagram")    # publish Content Queue items
@app.post("/refresh-instagram-token")  # manual token refresh
```

### n8n Workflow "Instagram Publisher"

- **Schedule Trigger:** mỗi 30 phút
- **HTTP Request node:** `POST {CURATOR_API_URL}/run-instagram`
- **Telegram node:** `✅ Instagram: pushed {{ $json.pushed }} items | errors: {{ $json.errors }}`

---

## Airtable Changes

Content Queue table:
- **Field `Buffer ID`** (Single line text) — lưu `ig:{media_id}` sau khi publish thành công (reuse field cũ cho dedup)
- **Status option `Scheduled`** — thêm vào Single Select

Status flow:
```
Approved → (n8n Instagram Publisher) → Scheduled → (manual) → Done
```

---

## Caption & Image

**Caption:** `{Draft VN}\n\n{Draft EN}`  
- Nếu cả 2 trống → skip item, log warning  

**Image:** Cloudinary URL từ `Image URL` field.
- Complex transformation URLs (text overlay tiếng Việt) → strip thành clean URL chỉ với `c_fill,w_1080,h_1080`
- Instagram yêu cầu JPEG, 1080x1080, public URL

---

## Error Handling

| Lỗi | Behavior |
|-----|----------|
| Instagram API 400 | Log error chi tiết, tiếp tục item tiếp |
| Token hết hạn | Auto-refresh trước khi publish |
| Token refresh fail | Log warning, dùng token cũ |
| Item không có caption | Skip item, log warning |
| Item không có image | Skip item, log warning |
| `INSTAGRAM_ACCESS_TOKEN` không set | Raise `RuntimeError` khi khởi tạo |

**Không fail toàn run khi 1 item lỗi** — xử lý được bao nhiêu tốt bấy nhiêu.

---

## Environment Variables

```
INSTAGRAM_APP_ID=4504736839853185
INSTAGRAM_APP_SECRET=...
INSTAGRAM_USER_ID=27052054527731009
INSTAGRAM_ACCESS_TOKEN=... (auto-refreshed, 60 ngày)
```

---

## Constraints

- Instagram cho phép 50 posts/24h — `limit=20` mỗi run
- Long-lived token hết hạn sau 60 ngày — auto-refresh mỗi lần publish
- Container cần ~3s để process trước khi publish
- Cloudinary text overlay URLs không hoạt động với Instagram API → cần strip transformations
- Dedup: lưu `ig:{media_id}` vào `Buffer ID` field trước khi update Status
