Legends: [ ] new, [.] working, [x] done, [!] blocked
Dates: (YYYY-MM-DD →) = started, (YYYY-MM-DD → YYYY-MM-DD) = completed, no dates = not started

## Infrastructure — Render Cold Start Fix (2026-04-08 →)

> Render free tier spins down after ~15 min idle. GitHub Actions cron jobs hit 521 error instantly before service wakes up.

- [x] INFRA-1: Add "Wake up Render service" warm-up step to all 4 GitHub Actions workflows — retry /health up to 6 times with 10s intervals before calling actual endpoint (2026-04-08 → 2026-04-08)

## Instagram Visual Improvement (2026-04-08 →)

> Based on visual audit of Instagram grid + post view.
> Problems: title too long, brand text clutters image, gradient covers too much, images not eye-catching.

### Priority 1 — Image Overlay Cleanup (readability)

- [x] VIS-1: Add `title_short` field to AI prompt — max 50 chars, punchy title for overlay instead of using first line of Draft VN caption (2026-04-08 → 2026-04-08)
- [x] VIS-2: Use `title_short` from AI data for overlay — fallback to parsed title if not available (2026-04-08 → 2026-04-08)
- [x] VIS-3: Remove "NHA TRANG CURATOR" brand text from image overlay — brand already visible in IG username, saves vertical space (2026-04-08 → 2026-04-08)
- [x] VIS-4: Reduce bottom gradient from 45% to 35% of image height — shows more of the actual photo (2026-04-08 → 2026-04-08)
- [x] VIS-5: Truncate overlay title to 50 chars (was 60) — fits 1-2 lines max for quick scanning (2026-04-08 → 2026-04-08)

### Priority 2 — Image Quality (engagement)

- [ ] VIS-6: Prefer source images with faces/food/scenery — add image quality heuristic or AI scoring
- [ ] VIS-7: Add brightness/contrast check — skip or auto-enhance dark source images before overlay
- [ ] VIS-8: A/B test overlay styles — minimal (just category tag) vs current (tag + title + pills)

### Priority 3 — Caption Optimization

- [ ] VIS-9: Shorten Draft VN caption to 2-3 sentences max — current 3-4 sentences too long for IG feed preview
- [ ] VIS-10: Move hashtags to first comment instead of caption — cleaner look, same discoverability
- [ ] VIS-11: Add CTA line at end of caption — "Save for later" / "Tag someone" to boost engagement

## Smart Scraping — Tier Scheduling + Multi-Provider (2026-04-08 →)

> Based on rate limit analysis: 40 FB sources, only 13 active, 63% duplicate records, ~70% Apify credits wasted.
> See: `docs/superpowers/specs/2026-04-08-smart-scraping-design.md`

### Phase 1 — Tier Scheduling (reduce waste)

- [x] SCR-1: Create `scraper/tier_scheduler.py` — query latest post date per source, assign HOT/WARM/COLD/NEW tier, filter eligible sources by interval (2026-04-08 → 2026-04-08)
- [x] SCR-2: Add `get_latest_post_dates()` to `scraper/airtable_client.py` — batch query Raw Items MAX(Published date) grouped by Source (2026-04-08 → 2026-04-08)
- [x] SCR-3: Refactor `scraper/main.py` — replace `get_active_sources(limit=3)` with `tier_scheduler.get_eligible(limit=3)` (2026-04-08 → 2026-04-08)
- [x] SCR-4: Update Telegram notification — include tier breakdown and skip count (2026-04-08 → 2026-04-08)

### Phase 2 — Multi-Provider Pool (scale capacity)

- [!] SCR-5: PhantomBuster — no "Facebook Page Posts" phantom in store, only LinkedIn/Google/Instagram phantoms available. API keys removed, phantom_fetcher.py removed (2026-04-09 → 2026-04-09)
- [x] SCR-6: Create `scraper/fb_direct_scraper.py` — Playwright + Facebook cookies, scrape rendered DOM, normalize to same format (2026-04-09 → 2026-04-09)
- [x] SCR-7: Refactor `scraper/main.py` — multi-provider fallback: Apify → Direct, auto-skip unavailable providers (2026-04-09 → 2026-04-09)
- [x] SCR-8: Rewrite `facebook-scraper.yml` — run Playwright directly on GitHub Actions runner instead of via Render API (2026-04-09 → 2026-04-09)
- [x] SCR-9: Add `FACEBOOK_COOKIES` + all required secrets to GitHub Actions (2026-04-09 → 2026-04-09)

### Phase 3 — Direct Scraper Quality Audit

- [ ] SCR-12: Audit Direct scraper output quality — compare URLs, text, images vs Apify format. Check: post URLs valid (not photo/reel links), text is actual post content (not UI elements/HTML), images are post images (not avatars/ads), dedup works correctly with new URL format
- [ ] SCR-13: Fix text extraction — current `div[dir="auto"]` selector may capture UI strings, comments, or ad text mixed with real posts. Need stricter parent-level filtering
- [ ] SCR-14: Fix URL extraction — Direct scraper returns photo/reel links instead of canonical post URLs (`/posts/` or `permalink`). Apify returned clean post URLs. Need to normalize or extract correct post permalink
- [ ] SCR-15: Filter duplicate text variants — same post text appears multiple times (full vs truncated "See more" versions). Need dedup by similarity, not just exact match

### Phase 4 — Future Improvements

- [ ] SCR-16: Add more Apify accounts or alternative actors when free tier unblocks
- [ ] SCR-17: Auto-detect cookie expiry and send Telegram alert before it expires
