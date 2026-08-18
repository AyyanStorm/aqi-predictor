# Manual QA Checklist — UI / Visual Layer (Q6, LOCKED scope)

Purpose: the things that are expensive to assert in code and fast to eyeball.
Run against the **live Render deployment** (per Q5: Render is the source of
truth) after the Wed 19 Aug staged deploy, plus a final pass on Fri 21 Aug
before the demo. Tick each box; note pass/fail + any screenshot.

## 1. Startup & navigation
- [ ] Dashboard loads without errors on first visit (cold start noted separately)
- [ ] Glass navbar renders: brand, page links (Dashboard/Map/Compare/Tracking/Analytics), location chip, settings, refresh
- [ ] Every nav link switches page correctly; active page is highlighted
- [ ] Page switch does not reset the selected location unexpectedly

## 2. Location & geolocation
- [ ] "Use my location" requests permission; granting resolves to the correct city (test with VPN off, PKT location)
- [ ] Denying permission falls back gracefully (IP detection → default city)
- [ ] City search: type-ahead works; selecting a city loads its forecast
- [ ] Country quick-pick: changing country updates the city list correctly
- [ ] Invalid/unknown city input handled without crash
- [ ] Timezone + current local time display correct for selected city

## 3. Forecast correctness (spot-check vs Open-Meteo)
- [ ] Current AQI matches the live value for Karachi/Lahore (within a few points)
- [ ] +24h/+48h/+72h forecast cards render; categories/colors match EPA bands
- [ ] Trend chart (past 24-48h) renders and matches current AQI
- [ ] SHAP/explanation panel renders without error
- [ ] "Refresh" updates the forecast and clears the cache

## 4. Map page
- [ ] Markers render; clicking a marker shows its AQI
- [ ] Heat grid loads (may be rate-limit paced on first load)
- [ ] Map is interactive (pan/zoom)

## 5. Compare / Tracking / Analytics
- [ ] Multi-city comparison table/chart renders
- [ ] Top-10 cities list correct for the selected country
- [ ] Tracking page shows saved predictions + accuracy stats
- [ ] Analytics page (charts, distributions) renders

## 6. Error & edge states
- [ ] Simulated API failure (airplane mode / kill network mid-load) shows a friendly error, no white screen
- [ ] Loading spinners appear during slow fetches
- [ ] Empty states (no data for a location) handled gracefully
- [ ] Rapid clicking / double refresh doesn't crash

## 7. Mobile / responsive
- [ ] 375px width: navbar usable, cards stack, charts fit
- [ ] 768px tablet: layout acceptable
- [ ] Desktop 1440px: intended glass layout

## 8. Visual regression
- [ ] Fonts (Orbitron display) load; glassmorphism backgrounds render
- [ ] No horizontal scrollbars, no overlapping text
- [ ] Chart tooltips work

---
Record results in `logs/manual_qa_<date>.md` with pass/fail and notes.
