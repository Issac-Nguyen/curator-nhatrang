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

- [ ] SCR-5: Create `scraper/providers/base.py` — abstract BaseProvider with `fetch_posts()` and `is_available()` interface
- [ ] SCR-6: Create `scraper/providers/apify_provider.py` — extract from `apify_fetcher.py`, keep 2-token rotation
- [ ] SCR-7: Create `scraper/providers/phantom_provider.py` — PhantomBuster Facebook Page Posts integration, 2-key rotation
- [ ] SCR-8: Create `scraper/provider_pool.py` — round-robin + fallback logic, usage tracking per provider
- [ ] SCR-9: Refactor `scraper/main.py` — use `provider_pool.fetch()` instead of `ApifyFetcher.run_actor()`
- [ ] SCR-10: Add `PHANTOMBUSTER_API_KEY` and `PHANTOMBUSTER_API_KEY_2` to GitHub Actions secrets

### Phase 3 — Direct Scraper (unlimited fallback)

- [ ] SCR-11: Create `scraper/providers/direct_provider.py` — facebook-scraper lib, self-hosted on GitHub Actions
- [ ] SCR-12: Test direct scraper reliability on all 40 sources
- [ ] SCR-13: Add direct_provider as lowest-priority fallback in provider_pool
