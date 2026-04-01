# GitHub Actions Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chuyển 5 n8n scheduled workflows sang GitHub Actions (free, ổn định hơn Render free tier).

**Architecture:** Mỗi workflow là 1 YAML file: cron trigger → curl API endpoint → parse JSON → curl Telegram. Secrets lưu trong GitHub repo settings.

**Tech Stack:** GitHub Actions, curl, jq, Telegram Bot API

---

## File Map

```
.github/
  workflows/
    rss-scraper.yml          CREATE  cron every 6h → /run-rss
    facebook-scraper.yml     CREATE  cron every 8h → /run-facebook
    ai-processor.yml         CREATE  cron every 3h → /run-ai-processor
    instagram-publisher.yml  CREATE  cron every 4h → /run-visual + /run-instagram
    newsletter-publisher.yml CREATE  cron every 4h → /run-newsletter
```

---

## Task 1: Tạo GitHub Secrets

**Files:** None (GitHub API)

- [ ] **Step 1: Thêm 4 secrets qua GitHub CLI**

```bash
gh secret set CURATOR_API_URL --body "https://curator-api-hhau.onrender.com"
gh secret set API_SECRET_KEY --body "$(grep '^API_SECRET_KEY=' .env | cut -d= -f2)"
gh secret set TELEGRAM_BOT_TOKEN --body "$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2)"
gh secret set TELEGRAM_CHAT_ID --body "$(grep '^TELEGRAM_CHAT_ID=' .env | cut -d= -f2)"
```

- [ ] **Step 2: Verify secrets**

```bash
gh secret list
```

Expected: 4 secrets listed (CURATOR_API_URL, API_SECRET_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).

---

## Task 2: Tạo RSS Scraper workflow

**Files:**
- Create: `.github/workflows/rss-scraper.yml`

- [ ] **Step 1: Tạo workflow file**

```yaml
name: RSS Scraper
on:
  schedule:
    - cron: '0 1,7,13,19 * * *'
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Call /run-rss
        id: api
        run: |
          RESULT=$(curl -sf --max-time 300 -X POST \
            "${{ secrets.CURATOR_API_URL }}/run-rss" \
            -H "X-API-Key: ${{ secrets.API_SECRET_KEY }}")
          echo "$RESULT"
          echo "result=$RESULT" >> "$GITHUB_OUTPUT"

      - name: Telegram Notification
        if: always()
        run: |
          if [ "${{ steps.api.outcome }}" = "success" ]; then
            ADDED=$(echo '${{ steps.api.outputs.result }}' | jq -r '.created // 0')
            MSG="✅ RSS Scraper: ${ADDED} new items"
          else
            MSG="❌ RSS Scraper: API call failed"
          fi
          curl -sf -X POST \
            "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=${MSG}"
```

- [ ] **Step 2: Commit**

```bash
mkdir -p .github/workflows
git add .github/workflows/rss-scraper.yml
git commit -m "ci: add RSS Scraper GitHub Actions workflow"
```

---

## Task 3: Tạo Facebook Scraper workflow

**Files:**
- Create: `.github/workflows/facebook-scraper.yml`

- [ ] **Step 1: Tạo workflow file**

```yaml
name: Facebook Scraper
on:
  schedule:
    - cron: '0 2,10,18 * * *'
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Call /run-facebook
        id: api
        run: |
          RESULT=$(curl -sf --max-time 300 -X POST \
            "${{ secrets.CURATOR_API_URL }}/run-facebook" \
            -H "X-API-Key: ${{ secrets.API_SECRET_KEY }}")
          echo "$RESULT"
          echo "result=$RESULT" >> "$GITHUB_OUTPUT"

      - name: Telegram Notification
        if: always()
        run: |
          ADDED=$(echo '${{ steps.api.outputs.result }}' | jq -r '.created // 0' 2>/dev/null || echo "?")
          if [ "${{ steps.api.outcome }}" = "success" ]; then
            MSG="✅ Facebook Scraper: ${ADDED} new items"
          else
            MSG="❌ Facebook Scraper: API call failed"
          fi
          curl -sf -X POST \
            "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=${MSG}"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/facebook-scraper.yml
git commit -m "ci: add Facebook Scraper GitHub Actions workflow"
```

---

## Task 4: Tạo AI Processor workflow

**Files:**
- Create: `.github/workflows/ai-processor.yml`

- [ ] **Step 1: Tạo workflow file**

```yaml
name: AI Processor
on:
  schedule:
    - cron: '0 3,6,9,12,15,18,21,0 * * *'
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Call /run-ai-processor
        id: api
        run: |
          RESULT=$(curl -sf --max-time 300 -X POST \
            "${{ secrets.CURATOR_API_URL }}/run-ai-processor" \
            -H "X-API-Key: ${{ secrets.API_SECRET_KEY }}")
          echo "$RESULT"
          echo "result=$RESULT" >> "$GITHUB_OUTPUT"

      - name: Telegram Notification
        if: always()
        run: |
          if [ "${{ steps.api.outcome }}" = "success" ]; then
            PROCESSED=$(echo '${{ steps.api.outputs.result }}' | jq -r '.processed // 0')
            USE=$(echo '${{ steps.api.outputs.result }}' | jq -r '.use // 0')
            SKIP=$(echo '${{ steps.api.outputs.result }}' | jq -r '.skip // 0')
            MSG="✅ AI Processor: ${PROCESSED} processed, ${USE} Use, ${SKIP} Skip"
          else
            MSG="❌ AI Processor: API call failed"
          fi
          curl -sf -X POST \
            "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=${MSG}"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ai-processor.yml
git commit -m "ci: add AI Processor GitHub Actions workflow"
```

---

## Task 5: Tạo Instagram Publisher workflow

**Files:**
- Create: `.github/workflows/instagram-publisher.yml`

- [ ] **Step 1: Tạo workflow file**

Workflow này gọi 2 endpoints tuần tự: `/run-visual` (tạo ảnh) → `/run-instagram` (publish).

```yaml
name: Instagram Publisher
on:
  schedule:
    - cron: '0 4,8,12,16,20,0 * * *'
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Call /run-visual
        id: visual
        run: |
          RESULT=$(curl -sf --max-time 300 -X POST \
            "${{ secrets.CURATOR_API_URL }}/run-visual" \
            -H "X-API-Key: ${{ secrets.API_SECRET_KEY }}")
          echo "$RESULT"
          echo "result=$RESULT" >> "$GITHUB_OUTPUT"

      - name: Call /run-instagram
        id: instagram
        run: |
          RESULT=$(curl -sf --max-time 300 -X POST \
            "${{ secrets.CURATOR_API_URL }}/run-instagram" \
            -H "X-API-Key: ${{ secrets.API_SECRET_KEY }}")
          echo "$RESULT"
          echo "result=$RESULT" >> "$GITHUB_OUTPUT"

      - name: Telegram Notification
        if: always()
        run: |
          if [ "${{ steps.instagram.outcome }}" = "success" ]; then
            PUSHED=$(echo '${{ steps.instagram.outputs.result }}' | jq -r '.pushed // 0')
            SKIPPED=$(echo '${{ steps.instagram.outputs.result }}' | jq -r '.skipped // 0')
            ERRORS=$(echo '${{ steps.instagram.outputs.result }}' | jq -r '.errors // 0')
            VISUAL=$(echo '${{ steps.visual.outputs.result }}' | jq -r '.processed // 0' 2>/dev/null || echo "?")
            MSG="✅ Instagram Publisher: pushed ${PUSHED} | skipped ${SKIPPED} | errors ${ERRORS} | visual ${VISUAL}"
          else
            MSG="❌ Instagram Publisher: API call failed"
          fi
          curl -sf -X POST \
            "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=${MSG}"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/instagram-publisher.yml
git commit -m "ci: add Instagram Publisher GitHub Actions workflow"
```

---

## Task 6: Tạo Newsletter Publisher workflow

**Files:**
- Create: `.github/workflows/newsletter-publisher.yml`

- [ ] **Step 1: Tạo workflow file**

```yaml
name: Newsletter Publisher
on:
  schedule:
    - cron: '0 5,9,13,17,21,1 * * *'
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Call /run-newsletter
        id: api
        run: |
          RESULT=$(curl -sf --max-time 300 -X POST \
            "${{ secrets.CURATOR_API_URL }}/run-newsletter" \
            -H "X-API-Key: ${{ secrets.API_SECRET_KEY }}")
          echo "$RESULT"
          echo "result=$RESULT" >> "$GITHUB_OUTPUT"

      - name: Telegram Notification
        if: always()
        run: |
          if [ "${{ steps.api.outcome }}" = "success" ]; then
            PUBLISHED=$(echo '${{ steps.api.outputs.result }}' | jq -r '.published // 0')
            SKIPPED=$(echo '${{ steps.api.outputs.result }}' | jq -r '.skipped // 0')
            ERRORS=$(echo '${{ steps.api.outputs.result }}' | jq -r '.errors // 0')
            MSG="✅ Newsletter: published ${PUBLISHED} | skipped ${SKIPPED} | errors ${ERRORS}"
          else
            MSG="❌ Newsletter Publisher: API call failed"
          fi
          curl -sf -X POST \
            "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=${MSG}"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/newsletter-publisher.yml
git commit -m "ci: add Newsletter Publisher GitHub Actions workflow"
```

---

## Task 7: Push, verify, và deactivate n8n

- [ ] **Step 1: Push tất cả workflows**

```bash
git push origin main
```

- [ ] **Step 2: Trigger manual test cho mỗi workflow**

```bash
gh workflow run rss-scraper.yml
gh workflow run facebook-scraper.yml
gh workflow run ai-processor.yml
gh workflow run instagram-publisher.yml
gh workflow run newsletter-publisher.yml
```

- [ ] **Step 3: Kiểm tra kết quả**

```bash
gh run list --limit 5
```

Expected: 5 runs with status "completed" (hoặc "in_progress" nếu đang chạy). Kiểm tra Telegram nhận được notifications.

- [ ] **Step 4: Deactivate n8n workflows**

Gọi n8n REST API để deactivate (không xóa):

```bash
# Login và deactivate qua Python
python3 << 'PYEOF'
import requests, os
from dotenv import load_dotenv
load_dotenv('.env')

N8N = 'https://curator-n8n.onrender.com'
session = requests.Session()
session.post(f'{N8N}/rest/login', json={
    'emailOrLdapLoginId': 'issac.nguyen87@gmail.com',
    'password': os.getenv('N8N_BASIC_AUTH_PASSWORD', ''),
}, timeout=60)

for wf_id in ['RMzb3wh0Gxper9uw', '6GNx4AvpvHcL5cdh', 'fVjAja1kGc8vzhCp', 'yFl58xOdMtXk42gR', 'OrFyGumi5DxsHm8a']:
    resp = session.patch(f'{N8N}/rest/workflows/{wf_id}', json={'active': False}, timeout=60)
    name = resp.json().get('data', {}).get('name', wf_id)
    print(f'Deactivated: {name} ({resp.status_code})')
PYEOF
```

- [ ] **Step 5: Update CLAUDE.md**

Trong `CLAUDE.md`, thay dòng:
```
- Automation: n8n (hosted trên Render)
```
Thành:
```
- Automation: GitHub Actions (cron schedules)
```

- [ ] **Step 6: Commit và push**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md - n8n replaced by GitHub Actions"
git push origin main
```
