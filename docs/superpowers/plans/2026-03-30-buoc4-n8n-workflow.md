# Bước 4: n8n Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy curator-api (Python Flask) và n8n (Docker) lên Render, kết nối pipeline scraper→AI→ContentQueue tự động với Telegram notification.

**Architecture:** Render host 2 services: curator-api (Python) expose HTTP endpoints, n8n (Docker) orchestrate workflows theo schedule. Neon PostgreSQL lưu n8n state. UptimeRobot ping cả 2 services mỗi 10 phút để tránh idle sleep.

**Tech Stack:** Flask, Gunicorn, n8n Docker, Neon PostgreSQL, UptimeRobot, Render, Telegram Bot API

---

## File Map

```
scraper/
  server.py          CREATE  Flask app với 4 endpoints
  requirements.txt   MODIFY  thêm flask, gunicorn

n8n/
  Dockerfile         CREATE  n8n Docker image

render.yaml          CREATE  deploy config cho curator-api
render-n8n.yaml      CREATE  deploy config cho n8n
```

---

## Task 1: Flask server — /health và /run-rss

**Files:**
- Create: `scraper/server.py`
- Modify: `scraper/requirements.txt`

- [ ] **Step 1: Thêm flask và gunicorn vào requirements.txt**

```
feedparser==6.0.11
requests==2.31.0
python-dotenv==1.0.0
apscheduler==3.10.4
google-genai
groq
flask==3.0.3
gunicorn==22.0.0
```

- [ ] **Step 2: Tạo scraper/server.py với /health và /run-rss**

```python
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv(Path(__file__).parent.parent / ".env")

# Thêm scraper/ vào path để import các module
sys.path.insert(0, str(Path(__file__).parent))

from airtable_client import AirtableClient
from deduplicator import Deduplicator
import main as pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

app = Flask(__name__)

API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")


def _check_auth():
    """Return error response nếu API key sai, None nếu OK."""
    if not API_SECRET_KEY:
        return None  # dev mode, no auth
    key = request.headers.get("X-API-Key", "")
    if key != API_SECRET_KEY:
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/run-rss")
def run_rss():
    err = _check_auth()
    if err:
        return err
    try:
        client = AirtableClient()
        dedup = Deduplicator(client)
        created = pipeline.run_rss_pipeline(client, dedup)
        log.info(f"/run-rss: {created} new items")
        return jsonify({"created": created})
    except Exception as e:
        log.error(f"/run-rss error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
```

- [ ] **Step 3: Test /health locally**

```bash
cd scraper
source venv/bin/activate
pip install flask==3.0.3 gunicorn==22.0.0
python server.py &
curl http://localhost:8000/health
# Expected: {"status": "ok"}
kill %1
```

- [ ] **Step 4: Test /run-rss locally (no auth)**

```bash
cd scraper
source venv/bin/activate
python server.py &
curl -X POST http://localhost:8000/run-rss
# Expected: {"created": 0}  (dedup đã có hết rồi)
kill %1
```

---

## Task 2: Flask server — /run-facebook và /run-ai-processor

**Files:**
- Modify: `scraper/server.py`

- [ ] **Step 1: Thêm 2 endpoints còn lại vào server.py**

Thêm sau hàm `run_rss()`:

```python
@app.post("/run-facebook")
def run_facebook():
    err = _check_auth()
    if err:
        return err
    try:
        client = AirtableClient()
        dedup = Deduplicator(client)
        created = pipeline.run_facebook_pipeline(client, dedup)
        log.info(f"/run-facebook: {created} new items")
        return jsonify({"created": created})
    except Exception as e:
        log.error(f"/run-facebook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/run-ai-processor")
def run_ai_processor():
    err = _check_auth()
    if err:
        return err
    try:
        from ai_processor import AIProcessor
        processor = AIProcessor()
        stats = processor.process_new_items(limit=50)
        log.info(f"/run-ai-processor: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-ai-processor error: {e}")
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Test /run-ai-processor locally**

```bash
cd scraper
source venv/bin/activate
python server.py &
curl -X POST http://localhost:8000/run-ai-processor
# Expected: {"processed": 0, "use": 0, "reviewed": 0, "skip": 0, "errors": 0}
# (0 vì đã xử lý hết ở bước 3)
kill %1
```

---

## Task 3: render.yaml cho curator-api

**Files:**
- Create: `render.yaml`

- [ ] **Step 1: Tạo render.yaml**

```yaml
services:
  - type: web
    name: curator-api
    runtime: python
    rootDir: scraper
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn server:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1
    envVars:
      - key: AIRTABLE_TOKEN
        sync: false
      - key: APIFY_TOKEN
        sync: false
      - key: GROQ_API_KEY
        sync: false
      - key: API_SECRET_KEY
        sync: false
```

Lưu ý `--timeout 600` vì Facebook pipeline có thể chạy đến 10 phút.

---

## Task 4: Deploy curator-api lên Render

**Files:** không có file mới — thao tác qua Render dashboard + dev-browser

- [ ] **Step 1: Login Render qua dev-browser**

Dùng dev-browser navigate tới `https://dashboard.render.com`, login với `issac.nguyen87@gmail.com` / `killeR@21`.

- [ ] **Step 2: Tạo Web Service mới**

- Click "New" → "Web Service"
- Connect GitHub repo hoặc "Deploy from existing code"
- Nếu chưa có repo: push code lên GitHub trước

```bash
cd /Users/phatnguyen/Projects/curator-nhatrang
git init
git add .
git commit -m "feat: curator-nhatrang pipeline bước 1-4"
gh repo create curator-nhatrang --private --push --source=.
```

- [ ] **Step 3: Cấu hình Web Service trên Render**

Điền vào form:
- Name: `curator-api`
- Root Directory: `scraper`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn server:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1`
- Instance Type: Free

- [ ] **Step 4: Thêm Environment Variables trên Render**

Vào tab "Environment" của service, thêm:
- `AIRTABLE_TOKEN` = (lấy từ .env local)
- `APIFY_TOKEN` = (lấy từ .env local)
- `GROQ_API_KEY` = (lấy từ .env local)
- `API_SECRET_KEY` = (generate random: `openssl rand -hex 16`)

- [ ] **Step 5: Verify deploy thành công**

```bash
# Sau khi deploy xong (2-3 phút)
curl https://curator-api.onrender.com/health
# Expected: {"status": "ok"}
```

---

## Task 5: Neon PostgreSQL setup

**Files:** không có file — thao tác qua Neon dashboard

- [ ] **Step 1: Tạo Neon account và database**

Navigate tới `https://console.neon.tech`, signup với `issac.nguyen87@gmail.com`.

- [ ] **Step 2: Tạo project mới**

- Project name: `curator-nhatrang`
- Region: Singapore (gần nhất với VN)
- Database name: `n8n`

- [ ] **Step 3: Lấy connection string**

Từ Neon dashboard → Connection Details → copy "Connection string" dạng:
```
postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/n8n?sslmode=require
```

Lưu vào `.env`:
```
NEON_DATABASE_URL=postgresql://...
```

---

## Task 6: n8n Dockerfile

**Files:**
- Create: `n8n/Dockerfile`

- [ ] **Step 1: Tạo n8n/Dockerfile**

```dockerfile
FROM n8nio/n8n:latest

USER root
RUN apk add --no-cache curl
USER node

EXPOSE 5678
```

- [ ] **Step 2: Tạo render-n8n.yaml**

```yaml
services:
  - type: web
    name: curator-n8n
    runtime: docker
    dockerfilePath: n8n/Dockerfile
    dockerContext: n8n
    envVars:
      - key: DB_TYPE
        value: postgresdb
      - key: DB_POSTGRESDB_HOST
        sync: false
      - key: DB_POSTGRESDB_PORT
        value: "5432"
      - key: DB_POSTGRESDB_DATABASE
        value: n8n
      - key: DB_POSTGRESDB_USER
        sync: false
      - key: DB_POSTGRESDB_PASSWORD
        sync: false
      - key: DB_POSTGRESDB_SSL
        value: "true"
      - key: N8N_BASIC_AUTH_ACTIVE
        value: "true"
      - key: N8N_BASIC_AUTH_USER
        sync: false
      - key: N8N_BASIC_AUTH_PASSWORD
        sync: false
      - key: EXECUTIONS_DATA_PRUNE
        value: "true"
      - key: EXECUTIONS_DATA_MAX_AGE
        value: "168"
      - key: N8N_HOST
        sync: false
      - key: WEBHOOK_URL
        sync: false
      - key: N8N_PROTOCOL
        value: https
      - key: NODE_ENV
        value: production
```

---

## Task 7: Deploy n8n lên Render

- [ ] **Step 1: Tạo Web Service mới trên Render**

- Name: `curator-n8n`
- Runtime: Docker
- Dockerfile Path: `n8n/Dockerfile`
- Instance Type: Free

- [ ] **Step 2: Thêm Environment Variables**

Parse connection string từ Neon: `postgresql://USER:PASSWORD@HOST/n8n?sslmode=require`

Điền vào Render env vars:
- `DB_POSTGRESDB_HOST` = HOST từ Neon connection string
- `DB_POSTGRESDB_USER` = USER từ Neon connection string
- `DB_POSTGRESDB_PASSWORD` = PASSWORD từ Neon connection string
- `N8N_BASIC_AUTH_USER` = `admin`
- `N8N_BASIC_AUTH_PASSWORD` = (password tự chọn, lưu vào `.env` là `N8N_PASSWORD`)
- `N8N_HOST` = `curator-n8n.onrender.com`
- `WEBHOOK_URL` = `https://curator-n8n.onrender.com/`

- [ ] **Step 3: Verify n8n chạy**

```bash
curl https://curator-n8n.onrender.com/healthz
# Expected: {"status":"ok"}
```

Mở browser tới `https://curator-n8n.onrender.com`, đăng nhập bằng `admin` / password đã set.

---

## Task 8: Tạo Telegram Bot

- [ ] **Step 1: Tạo bot qua BotFather**

Mở Telegram → tìm `@BotFather` → `/newbot`
- Name: `Curator Nha Trang`
- Username: `curator_nhatrang_bot`

Lưu token vào `.env`: `TELEGRAM_BOT_TOKEN=...`

- [ ] **Step 2: Lấy chat_id**

```bash
# Gửi 1 tin nhắn bất kỳ cho bot, rồi:
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"
# Tìm "chat":{"id": XXXXX} trong response
# Lưu vào .env: TELEGRAM_CHAT_ID=XXXXX
```

- [ ] **Step 3: Test gửi tin nhắn**

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}&text=Test từ curator pipeline 🎉"
# Expected: {"ok":true,...}
```

---

## Task 9: n8n Workflows setup

Thực hiện qua n8n UI tại `https://curator-n8n.onrender.com`.

### Workflow 1: RSS Pipeline (7am daily)

- [ ] **Step 1: Tạo workflow mới, đặt tên "RSS Pipeline"**

- [ ] **Step 2: Thêm Schedule Trigger node**
  - Cron expression: `0 0 * * *` (7am GMT+7 = 0am UTC)

- [ ] **Step 3: Thêm HTTP Request node — /run-rss**
  - Method: POST
  - URL: `https://curator-api.onrender.com/run-rss`
  - Headers: `X-API-Key: {{$env.API_SECRET_KEY}}`
  - Timeout: 120000ms

- [ ] **Step 4: Thêm HTTP Request node — /run-ai-processor**
  - Method: POST
  - URL: `https://curator-api.onrender.com/run-ai-processor`
  - Headers: `X-API-Key: {{$env.API_SECRET_KEY}}`
  - Timeout: 300000ms

- [ ] **Step 5: Thêm Airtable node — List Raw Items (Use, no queue)**
  - Operation: List
  - Base ID: `app8VMuhpjzSw25YF`
  - Table ID: `tblNZkO6qjwTHOcAk`
  - Filter: `AND(Status='Use', {Content Queue}=BLANK())`
  - Max Records: 20

- [ ] **Step 6: Thêm IF node — có items không?**
  - Condition: `{{$json.length}} > 0`

- [ ] **Step 7: Thêm Loop Over Items node**

- [ ] **Step 8: Thêm HTTP Request node — Groq API (trong loop)**
  - Method: POST
  - URL: `https://api.groq.com/openai/v1/chat/completions`
  - Headers: `Authorization: Bearer {{$env.GROQ_API_KEY}}`
  - Body (JSON):
  ```json
  {
    "model": "llama-3.3-70b-versatile",
    "messages": [
      {
        "role": "system",
        "content": "Bạn là content creator chuyên về du lịch Nha Trang. Viết caption TikTok và Instagram song ngữ Việt/Anh.\n\nTikTok: hook mạnh, ≤150 ký tự, 3-5 hashtag\nInstagram: kể chuyện 3-5 câu, 10-15 hashtag\n\nChỉ trả về JSON:\n{\"tiktok_vn\":\"...\",\"tiktok_en\":\"...\",\"instagram_vn\":\"...\",\"instagram_en\":\"...\"}"
      },
      {
        "role": "user",
        "content": "Tiêu đề: {{$json.fields.Title}}\nTóm tắt: {{$json.fields['AI Summary']}}\nCategory: {{$json.fields.Category}}"
      }
    ],
    "temperature": 0.7,
    "max_tokens": 800
  }
  ```

- [ ] **Step 9: Thêm Code node — parse Groq response**
  ```javascript
  const text = $input.first().json.choices[0].message.content.trim();
  let captions;
  try {
    const clean = text.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
    captions = JSON.parse(clean);
  } catch(e) {
    captions = { tiktok_vn: text, tiktok_en: '', instagram_vn: text, instagram_en: '' };
  }
  return [{ json: captions }];
  ```

- [ ] **Step 10: Thêm Airtable node — Create Content Queue**
  - Operation: Create
  - Table ID: `tblwjOxiCWhUEoKEP`
  - Fields:
    - `Title`: `{{$('Loop Over Items').item.json.fields.Title}}`
    - `Raw Item`: `["{{$('Loop Over Items').item.json.id}}"]`
    - `Draft VN`: `{{$json.tiktok_vn}}`
    - `Draft EN`: `{{$json.tiktok_en}}`
    - `Status`: `Draft`
    - `Platform`: `["TikTok","Instagram"]`

- [ ] **Step 11: Thêm Wait node — 2 giây (rate limit)**

- [ ] **Step 12: Thêm Telegram node (sau loop)**
  - Operation: Send Message
  - Chat ID: `{{$env.TELEGRAM_CHAT_ID}}`
  - Text: `✅ RSS Pipeline xong!\n📋 {{$('Airtable - List').item.json.length}} items → Content Queue\n🕐 {{new Date().toLocaleString('vi-VN', {timeZone: 'Asia/Ho_Chi_Minh'})}}`

- [ ] **Step 13: Add credentials vào n8n**
  - Groq: API Key env var `GROQ_API_KEY`
  - Telegram: Bot Token env var `TELEGRAM_BOT_TOKEN`
  - Airtable: Personal Access Token env var `AIRTABLE_TOKEN`

- [ ] **Step 14: Activate workflow và test manual run**

### Workflow 2: Facebook Pipeline (8am Mon/Wed/Fri)

- [ ] **Step 1: Duplicate Workflow 1, đổi tên thành "Facebook Pipeline"**

- [ ] **Step 2: Sửa Schedule Trigger**
  - Cron: `0 1 * * 1,3,5` (8am GMT+7 = 1am UTC, Mon/Wed/Fri)

- [ ] **Step 3: Sửa HTTP Request node đầu tiên**
  - URL: `https://curator-api.onrender.com/run-facebook`
  - Timeout: 600000ms (10 phút vì Apify cần thời gian)

- [ ] **Step 4: Sửa Telegram message**
  - Text: `✅ Facebook Pipeline xong!\n📋 {{$('Airtable - List').item.json.length}} items → Content Queue\n🕐 {{new Date().toLocaleString('vi-VN', {timeZone: 'Asia/Ho_Chi_Minh'})}}`

- [ ] **Step 5: Activate và test manual run**

---

## Task 10: UptimeRobot setup

- [ ] **Step 1: Tạo UptimeRobot account**

Navigate tới `https://uptimerobot.com`, signup với `issac.nguyen87@gmail.com` / `killeR@21`.

- [ ] **Step 2: Tạo monitor cho curator-api**
  - Monitor Type: HTTP(s)
  - Friendly Name: `curator-api`
  - URL: `https://curator-api.onrender.com/health`
  - Monitoring Interval: 10 minutes

- [ ] **Step 3: Tạo monitor cho curator-n8n**
  - Monitor Type: HTTP(s)
  - Friendly Name: `curator-n8n`
  - URL: `https://curator-n8n.onrender.com/healthz`
  - Monitoring Interval: 10 minutes

- [ ] **Step 4: Verify monitors active**

Kiểm tra dashboard UptimeRobot: cả 2 monitors đều "Up" (màu xanh).

---

## Task 11: End-to-end test

- [ ] **Step 1: Trigger RSS Pipeline manually trong n8n**

Vào n8n UI → RSS Pipeline → "Execute Workflow" → quan sát logs.

- [ ] **Step 2: Kiểm tra Airtable Content Queue**

```bash
cd scraper && source venv/bin/activate
python -c "
from airtable_client import AirtableClient
import json
client = AirtableClient()
records = client.get_records('contentQueue', max_records=5)
for r in records:
    f = r['fields']
    print(f'[{f.get(\"Status\",\"?\")}] {f.get(\"Title\",\"\")[:50]}')
    print(f'  Draft VN: {f.get(\"Draft VN\",\"\")[:80]}')
    print()
" 2>&1 | grep -v INFO
```

- [ ] **Step 3: Kiểm tra Telegram**

Phải nhận được tin nhắn "✅ RSS Pipeline xong!" trong Telegram.

- [ ] **Step 4: Update PROCESS.md**

```
- [x] Bước 4: n8n workflow
      curator-api: https://curator-api.onrender.com
      curator-n8n: https://curator-n8n.onrender.com
      UptimeRobot: 2 monitors active
      Workflows: RSS Pipeline (7am daily), Facebook Pipeline (8am Mon/Wed/Fri)
      Hoàn thành: 30/3/2026
```
