# Post-Publish Cleanup — Design Spec

**Status:** Designed
**Date:** 2026-04-01

---

## Mục tiêu

Tự động dọn dẹp Cloudinary images và Airtable records sau khi publish Instagram, giữ record count dưới Airtable free tier limit (1,000 records/base).

---

## Cleanup Flow

### 1. Ngay sau publish (trong instagram_publisher.py)

Sau khi Instagram publish thành công (có media_id):

```
1. Tạo Published record:
   - Title (từ Content Queue)
   - Platform = "Instagram"
   - Post URL = https://www.instagram.com/p/{shortcode}/
   - Published at = now (ISO)

2. Xóa Cloudinary image:
   - Extract public_id từ Image URL (format: .../upload/v123/nhatrang/recXXX.jpg)
   - cloudinary.uploader.destroy(public_id)

3. Xóa Content Queue record:
   - client.delete_record("contentQueue", record_id)

4. Xóa Raw Item linked record:
   - Lấy Raw Item ID từ Content Queue record (trước khi xóa)
   - client.delete_record("rawItems", raw_item_id)
```

### 2. Weekly cleanup job (endpoint /run-cleanup)

Chạy mỗi tuần qua GitHub Actions:

```
1. Xóa Published records > 30 ngày
   - Filter: IS_BEFORE({Published at}, DATEADD(TODAY(), -30, 'days'))

2. Xóa Raw Items Status=Skip
   - Filter: {Status}="Skip"

3. Xóa Raw Items Status=New > 30 ngày
   - Filter: AND({Status}="New", IS_BEFORE({Collected at}, DATEADD(TODAY(), -30, 'days')))
```

---

## Components

### `scraper/instagram_publisher.py` — thêm cleanup sau publish

Sau `self.client.update_record(... Status=Scheduled)`, thay bằng:
1. Lấy Raw Item IDs từ record trước
2. Tạo Published record
3. Xóa Cloudinary image
4. Xóa Content Queue record
5. Xóa Raw Item record

Cần thêm `cloudinary.uploader` import lại (đã bỏ ở task trước).

### `scraper/airtable_client.py` — thêm delete_record method

```python
def delete_record(self, table_key: str, record_id: str) -> None
```

### `scraper/server.py` — thêm /run-cleanup endpoint

```python
@app.post("/run-cleanup")
```

### `.github/workflows/weekly-cleanup.yml` — cron weekly

Schedule: mỗi Chủ Nhật 3:00 UTC (10:00 VN).

---

## Published Record Fields

| Field | Value |
|-------|-------|
| Title | Từ Content Queue record |
| Platform | "Instagram" |
| Post URL | Permalink từ Instagram API |
| Published at | ISO timestamp |

---

## Error Handling

| Lỗi | Xử lý |
|-----|-------|
| Cloudinary destroy fail | Log warning, tiếp tục (không block) |
| Delete Content Queue fail | Log error, tiếp tục |
| Delete Raw Item fail | Log warning, tiếp tục (có thể Raw Item đã bị xóa) |
| Published record create fail | Log error, tiếp tục (post đã lên Instagram rồi) |
| Weekly cleanup filter trả 0 records | Log info, skip |

Cleanup là best-effort — không fail toàn flow nếu 1 bước lỗi.

---

## Constraints

- Airtable batch delete: max 10 records/request
- Cloudinary destroy: 1 request per image
- Weekly cleanup: không xóa Raw Items Status=Use hoặc Reviewed (đang trong pipeline)
- Instagram permalink: lấy từ Graph API sau khi publish (GET /{media_id}?fields=permalink)
