# Progress

## Đã hoàn thành
- [x] Bước 1: Airtable base + 4 tables
      Base ID: app8VMuhpjzSw25YF
      Hoàn thành: 30/3/2026

- [x] Bước 2: RSS + Apify scraper
      Actor: apify~facebook-posts-scraper (đổi từ pages-scraper)
      Schedule: RSS daily 7am | Facebook Mon/Wed/Fri 8am
      Credit usage: ~$3-5/tháng với 3 lần/tuần
      Lần chạy đầu: 51 records Facebook + 29 records RSS = 80 records tổng
      Dedup OK: lần 2 trả về 0 new items

      RSS Sources (3 nguồn Google News thay cho Báo Khánh Hòa chung chung):
      - "Google News — Sự kiện Nha Trang": lễ hội, festival, khai mạc, biểu diễn
      - "Google News — Ẩm thực Nha Trang": nhà hàng, quán ngon, đặc sản, món ăn
      - "Google News — Địa điểm Nha Trang": tham quan, check-in, khám phá, lặn biển
      Lý do đổi: baokhanhhoa.vn không có RSS, Google News không có site: filter tốt
      Lưu ý: vẫn còn ~10% nhiễu (tin chính trị lọt vào) → AI processor bước 3 sẽ lọc

## Chưa làm
- [ ] Bước 4: n8n workflow
- [ ] Bước 5: Buffer scheduling

- [x] Bước 3: AI processor (Groq llama-3.3-70b, free tier)
      Model: llama-3.3-70b-versatile (Groq) — thay Gemini vì 1 RPM quá chậm
      API Key: trong .env GROQ_API_KEY (jupitern8@gmail.com)
      Free tier: 30 RPM, 14400 RPD → batch 5 items/request, sleep 2s/batch
      Logic: relevant filter + category + summary VN/EN + content_potential
      Status flow: New → Use (high) / Reviewed (medium) / Skip (không relevant)
      Kết quả 80 items: Use=32, Reviewed=28, Skip=20, ~3 phút (vs Gemini: ~87 phút)
      Hoàn thành: 30/3/2026

## Ghi chú kỹ thuật
- Airtable rate limit: cần sleep 200ms
- Facebook: dùng apify~facebook-posts-scraper (không phải pages-scraper)
- RSS: Google News RSS với query keyword, không dùng site: filter
- Apify free tier $5/tháng, ~$0.02/run, đủ cho 3 lần/tuần × 6 fanpages
- Groq free tier: 30 RPM, 14400 RPD — dùng llama-3.3-70b-versatile
- Gemini 2.5 Flash free tier chỉ 1 RPM/25 RPD → quá chậm, giữ làm fallback
