# AQI Predictor — Final Project Report

**Author:** Ayyan Amir
**Program:** 10Pearls Data Science Internship
**Duration:** 27 Jul – 23 Aug 2026 (33 days)
**Repository:** https://github.com/AyyanStorm/aqi-predictor
**Live application:** https://aqi-predictor-blii.onrender.com
**Report date:** 22 Aug 2026 (Day 32)

---

## Executive Summary

AQI Predictor is a production-shaped machine-learning system that forecasts the Air
Quality Index (AQI) **24, 48 and 72 hours ahead** for any city in Pakistan — and, by
design, any latitude/longitude on Earth. It is built from five automated parts that run
on a schedule and feed each other: an hourly data-ingestion pipeline, a feature store, a
daily training pipeline with an automated model registry, an on-demand inference
pipeline, and a location-aware web dashboard backed by a REST API.

The headline result: a single **city-agnostic LightGBM model** (`lgbm_v12`), trained on
four years of hourly data from ten Pakistani cities (352,320 rows), forecasts +24h AQI at
**RMSE 17.6 / MAE 12.5 / R² 0.77** on a clean 60-day temporal holdout, and generalizes to
**Sialkot — a city it has never seen — at MAE 13.5**. Every pre-declared promotion gate
passes; the system is live, automated, and documented.

The project deliberately exceeds the brief. The brief asks to forecast "your city"; this
system forecasts *every* city, proven by a held-out city, served through an auto-detecting
dashboard and a public API.

---

## 1. Problem Statement

Air pollution is a daily health hazard across Pakistan, where cities like Lahore and
Faisalabad routinely enter "Very Unhealthy" and "Hazardous" AQI bands during the winter
smog season. People need **advance warning**, not just a current reading — knowing that
AQI will spike in 24–72 hours lets them plan outdoor activity, protect vulnerable family
members, and take precautions.

The task: build an end-to-end system that ingests real pollutant and weather data,
engineers features, trains and evaluates forecasting models, stores the best model in a
registry, automates the whole pipeline, and serves live +24/48/72h forecasts on an
interactive dashboard with explainability and hazard alerts.

### 1.1 The single decision that makes or breaks the project

Open-Meteo's `us_aqi` field is **not an independent measurement**. It is computed
deterministically from the same-hour pollutant concentrations (PM2.5, PM10, CO, NO₂, SO₂,
O₃) using the public US EPA breakpoint table. A model that predicts `us_aqi` from those
same readings at the same timestamp scores R² ≈ 0.999 — but that is not machine learning.
It is rediscovering a lookup table, and any domain reviewer spots it in thirty seconds.

The correct framing is **direct multi-horizon forecasting**: given everything observable
at time *t*, predict `us_aqi` at *t+24h*, *t+48h*, and *t+72h*. Three target columns,
three horizons, one honest problem.

---

## 2. Approach

### 2.1 Feature design — two legal families

Every feature must pass one test: *"Would I know this value at the moment I press
Predict?"* If not, it is leakage and it is deleted.

- **Family A — history (known at time *t*):** current pollutant concentrations and AQI;
  lags of AQI and PM2.5 at t−1h, t−3h, t−6h, t−12h, t−24h, t−48h, t−168h; rolling
  statistics (24h mean/max/std, 72h mean, 7-day mean); and the AQI change rate
  (`aqi_t − aqi_{t-24}`).
- **Family B — future weather at the target hour (legitimately known at inference):**
  forecast temperature, **wind speed**, **wind direction**, humidity, precipitation,
  pressure, and boundary-layer height *at the target timestamp*, plus calendar features
  (hour, day-of-week, month via sin/cos encoding, is_weekend).

Family B is legal because weather forecasts genuinely exist at prediction time — this is
exactly how real air-quality forecasting works. **Wind is the single most important
feature**: pollution is emission minus dispersion, and wind speed *is* dispersion.

### 2.2 The differentiator — a city-agnostic global model

To forecast *any* city rather than one hardcoded city, the model **never sees which city
it is looking at** — no name, no latitude, no longitude. It sees only physical and
temporal state. A model trained that way learns *atmospheric dynamics*, not *Karachi*, and
therefore transfers to any coordinate pair.

- **Training set:** 10 Pakistani cities × 4 years × hourly ≈ 352,320 rows, spanning
  Pakistan's full air-quality range — the Punjab smog belt (Lahore, Faisalabad,
  Gujranwala), coastal (Karachi, Hyderabad), arid highland (Quetta), and northern
  (Islamabad, Peshawar, Rawalpindi, Multan).
- **Validation of the claim:** one entire city — **Sialkot** — is held out of every
  training fold. Its reported metrics are the evidence that "works anywhere in Pakistan"
  is a real property, not a hope.

### 2.3 Serverless, zero-key architecture

Five parts, no paid services, no Docker, no Airflow:

| Part | Runs | Job |
|---|---|---|
| Feature pipeline | Hourly (GitHub Actions) | Ingest → engineer features → feature store |
| Historical backfill | Once (manual) | 4 years of history → training set |
| Training pipeline | Daily (GitHub Actions) | Train + evaluate → registry (auto-promote if better) |
| Inference pipeline | On demand | Latest features + model → +24/48/72h forecast |
| Dashboard + API | Always on (Render) | Location-aware forecast, trends, SHAP, alerts, REST |

Design rules that make it an architecture and not a script: `src/config.py` is the single
source of truth; `build_features.py` is shared by training and inference (no
training-serving skew); `open_meteo_client.py` is the only file that touches the network;
the feature store sits behind an adapter with a Parquet fallback.

---

## 3. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Data source | Open-Meteo (air-quality, archive, forecast, geocoding) | Free, no API key, global, 4+ years history |
| Data handling | pandas, numpy | Standard |
| Feature store | Parquet-on-disk (Hopsworks adapter ready) | Brief requirement; adapter keeps it swappable |
| Models | scikit-learn (Ridge, RandomForest), LightGBM, TensorFlow/Keras (LSTM) | Baseline → winner → deep-learning bullet |
| Model registry | Custom joblib registry with promotion logic | Versioning + automated promotion |
| Explainability | SHAP (TreeExplainer) | Fast, exact for tree models; brief requirement |
| Dashboard | Streamlit + Plotly | Pure Python, free hosting, interactive |
| API | FastAPI (`/health`, `/cities`, `/predict`) | Brief requires Streamlit **and** Flask/FastAPI |
| Geolocation | streamlit-js-eval → ipapi.co → Open-Meteo geocoding | Three-tier fallback, zero keys |
| Orchestration | GitHub Actions (cron + manual dispatch) | Free, lives with the code |
| Deployment | Render (blueprint: dashboard + API) | Free tier, public HTTPS, deploy from repo |
| Testing | pytest (95 tests) | Lightweight CI |

**Deliberately excluded:** Docker, Airflow, AWS, MLflow — each is defensible in a large
system and each would have consumed days without adding capability at this scale.

---

## 4. Experiments

The modeling progression walked deliberately from trivial baselines to deep learning, so
every later model has an honest yardstick.

| Model | Family | Role | Outcome |
|---|---|---|---|
| Persistence | Naive | "Tomorrow = today" floor | RMSE ~22–30 across horizons |
| Seasonal naive | Naive | "Same hour last cycle" floor | RMSE ~32 across horizons |
| Ridge regression | Linear | Interpretable baseline, scaled | Walk-forward RMSE 25.63 |
| Random Forest | Bagging | Feature importance, non-linear | Improved over Ridge |
| **LightGBM** | Boosting | **Production winner** | **Walk-forward RMSE 24.28** |
| LSTM (Keras) | Deep learning | Satisfies DL bullet; honest comparison | Did not beat LightGBM |

**Finding:** gradient-boosted trees (LightGBM) won decisively, as expected for tabular
time-series with engineered lags. The LSTM was built for completeness and an honest
comparison — it did not outperform LightGBM, which is a legitimate and commonly-observed
result reported transparently rather than hidden.

**Validation method:** walk-forward (time-series) cross-validation, never random splits —
random CV leaks the future into the past for temporal data. Model selection used a
pre-holdout window; final numbers come from a clean 60-day temporal holdout the winning
model never trained on.

---

## 5. Results

Production model: **`lgbm_v12`** — LightGBM trained strictly before the 60-day temporal
holdout (train end 2026-06-13, 337,910 rows).

### 5.1 Clean 60-day temporal holdout (14,410 rows, 10 cities)

| Horizon | RMSE | MAE | R² | MAPE | MAE target | Met? |
|---|---|---|---|---|---|---|
| +24h | **17.6** | 12.5 | 0.77 | 10.3% | ≤ 20 | ✅ |
| +48h | **22.1** | 16.0 | 0.64 | 13.1% | ≤ 25 | ✅ |
| +72h | **22.6** | 16.5 | 0.62 | 13.5% | ≤ 30 | ✅ |

Forecast skill decays with horizon (R² 0.77 → 0.62) — the expected, correct behavior for
weather-driven forecasting. A model that claimed near-perfect +72h accuracy would be more
suspicious than impressive.

### 5.2 Pre-declared promotion gates (all PASS)

| Gate | +24h | +48h | +72h |
|---|---|---|---|
| Beat persistence (RMSE) | 17.6 vs 22.4 ✅ | 22.1 vs 27.9 ✅ | 22.6 vs 30.2 ✅ |
| Beat seasonal-naive (RMSE) | 17.6 vs 32.0 ✅ | 22.1 vs 32.0 ✅ | 22.6 vs 31.9 ✅ |
| Beat previous production (v6) | ✅ satisfied by disqualification (see §6.1) |

### 5.3 Unseen-city generalization — Sialkot (35,232 rows, never in training)

| Horizon | RMSE | MAE | R² | MAPE |
|---|---|---|---|---|
| +24h | 17.4 | **13.5** | 0.82 | 10.6% |
| +48h | 22.7 | **18.0** | 0.70 | 14.5% |
| +72h | 23.7 | **18.9** | 0.68 | 15.2% |

The model performs on Sialkot as well as on cities it trained on — the strongest single
piece of evidence for the "works anywhere in Pakistan" claim.

### 5.4 Per-city accuracy (holdout, +24h)

| City | MAE | RMSE | | City | MAE | RMSE |
|---|---|---|---|---|---|---|
| Karachi | 3.9 | 5.0 | | Peshawar | 13.3 | 16.7 |
| Hyderabad | 5.2 | 6.8 | | Faisalabad | 13.8 | 18.3 |
| Rawalpindi | 12.3 | 15.9 | | Gujranwala | 15.5 | 20.3 |
| Islamabad | 12.4 | 16.0 | | Lahore | 17.7 | 26.0 |
| Multan | 12.9 | 16.5 | | Quetta | 18.0 | 23.4 |

Best on the low-variance coastal cities (Karachi, Hyderabad); hardest on the Punjab smog
belt (Lahore, Gujranwala) and high-altitude Quetta, where AQI swings are largest — yet all
cities land within the reporting targets.

### 5.5 Predicted-vs-actual analysis (holdout)

| Horizon | Correlation | Mean bias | Within ±10 | Within ±20 |
|---|---|---|---|---|
| +24h | 0.88 | −1.9 | 53.8% | 79.6% |
| +48h | 0.80 | −3.3 | 43.3% | 69.0% |
| +72h | 0.79 | −3.7 | — | — |

A slight systematic under-prediction (negative bias growing with horizon) — typical for
mean-regressing forecasts of spiky AQI. Roughly 70–80% of predictions land within ±20 AQI.

### 5.6 Data health

The 4-year feature store passed a full data-quality audit: **352,320 rows** (10 cities ×
35,232), **0 duplicate (city, date) rows**, UTC-aware timestamps with **perfect hourly
cadence**, no missing targets, no impossible values, and an explicit leakage audit that
confirms targets are shifted into the future. Documented caveats: a Open-Meteo archive gap
in `boundary_layer_height` for 2024-H1 (handled by imputation; the forecast API is
unaffected) and 10 real extreme-event rows above the EPA cap (kept and documented).

### 5.7 Live performance (Render, median of 7 warm runs)

| Endpoint | Before | After | P95 | Target | Status |
|---|---|---|---|---|---|
| `/health` | 0.33s | **0.21s** | 0.22s | < 0.5s | ✅ |
| `/cities` | 0.24s | **0.21s** | 0.26s | < 1s | ✅ |
| `/predict` (Karachi) | 0.70s | **0.89s** | 1.00s | < 1.5s | ✅ |
| Dashboard root | 0.40s | **0.38s** | 0.50s | < 3s | ✅ |

`/predict` rose slightly because the app now serves the heavier v12 model — still 40%
under target. The full automated regression suite (**95/95 tests**) passes on the live
deployed code.

---

## 6. Honesty Notes & Limitations

### 6.1 Why the previous production model was disqualified

The previous production model, v6, posts *better-looking* holdout numbers
(RMSE 15.9/19.1/19.7) than v12 — but only because v6 was trained on data through August
2026 that **overlaps the 60-day holdout**, memorizing ~54 of 60 holdout days. On the
genuinely-unseen Sialkot comparison, v12 wins or ties v6 at every horizon. Reporting v6's
overlap-inflated numbers would be dishonest, so they are documented and excluded, and Gate
3 is treated as *satisfied by disqualification*. This is the single most important
methodological decision in the project: **we chose the honest number over the pretty one.**

### 6.2 Known limitations

- **+72h skill is lower** (R² 0.62). This is expected — forecast uncertainty compounds
  with horizon — and is reported honestly rather than masked.
- **Under-prediction bias** on extreme spikes: the model mean-regresses, so the very worst
  smog peaks are slightly under-called. Hazard alerts partly compensate by triggering on
  band, not exact value.
- **Boundary-layer data gap** (2024-H1) in the archive API; imputed, not backfilled.
- **Render free tier cold start**: the first request after idle incurs a spin-up delay
  (measured separately, excluded from performance gates); warm performance is well within
  targets.
- **National, not truly global**: the "works anywhere" claim is proven for Pakistan's
  climate regimes via Sialkot; extending the proof to other continents would need
  out-of-region holdouts.

---

## 7. Future Work

- **Ensemble the horizons** or add quantile/prediction-interval outputs so the dashboard
  can show uncertainty bands, not just point forecasts.
- **Spike-aware training** (e.g. weighted loss or a dedicated extreme-event head) to reduce
  the under-prediction bias on the worst smog days.
- **Backfill the boundary-layer gap** from an alternative reanalysis source.
- **Out-of-region validation** to upgrade "works anywhere in Pakistan" toward a broader
  global claim.
- **Model monitoring in production**: log live predicted-vs-actual over time (the Tracking
  view already seeds this) and trigger retraining on drift.
- **Hopsworks feature store** swap-in (adapter already in place) if a managed store is
  preferred over the Parquet fallback.

---

## 8. Conclusion

AQI Predictor delivers what the 10Pearls brief asked for and more: an end-to-end,
automated, serverless ML system that forecasts AQI 24–72 hours ahead, stores versioned
models in a registry, runs itself on GitHub Actions, and serves an explainable,
location-aware dashboard plus a REST API on a public URL. Every brief requirement is mapped
and satisfied (see the compliance map in `docs/ROADMAP.md §11`).

The differentiator — a single city-agnostic model proven on an unseen city — turns "predict
my city" into "predict any city," backed by evidence rather than assertion. And the project
was built with an engineer's discipline throughout: single-source-of-truth config, shared
feature code to prevent training-serving skew, an explicit leakage audit, walk-forward
validation, pre-declared promotion gates, and a documented decision to prefer the honest
metric over the flattering one.

---

## Appendix — Evidence & Deliverables

- **Final Model Health Report:** `docs/FINAL_MODEL_HEALTH_REPORT.md`
- **Architecture:** `docs/ARCHITECTURE.md`
- **Roadmap & brief compliance map:** `docs/ROADMAP.md`
- **QA:** `docs/QA_TEST_PLAN.md`, `docs/MANUAL_QA_CHECKLIST.md`
- **Audit scripts:** `scripts/audit/{data_audit,model_audit,model_select,final_candidate_eval}.py`
- **Benchmark scripts:** `scripts/benchmark/{before,after}_benchmark.py`
- **Evidence logs:** `logs/{data_audit,model_audit_before,model_audit_after_v2,model_select,before_benchmark,after_benchmark}.json`
- **Live app:** https://aqi-predictor-blii.onrender.com
- **Repository:** https://github.com/AyyanStorm/aqi-predictor
