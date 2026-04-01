# GitHub Actions Migration — Design Spec

**Status:** Designed
**Date:** 2026-04-01

---

## Mục tiêu

Chuyển 5 n8n workflows sang GitHub Actions để loại bỏ n8n instance trên Render (free tier hay down, cold start chậm). GitHub Actions free 2000 phút/tháng, ổn định hơn.

---

## Workflows

| # | Workflow | Endpoint | Schedule | Est. runs/tháng |
|---|---------|----------|----------|-----------------|
| 1 | RSS Scraper | POST /run-rss | Every 6h | 120 |
| 2 | Facebook Scraper | POST /run-facebook | Every 8h | 90 |
| 3 | AI Processor | POST /run-ai-processor | Every 3h | 240 |
| 4 | Instagram Publisher | POST /run-visual → POST /run-instagram | Every 4h | 180 |
| 5 | Newsletter Publisher | POST /run-newsletter | Every 4h | 180 |

**Tổng:** ~810 runs × ~1.5 min = ~1215 phút/tháng (dưới free tier 2000).

---

## Kiến trúc

```
GitHub Actions (cron schedule)
  → curl POST {CURATOR_API_URL}/{endpoint}
      -H "X-API-Key: {API_SECRET_KEY}"
  → parse JSON response
  → curl POST Telegram sendMessage
      "✅ {workflow}: {stats}"
```

Mỗi workflow là 1 file YAML riêng trong `.github/workflows/`.

---

## Cron Schedules (UTC)

| Workflow | Cron | Giờ VN (UTC+7) |
|----------|------|----------------|
| RSS Scraper | `0 1,7,13,19 * * *` | 8h, 14h, 20h, 2h |
| Facebook Scraper | `0 2,10,18 * * *` | 9h, 17h, 1h |
| AI Processor | `0 3,6,9,12,15,18,21,0 * * *` | Mỗi 3h bắt đầu 7h sáng |
| Instagram Publisher | `0 4,8,12,16,20,0 * * *` | Mỗi 4h bắt đầu 7h sáng |
| Newsletter Publisher | `0 5,9,13,17,21,1 * * *` | Mỗi 4h, lệch 1h so với IG |

Lệch giờ giữa các workflow để tránh gọi curator-api cùng lúc (Render free tier chỉ 1 worker).

---

## File Map

```
.github/
  workflows/
    rss-scraper.yml
    facebook-scraper.yml
    ai-processor.yml
    instagram-publisher.yml
    newsletter-publisher.yml
```

---

## GitHub Secrets

| Secret | Value |
|--------|-------|
| `CURATOR_API_URL` | `https://curator-api-hhau.onrender.com` |
| `API_SECRET_KEY` | API key hiện tại |
| `TELEGRAM_BOT_TOKEN` | Bot token |
| `TELEGRAM_CHAT_ID` | Chat ID |

---

## Workflow Template

Mỗi workflow theo cùng pattern:

```yaml
name: {Workflow Name}
on:
  schedule:
    - cron: '{cron expression}'
  workflow_dispatch:  # manual trigger

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Call API
        id: api
        run: |
          RESULT=$(curl -sf --max-time 300 -X POST \
            "${{ secrets.CURATOR_API_URL }}/{endpoint}" \
            -H "X-API-Key: ${{ secrets.API_SECRET_KEY }}")
          echo "result=$RESULT" >> $GITHUB_OUTPUT

      - name: Telegram Notification
        if: always()
        run: |
          if [ "${{ steps.api.outcome }}" = "success" ]; then
            MSG="✅ {Name}: {parsed stats from result}"
          else
            MSG="❌ {Name}: API call failed"
          fi
          curl -sf -X POST \
            "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=$MSG"
```

**Instagram Publisher đặc biệt:** 2 API calls tuần tự (`/run-visual` → `/run-instagram`), Telegram gửi kết quả cả 2.

---

## Error Handling

| Lỗi | Xử lý |
|-----|-------|
| API timeout (>5 min) | curl fail → Telegram gửi "❌ ... failed" |
| API trả HTTP error | curl -f fail → same |
| Telegram fail | `if: always()` đảm bảo step chạy, nhưng nếu Telegram cũng fail thì GitHub Actions log còn lưu |
| Render cold start | `--max-time 300` (5 phút) đủ cho Render wake up + process |

---

## Migration Steps

1. Tạo 5 workflow files
2. Thêm GitHub Secrets qua GitHub API
3. Push code → workflows tự activate
4. Verify 1-2 lần chạy thành công
5. Deactivate n8n workflows (không xóa, phòng rollback)

---

## Constraints

- GitHub Actions cron có độ trễ 5-15 phút (documented behavior) — chấp nhận được cho use case này
- `curl -sf`: silent + fail on HTTP error → step outcome = failure
- `--max-time 300`: Render free tier cần 30-60s cold start + API processing time
- Không cần checkout repo (không dùng source code, chỉ gọi HTTP)
