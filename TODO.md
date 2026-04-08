Legends: [ ] new, [.] working, [x] done, [!] blocked
Dates: (YYYY-MM-DD →) = started, (YYYY-MM-DD → YYYY-MM-DD) = completed, no dates = not started

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
