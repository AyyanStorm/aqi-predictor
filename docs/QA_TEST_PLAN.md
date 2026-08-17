# QA Test Plan — AQI Predictor (Day 26 phase)

Scope: functional, data, model, API, UI, regression, edge-case testing.
Status key: ✅ automated (test file) · 👁 manual checklist (docs/MANUAL_QA_CHECKLIST.md) · 🔄 pending

## Functional testing
| Feature | Status | Where |
|---|---|---|
| App startup (Streamlit) | ✅ | tests/test_app_smoke.py — test_app_starts_without_exception |
| All 5 views render | ✅ | tests/test_app_smoke.py — test_all_pages_render_without_exception |
| City search / picker / country detection | ✅ logic | tests/test_country_cities.py + geo probe (Day 26) |
| Geolocation | 👁 | manual checklist §2 |
| Timezone / local time / +24/+48/+72h times | ✅ | tests/test_local_time.py |
| Current AQI + prediction (inference path) | ✅ | tests/test_inference.py + live probe (Karachi 69/66/67/70) |
| Forecast cards / charts / explanations | ✅ render | smoke tests; visuals 👁 §3 |
| Historical data / multi-city compare / top-10 | ✅ render | smoke tests; correctness 👁 §5 |
| Global AQI map | ✅ render | smoke tests; visuals 👁 §4 |
| Navigation / refresh | ✅ cache logic | tests/test_inference.py, smoke; 👁 §1,§3 |
| Error handling / loading / empty states | 👁 | manual §6 |

## Data testing
- ✅ data_audit.py on the 4-year store: duplicates, timestamps/UTC, cadence gaps, coverage,
  city mapping, invalid AQI, outliers (IQR), impossible values, leakage, target construction,
  target alignment. Result: PASS with 3 documented caveats.
- ✅ Live tracking store: 22 records, no nulls, consistent model/version.

## Model testing
- ✅ model_audit.py: v6 on 60-day holdout vs persistence + seasonal-naive (all gates PASS);
  Sialkot generalization eval (MAE 13.6/18.2/19.2); per-city + per-AQI-band breakdowns.
- ✅ model_select.py: Ridge/RF/LGBM walk-forward on pre-holdout data → winner **lgbm**
  (mean RMSE 24.3 vs ridge 25.6 vs persist 29.0 vs seasonal 36.7).
- ✅ final_candidate_eval.py: winner trained strictly-before-holdout → **all Q3 hard gates
  PASS** on 60-day holdout (MAE 12.5/16.0/16.5; RMSE 17.6/22.1/22.6; R2 0.77/0.64/0.62;
  MAPE 10.3/13.1/13.5%); Sialkot MAE 13.6/17.8/18.6.
- ✅ accuracy-tracking component (live pred vs retro-actual): 3 mature records, 99.9/98.2/99.3%.
- ⚠️ Registry note (17 Aug): CI pipeline promoted its own v11 (full-data refit, overlaps
  holdout) overnight. QA candidate = **v12 / lgbm_v10_local_candidate.joblib** — the
  strictly-before-holdout model. Promote v12 on Wed, NOT v10/v11 (see AUDIT_PLAN).

## API testing (FastAPI TestClient, no network)
- ✅ tests/test_api.py: /health, /cities, /predict happy path, missing params (422),
  out-of-range lat (422), no-data coords (200 — P2 finding: silently interpolated).

## UI testing
- ✅ Streamlit AppTest smoke (each view loads, no exception).
- 👁 Manual checklist on live Render post-deploy (Wed 19 Aug + Fri 21 Aug): layout, fonts,
  responsive (375/768/1440), chart tooltips, map interaction, permission flows.

## Regression testing
- ✅ Full suite **95/95 passing (24.8s)** on 17 Aug after the Day 27 P0/P1 fixes
  (baseline run was 87/95 — see findings below).
- Re-run full suite after every optimization batch; CI gate stays green.

## Day 27 findings (17 Aug) — found + fixed
1. **P0 — environment break (not code):** local env had numpy 1.26.3 + scipy 1.18.0, but
   scipy 1.18.0 requires numpy>=2.0 → EVERY LightGBM artifact failed to unpickle
   (`np.long` AttributeError) → 8 tests failed. FIX: numpy upgraded to 2.4.6 (within the
   feature-store pin `<2.5`); requirements.txt now pins `numpy>=2.0,<2.5`. Committed 9610989.
2. **P1 — latent bug exposed by numpy 2.x:** predict.py `row.round(4)` raised "Expected
   numeric dtype, got object instead" — the prediction row arrives mixed
   float32/float64/int64, which pandas keeps as object dtype under numpy 2.x.
   FIX: `row = row.astype(float)` before `row.to_frame().T` in `predict()`. Committed 9610989.
- Result: 95/95 green; models v6/v10/v11/v12 all load.

## Edge-case testing
- ✅ Geo/country: case-insensitive, whitespace, unknown country/city, None → graceful.
- ✅ API: missing params, out-of-range coords.
- ✅ AQI: values past EPA cap (500-537) are real events, kept + documented.
- ✅ Sensor-noise negatives (NO2 -1.5, O3 -12): tolerated (LightGBM), documented.
- ✅ High-altitude city (Quetta pressure 825-848 hPa): valid, audit range fixed.
- 🔄 Empty state / offline / rapid refresh: manual §6.

## Priority classification (brief §11)
- **P0 (critical):** none open. (Env break found+fixed on 17 Aug — see above.)
- **P1 (high):** none open. (predict.py object-dtype bug found+fixed on 17 Aug — see above.)
- **P2 (medium):** no-data locations silently predicted (South Pacific → 200 with plausible
  forecast). Decision: accept + document (Open-Meteo grid interpolation), or add a
  confidence/fail-loud guard post-submission. Not blocking demo.
- **P3 (low):** repo tracks 29MB data/ parquets despite .gitignore — DECISION (17 Aug):
  keep tracked through the demo (Render boot dependency), document in final report;
  normalize_country('PK') → None (ISO code unmapped, UI never sends it) → fold into
  Wed Stage 1 low-risk fixes.

## Remaining work
1. Manual checklist (docs/MANUAL_QA_CHECKLIST.md) on live Render — Wed 19 Aug post-deploy + final pass Fri 21 Aug (Q5/Q6 scope: layout, responsive, map, permission flows, error states).
2. Optimization batch (measure → fix → re-measure) after Wed deploy; then after-benchmark + before/after table (Day 29–30).
3. Final Model Health Report (brief §12) — final numbers land by Sat 22 Aug.
