# Bước 2: Setup Scraper — RSS + Facebook qua Apify

Đọc CLAUDE.md và PROGRESS.md trước khi bắt đầu.

## Kiến trúc

RSS (feedparser, miễn phí hoàn toàn):
Apify → schedule → fetch → parse → Airtable

Facebook (Apify free tier $5/tháng):
Apify Actor → scrape fanpage → webhook → Airtable

Cả hai đều chạy hoàn toàn tự động, không cần người.

## Cấu trúc file

scraper/
├── main.py                  # Entry point chạy cả hai
├── rss_fetcher.py           # Xử lý RSS feeds
├── apify_fetcher.py         # Gọi Apify scrape Facebook
├── airtable_client.py       # Helper đọc/ghi Airtable
├── deduplicator.py          # Check trùng lặp
├── scheduler.py             # APScheduler chạy hàng ngày
├── requirements.txt
└── .env.example

## Chi tiết từng file

### airtable_client.py
Class AirtableClient:
- get_active_sources(type_filter=None)
  → list sources lọc theo Type nếu có
- get_existing_urls() → set URLs đã có trong Raw Items
- create_raw_item(data: dict) → record mới Status="New"
- create_raw_items_batch(items: list)
  → tạo nhiều records cùng lúc, 10 items/batch
  → Airtable batch API: POST /v0/{baseId}/{table}
     body: {"records": [{fields: ...}, ...]}
- update_source_last_checked(source_id: str)
- Rate limit: sleep 200ms giữa API calls
- Retry: tối đa 3 lần nếu gặp 429 rate limit

### rss_fetcher.py
Dùng feedparser.
Input: list source records có Type="RSS"

Process mỗi source:
- feedparser.parse(url)
- Extract tối đa 10 entries gần nhất
- Chuẩn hóa published date thành ISO string

Output format chuẩn (dùng chung cho mọi fetcher):
{
  "title": str,
  "content": str,           # full text hoặc summary
  "url": str,               # link bài gốc
  "published_date": str,    # ISO 8601
  "source_name": str,
  "source_id": str,         # Airtable record ID
  "fetcher_type": "rss"
}

Error handling:
- Feed không fetch được → log warning, continue
- Entry thiếu URL → skip entry đó
- Date parse lỗi → dùng current timestamp

### apify_fetcher.py
Dùng Apify REST API trực tiếp (không cần SDK).
Actor: apify/facebook-pages-scraper

Class ApifyFetcher:

**run_actor(facebook_url, source_id, source_name)**
→ Chạy actor và đợi kết quả

Flow:
1. POST https://api.apify.com/v2/acts/apify~facebook-pages-scraper/runs
   Headers: Authorization: Bearer {APIFY_API_TOKEN}
   Body:
   {
     "startUrls": [{"url": facebook_url}],
     "maxPosts": 10,
     "maxPostComments": 0,
     "maxReviews": 0,
     "maxImages": 0
   }
   → Nhận run_id từ response

2. Poll status mỗi 5 giây:
   GET https://api.apify.com/v2/actor-runs/{run_id}
   Đợi status = "SUCCEEDED" hoặc "FAILED"
   Timeout: 120 giây
   Nếu FAILED hoặc timeout → raise ApifyRunError

3. Fetch results:
   GET https://api.apify.com/v2/actor-runs/{run_id}/dataset/items
   → list posts

4. Transform mỗi post thành output format chuẩn:
   {
     "title": post.text[:100] nếu có,
     "content": post.text hoặc post.message,
     "url": post.url hoặc post.postUrl,
     "published_date": post.time hoặc post.date (ISO),
     "source_name": source_name,
     "source_id": source_id,
     "fetcher_type": "facebook"
   }

**Lưu ý Apify free tier:**
- $5 credit/tháng
- Facebook scraper tốn khoảng $0.01-0.05 per run
- Ước tính: 30 fanpages × 2 lần/tuần × 4 tuần
  = 240 runs/tháng × $0.02 = ~$4.8/tháng
- Vừa đủ free tier nếu scrape 2 lần/tuần
- Nếu muốn scrape hàng ngày: giảm xuống 15 fanpages

**Thêm method check_credit_balance():**
GET https://api.apify.com/v2/users/me
→ Log current credit balance sau mỗi lần chạy
→ Warning nếu balance < $1

### deduplicator.py
Class Deduplicator:
- __init__: load tất cả URLs từ Airtable vào set
- is_duplicate(url: str) → bool
- add_url(url: str) → update local set
- filter_new_items(items: list) → list items chưa có

### main.py
Pipeline chính:

def run_rss_pipeline(client, dedup):
  sources = client.get_active_sources(type_filter="RSS")
  all_items = []
  for source in sources:
    items = rss_fetcher.fetch(source)
    new_items = dedup.filter_new_items(items)
    all_items.extend(new_items)
  if all_items:
    client.create_raw_items_batch(all_items)
    for item in all_items:
      dedup.add_url(item["url"])
  return len(all_items)

def run_facebook_pipeline(client, dedup):
  sources = client.get_active_sources(type_filter="Facebook")
  total_new = 0
  for source in sources:
    try:
      items = apify_fetcher.run_actor(
        source["URL"],
        source["id"],
        source["Name"]
      )
      new_items = dedup.filter_new_items(items)
      if new_items:
        client.create_raw_items_batch(new_items)
        for item in new_items:
          dedup.add_url(item["url"])
      total_new += len(new_items)
      client.update_source_last_checked(source["id"])
      sleep(2)  # Tránh spam Apify API
    except ApifyRunError as e:
      log.error(f"Apify failed for {source['Name']}: {e}")
      continue  # Không crash, tiếp tục source tiếp theo
  return total_new

def main():
  log.info("=== Scraper started ===")
  client = AirtableClient()
  dedup = Deduplicator(client)

  # RSS pipeline
  rss_count = run_rss_pipeline(client, dedup)
  log.info(f"RSS: {rss_count} new items")

  # Facebook pipeline
  fb_count = run_facebook_pipeline(client, dedup)
  log.info(f"Facebook: {fb_count} new items")

  log.info(f"=== Done: {rss_count + fb_count} total new items ===")

### scheduler.py
Dùng APScheduler BlockingScheduler.

Schedule:
- RSS: mỗi ngày 7:00 AM
- Facebook: thứ 2, tư, 6 lúc 8:00 AM
  (3 lần/tuần để tiết kiệm Apify credit)

Log ra scraper.log:
- RotatingFileHandler
- Max 10MB mỗi file
- Giữ 7 file backup

## Env vars (.env.example)
AIRTABLE_API_TOKEN=
AIRTABLE_BASE_ID=
AIRTABLE_SOURCES_TABLE=Sources
AIRTABLE_RAW_ITEMS_TABLE=Raw Items
APIFY_API_TOKEN=

## Requirements.txt
feedparser==6.0.11
requests==2.31.0
pyairtable==2.3.3
python-dotenv==1.0.0
apscheduler==3.10.4

## Test sequence

# Bước 1: Test kết nối Airtable
python -c "
from airtable_client import AirtableClient
c = AirtableClient()
sources = c.get_active_sources()
print(f'Found {len(sources)} sources')
"

# Bước 2: Test RSS với 1 source
python -c "
from airtable_client import AirtableClient
from rss_fetcher import fetch
c = AirtableClient()
sources = c.get_active_sources(type_filter='RSS')
items = fetch(sources[0])
print(f'Fetched {len(items)} items')
for i in items[:2]:
    print(i['title'], i['url'])
"

# Bước 3: Test Apify với 1 fanpage
python -c "
from apify_fetcher import ApifyFetcher
f = ApifyFetcher()
f.check_credit_balance()
items = f.run_actor(
  'https://facebook.com/lifepuppets.show',
  'test_source_id',
  'Nha Hat Do'
)
print(f'Fetched {len(items)} posts')
"

# Bước 4: Chạy full pipeline
python main.py

# Bước 5: Verify dedup — chạy lại lần 2
python main.py
# Phải thấy "0 total new items"

# Bước 6: Kiểm tra Airtable
# Mở Airtable Raw Items, verify có records mới
# Status = "New", Source linked đúng không

# Bước 7: Start scheduler (production)
python scheduler.py

## Error handling rules
1. Một source fail → log error, continue source tiếp
2. Apify rate limit (429) → sleep 30s, retry 1 lần
3. Airtable rate limit (429) → sleep 1s, retry 3 lần
4. Apify credit hết → log CRITICAL, skip toàn bộ Facebook pipeline
5. Không có item nào mới → log info, không phải error

## Sau khi hoàn thành
Cập nhật PROGRESS.md:
- [x] Bước 2: RSS + Apify scraper
- Ghi Apify Actor ID đang dùng: apify~facebook-pages-scraper
- Ghi schedule: RSS daily 7am, Facebook Mon/Wed/Fri 8am
- Ghi ước tính credit usage: ~$3-5/tháng với 3 lần/tuần
- Ghi cách monitor: check_credit_balance() log

Cập nhật CLAUDE.md:
- Cập nhật để có đúng thông tin và cách xử lý trong project
```
