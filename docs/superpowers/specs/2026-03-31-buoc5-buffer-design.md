# Bước 5: Buffer Publisher — Design Spec

**Status:** Designed  
**Date:** 2026-03-31

---

## Mục tiêu

Tự động push Content Queue items (Status=Approved) lên Buffer để schedule đăng TikTok và Instagram. n8n poll mỗi 30 phút, gọi `/run-buffer` endpoint, Python xử lý Buffer API + cập nhật Airtable.

---

## Kiến trúc

```
n8n (every 30 min)
  → POST /run-buffer (curator-api)
      → BufferPublisher.push_pending_items()
          → Airtable: query Content Queue (Status=Approved, Buffer ID trống)
          → loop items:
              → Buffer API: create update cho TikTok profile
              → Buffer API: create update cho Instagram profile
              → Airtable: update Status=Scheduled, Buffer ID
      → return {pushed: N, errors: M}
  → Telegram: "✅ Buffer: pushed N items"
```

---

## Components

### `BufferPublisher` (`scraper/buffer_publisher.py`)

Class xử lý Buffer API calls và Airtable updates.

**Methods:**
- `__init__()` — load `BUFFER_ACCESS_TOKEN` từ `.env`, raise `RuntimeError` nếu không set. Load Buffer profile IDs cho TikTok và Instagram từ `.env` (`BUFFER_TIKTOK_PROFILE_ID`, `BUFFER_INSTAGRAM_PROFILE_ID`).
- `push_pending_items(limit=20)` — fetch Content Queue records với `Status=Approved` và `Buffer ID` trống, loop qua từng item, gọi `_push_item()`, trả về stats dict.
- `_push_item(record)` — push 1 item lên cả TikTok và Instagram profiles. Return `(success, buffer_id)`.
- `_build_caption(record)` — ghép `Draft VN` + `"\n\n"` + `Draft EN`. Return empty string nếu cả 2 đều trống.
- `_get_link(record)` — lấy `Affiliate link` nếu có, fallback về URL từ Raw Item linked record.

**Buffer API call:**
```
POST https://api.bufferapp.com/1/updates/create.json
Authorization: Bearer {BUFFER_ACCESS_TOKEN}
Body: profile_ids[]=..., text=..., shorten=false
```

Push lên cả 2 profiles trong 1 lần call bằng cách pass cả 2 profile_ids. Buffer trả về array updates — lưu `updates[0].id` làm `Buffer ID` trong Airtable để dedup.

### `server.py` — endpoint `/run-buffer`

```python
@app.route("/run-buffer", methods=["POST"])
def run_buffer():
    publisher = BufferPublisher()
    stats = publisher.push_pending_items(limit=20)
    return jsonify(stats)
```

### n8n Workflow "Buffer Publisher"

- **Schedule Trigger:** mỗi 30 phút
- **HTTP Request node:** `POST {CURATOR_API_URL}/run-buffer`
- **Telegram node:** `✅ Buffer: pushed {{ $json.pushed }} items | errors: {{ $json.errors }}`

---

## Airtable Changes

Content Queue table cần thêm:
- **Field `Buffer ID`** (Single line text) — lưu Buffer update ID sau khi push thành công
- **Status option `Scheduled`** — thêm vào Single Select (hiện có: Draft/Editing/Approved/Done)

Status flow sau khi có Buffer:
```
Approved → (n8n Buffer Publisher) → Scheduled → (manual) → Done
```

---

## Caption & Link

**Caption:** `{Draft VN}\n\n{Draft EN}`  
- Nếu cả 2 trống → skip item, log warning  
- Không truncate — Buffer tự handle nếu quá dài

**Link:** `Affiliate link` (ưu tiên) → fallback `URL` từ Raw Item linked record → fallback empty string

---

## Error Handling

| Lỗi | Behavior |
|-----|----------|
| Buffer API 429 | Sleep 5s, retry 1 lần |
| Buffer API error khác | Log error, đếm vào `errors`, tiếp tục item tiếp |
| Item không có caption | Skip item, log warning, không đếm vào `errors` |
| `BUFFER_ACCESS_TOKEN` không set | Raise `RuntimeError` khi khởi tạo |
| `BUFFER_TIKTOK_PROFILE_ID` hoặc `BUFFER_INSTAGRAM_PROFILE_ID` không set | Raise `RuntimeError` khi khởi tạo |

**Không fail toàn run khi 1 item lỗi** — xử lý được bao nhiêu tốt bấy nhiêu.

---

## Environment Variables

Thêm vào `.env`:
```
BUFFER_ACCESS_TOKEN=...
BUFFER_TIKTOK_PROFILE_ID=...
BUFFER_INSTAGRAM_PROFILE_ID=...
```

---

## Constraints

- Buffer free tier: 3 social accounts, 10 scheduled posts/account — đủ cho MVP
- Push TikTok + Instagram = 2 Buffer updates mỗi Content Queue item
- `limit=20` mỗi run — tránh flood Buffer queue
- Không retry nếu Airtable update fail sau khi Buffer push thành công (chấp nhận orphan: item được schedule nhưng Status vẫn Approved → lần poll sau sẽ try push lại, Buffer sẽ có duplicate)

**Workaround duplicate:** Lưu `Buffer ID` trước khi update Status. Nếu item đã có Buffer ID → skip. Cần check `Buffer ID` trống làm điều kiện query chứ không phải chỉ `Status=Approved`.
