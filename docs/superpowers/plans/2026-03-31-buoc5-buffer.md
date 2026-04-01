# Bước 5: Instagram Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Tự động push Content Queue items (Status=Approved) lên Instagram qua Instagram Graph API mỗi 30 phút.

**Architecture:** `InstagramPublisher` class query Airtable lấy items Approved chưa có Buffer ID, auto-refresh token, clean Cloudinary URL, gọi Instagram API (create container → publish), update Airtable với Status=Scheduled và `ig:{media_id}`. Flask endpoint `/run-instagram` expose class này. n8n workflow poll mỗi 30 phút và gửi Telegram khi xong.

**Tech Stack:** Python, requests, Instagram Graph API v22.0, Cloudinary, Airtable REST API, Flask, n8n

**Note:** Ban đầu dùng Buffer API nhưng Buffer đã ngừng hỗ trợ developer apps mới. Đã chuyển sang Instagram Graph API trực tiếp (2026-04-01).

---

## File Map

```
scraper/
  instagram_publisher.py  CREATE  InstagramPublisher class + token auto-refresh
  server.py               MODIFY  thêm /run-instagram và /refresh-instagram-token endpoints

.env                      MODIFY  thêm 4 biến Instagram
```

---

## Task 1: Chuẩn bị Instagram credentials

**Files:**
- Modify: `.env`

- [x] **Step 1: Tạo Meta App và Instagram API setup**

Vào Meta Developer Console → App "Nha trang - curator" → Use cases → Instagram API → API setup with Instagram login. Cần Instagram App ID và App Secret.

- [x] **Step 2: Lấy Access Token qua OAuth flow**

Chạy OAuth flow: authorize → exchange code → short-lived token → long-lived token (60 ngày).

- [x] **Step 3: Thêm vào .env**

```
INSTAGRAM_APP_ID=4504736839853185
INSTAGRAM_APP_SECRET=...
INSTAGRAM_USER_ID=27052054527731009
INSTAGRAM_ACCESS_TOKEN=... (long-lived, 60 ngày)
```

- [x] **Step 4: Verify Instagram API hoạt động**

```bash
curl "https://graph.instagram.com/v22.0/me?fields=user_id,username&access_token=$INSTAGRAM_ACCESS_TOKEN"
# Expect: {"user_id": "...", "username": "isaacnguyen_w"}
```

---

## Task 2: Tạo InstagramPublisher class

**Files:**
- Create: `scraper/instagram_publisher.py`

- [x] **Step 1: Tạo instagram_publisher.py**

Class gồm:
- Token auto-refresh (`_refresh_token_if_needed`, `_update_env_token`)
- `push_pending_items(limit)` — query Airtable → clean image → publish → update status
- `_build_caption(record)` — ghép Draft VN + Draft EN
- `_get_clean_image_url(image_url)` — strip Cloudinary text overlay → URL đơn giản
- `_publish_photo(caption, image_url)` — create container → wait 3s → publish

- [x] **Step 2: Test publish 1 item**

```bash
cd scraper && python3 -c "
from instagram_publisher import InstagramPublisher
publisher = InstagramPublisher()
stats = publisher.push_pending_items(limit=1)
print(stats)
"
```

- [x] **Step 3: Verify trên Instagram**

Kiểm tra post xuất hiện trên Instagram account isaacnguyen_w.

- [x] **Step 4: Verify Airtable update**

Item phải có Status=Scheduled và Buffer ID = `ig:{media_id}`.

---

## Task 3: Thêm endpoints vào server.py

**Files:**
- Modify: `scraper/server.py`

- [x] **Step 1: Thêm 2 endpoints**

```python
@app.post("/run-instagram")           # publish pending items
@app.post("/refresh-instagram-token")  # manual token refresh
```

- [x] **Step 2: Test endpoints locally**

```bash
curl -X POST http://localhost:8000/run-instagram -H "X-API-Key: $API_SECRET_KEY"
curl -X POST http://localhost:8000/refresh-instagram-token -H "X-API-Key: $API_SECRET_KEY"
```

---

## Task 4: Deploy lên Render

- [x] **Step 1: Push env vars lên Render**

Thêm `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN` vào Render environment.

- [x] **Step 2: Deploy và test**

```bash
curl -X POST https://curator-api-hhau.onrender.com/run-instagram -H "X-API-Key: $API_SECRET_KEY"
```

---

## Task 5: Update n8n workflow

- [x] **Step 1: Thay /run-buffer bằng /run-instagram**

Trong n8n workflow "Buffer Publisher" (hoặc rename thành "Instagram Publisher"):
- HTTP Request node: đổi URL từ `/run-buffer` sang `/run-instagram`
- Telegram message: đổi "Buffer" thành "Instagram"

- [x] **Step 2: Thêm token refresh schedule (optional)**

Tạo workflow mới chạy weekly gọi `/refresh-instagram-token` để đảm bảo token luôn fresh.

- [x] **Step 3: Xác nhận hoàn tất**

Kiểm tra Instagram Publisher workflow hoạt động đúng: n8n trigger → /run-instagram → Airtable status updated.

---

## Ghi chú kỹ thuật

- **Token refresh:** Long-lived token hết hạn sau 60 ngày. `InstagramPublisher.__init__()` tự gọi refresh mỗi lần khởi tạo. Token mới được ghi lại vào `.env` tự động.
- **Cloudinary URL:** Visual Creator tạo URL với text overlay phức tạp (tiếng Việt). Instagram API không thể download URL này. Publisher strip overlay và dùng URL ảnh gốc `c_fill,w_1080,h_1080/{public_id}.jpg`.
- **Rate limit:** Instagram cho phép 50 posts/24h. Publisher có `time.sleep(2)` giữa mỗi post.
- **Dedup:** Lưu `ig:{media_id}` vào field `Buffer ID` trước khi update Status.
- **Container processing:** Instagram cần ~3s để process image container trước khi publish.
