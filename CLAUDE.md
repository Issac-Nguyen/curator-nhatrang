# Nha Trang Curator — Project Context

## Mục đích
Hệ thống tự động thu thập, xử lý và phân phối thông tin
sự kiện/địa điểm Nha Trang để xây dựng kênh content
curator trên TikTok và Instagram (song ngữ Việt/Anh).
Mô hình kiếm tiền: affiliate + sponsor địa điểm.

## Vai trò của tôi trong hệ thống
Curator — không trực tiếp trải nghiệm địa điểm.
Toàn bộ thông tin lấy từ nguồn online.
Giá trị tạo ra nằm ở chất lượng tổng hợp và phân phối.

## Pipeline tổng thể
Sources → Raw Items → Content Queue → Published
(thu thập) (lưu thô)  (verify+draft)  (đã đăng)

## Stack kỹ thuật
- Database: Airtable (Base ID lưu trong config.json)
- Scraping: Apify (Facebook), feedparser (RSS)
- AI processing: Groq (llama-3.3-70b)
- Image: Pexels (stock photos) + Cloudinary (hosting + transforms)
- Publishing: Instagram Graph API (auto-refresh token 60 ngày)
- Automation: GitHub Actions (cron schedules)
- Hosting: Render (curator-api + curator-n8n)
- Newsletter: Beehiiv

## Cấu trúc Airtable — 4 tables

### Sources
Danh sách nguồn cần theo dõi.
Fields: Name, Type (RSS/Facebook/TikTok/Instagram/Website),
URL, Category (Sự kiện/Địa điểm/Tin tức/Workshop/Ẩm thực),
Active (bool), Last checked, Notes

### Raw Items
Thông tin thô scraper kéo về, chưa xử lý.
Fields: Title, Content, Source (→Sources), URL,
Published date, Collected at, AI Summary (JSON),
Status (New/Reviewed/Use/Skip)

### Content Queue
Draft content đã verify, chờ approve và đăng.
Fields: Title, Raw Item (→Raw Items), Content type,
Draft VN, Draft EN, Final VN, Final EN,
Image URL, Buffer ID (dedup guard, format: ig:{media_id}),
Schedule date, Platform (multi-select),
Affiliate link, Status (Draft/Editing/Approved/Scheduled/Done)

### Published
Bài đã đăng kèm performance metrics.
Fields: Title, Content Queue Item (→Content Queue),
Platform, Post URL, Published at,
Views, Likes, Comments, Saves,
Affiliate clicks, Affiliate revenue (VND), Notes

## Config files
- config.json: Airtable Base ID, Table IDs, API keys
- sources.json: Danh sách nguồn đầy đủ (backup)

## Quy tắc khi code
1. Luôn đọc config.json trước khi làm bất cứ thứ gì
2. Không hardcode Base ID hoặc Table ID — luôn lấy từ config
3. Rate limit Airtable: sleep 200ms giữa các API calls
4. Mọi thay đổi schema phải update config.json
5. Log rõ từng bước để debug dễ
