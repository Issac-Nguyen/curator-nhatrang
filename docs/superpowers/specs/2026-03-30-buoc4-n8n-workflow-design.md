# Bước 4: n8n Workflow Design

**Date:** 2026-03-30
**Status:** Approved

## Tổng quan

Orchestrate toàn bộ pipeline tự động: scraper → AI processor → content queue generation → Telegram notification. Không cần Mac bật 24/7.

## Architecture

```
UptimeRobot (free)
  → GET curator-api.onrender.com/health   mỗi 10 phút
  → GET curator-n8n.onrender.com/healthz  mỗi 10 phút

Render Service 1: curator-api (Python Flask)
  Codebase: scraper/ + server.py mới
  Endpoints:
    GET  /health              → 200 OK
    POST /run-rss             → chạy RSS scraper + lưu Airtable
    POST /run-facebook        → chạy Apify Facebook + lưu Airtable
    POST /run-ai-processor    → classify New items → Use/Reviewed/Skip

Render Service 2: n8n (Docker image n8nio/n8n)
  DB: Neon PostgreSQL free (500MB, dùng ~20MB)
  Workflows: 4 workflows

Neon PostgreSQL (free)
  → n8n metadata, workflows, credentials, execution history (pruned 7 ngày)
```

## Render Service 1: curator-api

### server.py

Flask app expose 4 endpoints. Mỗi endpoint chạy pipeline function đã có sẵn từ Bước 2-3.

```python
GET  /health             → {"status": "ok"}
POST /run-rss            → main.run_rss_pipeline() → {"created": N}
POST /run-facebook       → main.run_facebook_pipeline() → {"created": N}
POST /run-ai-processor   → AIProcessor().process_new_items() → stats dict
```

Bảo mật: mỗi POST endpoint yêu cầu header `X-API-Key` khớp với env `API_SECRET_KEY`.

### render.yaml (Service 1)

```yaml
services:
  - type: web
    name: curator-api
    runtime: python
    buildCommand: pip install -r scraper/requirements.txt
    startCommand: python scraper/server.py
    envVars:
      - key: AIRTABLE_TOKEN
      - key: APIFY_TOKEN
      - key: GROQ_API_KEY
      - key: API_SECRET_KEY
```

## Render Service 2: n8n

### Docker setup trên Render

```yaml
services:
  - type: web
    name: curator-n8n
    runtime: docker
    dockerfilePath: n8n/Dockerfile
    envVars:
      - key: DB_TYPE
        value: postgresdb
      - key: DB_POSTGRESDB_DATABASE
      - key: DB_POSTGRESDB_HOST
      - key: DB_POSTGRESDB_PORT
      - key: DB_POSTGRESDB_USER
      - key: DB_POSTGRESDB_PASSWORD
      - key: N8N_BASIC_AUTH_ACTIVE
        value: "true"
      - key: N8N_BASIC_AUTH_USER
      - key: N8N_BASIC_AUTH_PASSWORD
      - key: EXECUTIONS_DATA_PRUNE
        value: "true"
      - key: EXECUTIONS_DATA_MAX_AGE
        value: "168"
```

## n8n Workflows

### Workflow 1: RSS Pipeline
**Trigger:** Cron `0 7 * * *` (7am daily, GMT+7)

```
Schedule Trigger
→ HTTP POST /run-rss (curator-api, header X-API-Key)
→ HTTP POST /run-ai-processor
→ Airtable: List Raw Items (Status=Use, không có Content Queue linked)
→ IF có items:
    → Loop each item:
        → HTTP POST Groq API: generate captions
        → Airtable: Create Content Queue record (Status=Draft)
        → Wait 2s
→ Telegram: "✅ RSS xong — {{$json.created}} items vào Content Queue"
```

### Workflow 2: Facebook Pipeline
**Trigger:** Cron `0 8 * * 1,3,5` (8am Mon/Wed/Fri, GMT+7)

```
Schedule Trigger
→ HTTP POST /run-facebook (curator-api)
→ HTTP POST /run-ai-processor
→ (giống Workflow 1 từ bước Airtable trở đi)
→ Telegram: "✅ Facebook xong — {{$json.created}} items vào Content Queue"
```

### Workflow 3: Content Queue Generator (sub-workflow)
Được gọi từ Workflow 1 và 2. Tách riêng để tái sử dụng.

```
Input: không có (tự fetch từ Airtable)

Airtable: List Raw Items
  filter: Status='Use' AND {Content Queue} = BLANK()
  max: 20

Loop each item:
  Groq (llama-3.3-70b):
    Input: title, content, summary_vn, summary_en, category
    Output JSON:
      {
        "tiktok_vn": "Hook + nội dung ≤150 ký tự + #hashtag",
        "tiktok_en": "English TikTok version",
        "instagram_vn": "Caption dài + story + hashtags",
        "instagram_en": "English Instagram version"
      }

  Airtable: Create Content Queue record
    Title: raw item title
    Raw Item: [raw item id]
    Content type: TikTok + Instagram
    Draft VN: tiktok_vn
    Draft EN: tiktok_en
    Status: Draft

  Wait: 2s (Groq rate limit)

Output: count of created records
```

### Workflow 4: Telegram Notify (sub-workflow)
Nhận message text, gửi qua Telegram Bot API.

```
Input: message (string)
→ HTTP POST https://api.telegram.org/bot{TOKEN}/sendMessage
   chat_id: {CHAT_ID}
   text: message
```

## Groq Prompt — Caption Generation

```
System: Bạn là content creator chuyên về du lịch Nha Trang.
Viết caption cho TikTok và Instagram (song ngữ Việt/Anh).

TikTok: Hook mạnh đầu câu, ≤150 ký tự, 3-5 hashtag tiếng Việt + tiếng Anh
Instagram: Kể chuyện 3-5 câu, cảm xúc, 10-15 hashtag

Trả về JSON:
{
  "tiktok_vn": "...",
  "tiktok_en": "...",
  "instagram_vn": "...",
  "instagram_en": "..."
}

User: Tiêu đề: {title}
Nội dung: {content[:500]}
Tóm tắt VN: {summary_vn}
Category: {category}
```

## Airtable — Field mapping Content Queue

| Field | Value |
|-------|-------|
| Title | Raw Item title |
| Raw Item | linked record id |
| Content type | TikTok, Instagram |
| Draft VN | tiktok_vn (TikTok caption) |
| Draft EN | tiktok_en |
| Final VN | (trống, user điền sau) |
| Final EN | (trống, user điền sau) |
| Status | Draft |
| Platform | TikTok, Instagram |

## UptimeRobot Setup

- Monitor 1: `https://curator-api.onrender.com/health` — interval 10 phút
- Monitor 2: `https://curator-n8n.onrender.com/healthz` — interval 10 phút
- Alert: email khi down

## Bảo mật

- `API_SECRET_KEY`: random 32-char string, dùng cho X-API-Key header
- n8n Basic Auth: username + password để vào n8n UI
- Groq/Airtable keys: chỉ lưu trong Render env vars + .env local

## Files cần tạo/sửa

```
scraper/
  server.py          (MỚI) Flask API server
  requirements.txt   (SỬA) thêm flask, gunicorn

n8n/
  Dockerfile         (MỚI) n8n Docker image

render.yaml          (MỚI) deploy config cho cả 2 services
```

## Thứ tự implement

1. `scraper/server.py` + test local
2. `n8n/Dockerfile` + `render.yaml`
3. Tạo Neon database
4. Deploy lên Render (curator-api trước, n8n sau)
5. Setup n8n workflows qua UI
6. Setup UptimeRobot monitors
7. Test end-to-end
