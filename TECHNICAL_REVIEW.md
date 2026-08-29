# 🔍 Technical Review: AQI Predictor System

**Reviewer:** AI Technical Analyst
**Date:** 2026-08-29
**Scope:** Complete system analysis (architecture, code, testing, deployment, monitoring)
**Codebase Size:** 9,269 LOC (src + app) | 980 LOC (tests) | 1,190 Python files total

---

## Executive Summary

**Overall Health:** ⚠️ **GOOD with CRITICAL GAPS**

### Strengths
✅ Excellent validation strategy (temporal + unseen-city holdouts)
✅ Solid architectural separation (feature → training → inference)
✅ Clean code structure with single-responsibility patterns
✅ Comprehensive model health documentation
✅ Automated pipelines (hourly ingest, daily training, CI gates)

### Critical Issues
🔴 **No error recovery** in production inference/serving
🔴 **Minimal monitoring/alerting** for data quality and model drift
🔴 **No graceful degradation** when external APIs fail
🔴 **Insufficient logging** in critical paths
🔴 **No API rate limiting** despite external dependency on Open-Meteo

### High-Impact Improvements Needed
1. Production resilience & error handling
2. Observability & monitoring (data quality, model drift, API health)
3. Circuit breakers & fallback strategies
4. Comprehensive test coverage (currently 10.5% code coverage)
5. Database abstraction layer (currently tightly coupled to Parquet)

---

## 1. ARCHITECTURE & DESIGN

### 1.1 Strengths

✅ **Clean Separation of Concerns**
- Feature pipeline isolated from training
- Inference decoupled from serving layer
- Single feature builder (`build_features.py`) prevents training-serving skew
- Good use of configuration centralization (`config.py`)

✅ **Elegant Handle of Feature Store Duality**
- Plan B (Parquet) prevents vendor lock-in
- Graceful fallback from Hopsworks to local files
- No code changes between environments

✅ **Deliberate Validation Strategy**
- 60-day temporal holdout never seen by training
- Unseen-city validation (Sialkot) proves generalization
- Pre-declared gates locked before training

### 1.2 Gaps & Weaknesses

🔴 **No Abstraction for Feature Store**
- Code tightly coupled to both Hopsworks API and Parquet schema
- `feature_store.py` directly handles both backends with many conditionals
- **Risk:** Changing backends requires code refactoring
- **Fix:** Create a `FeatureStoreBackend` abstract base class

```python
# Proposal:
class FeatureStoreBackend(ABC):
    @abstractmethod
    def write(self, df: pd.DataFrame) -> None: ...
    @abstractmethod
    def read(self, city: str, date_range: tuple) -> pd.DataFrame: ...

class HopsworksBackend(FeatureStoreBackend): ...
class ParquetBackend(FeatureStoreBackend): ...
```

🔴 **No Database Persistence for Predictions**
- Prediction tracking stored in local SQLite (`.tracking_store.db`)
- Not synced to feature store or cloud
- **Risk:** Tracking data lost if container restarts
- **Fix:** Move tracking to Hopsworks or persistent cloud store

🔴 **Missing Circuit Breaker Pattern**
- Open-Meteo API calls have no circuit breaker
- 429 rate limits (seen in backfill) can cascade failures
- Forecast API outages bring down entire dashboard
- **Fix:** Implement exponential backoff + circuit breaker

```python
from pybreaker import CircuitBreaker

api_breaker = CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    listeners=[BreakerListener()]
)

@api_breaker
def fetch_forecast():
    return requests.get(FORECAST_URL, timeout=30)
```

🔴 **No Fallback Strategy for Stale Data**
- If hourly pipeline fails, next prediction uses 24h+ old data
- No alerting when data is stale
- **Risk:** Silent degradation without user awareness
- **Fix:** Track data freshness, serve stale-data warnings

🟡 **Tightly Coupled Model Loading**
- Model registry hardcoded to `data/models/registry/`
- No support for remote model registries (S3, GCS, etc.)
- **Risk:** Limits scalability to multi-region deployments

---

## 2. DATA PIPELINE & RELIABILITY

### 2.1 Strengths

✅ **Idempotent Feature Engineering**
- `hourly_ingest.py` uses upsert pattern (idempotent)
- Can be re-run safely without duplicates
- Good use of UTC timestamps

✅ **Documented Data Gaps**
- Known caveat: `boundary_layer_height` null Jan–Jun 2024
- 10 extreme AQI rows documented and kept
- Audit script validates no leakage

### 2.2 Gaps & Weaknesses

🔴 **No Data Quality Monitoring**
- Data audit (`scripts/audit/data_audit.py`) is **one-time, manual**
- No continuous validation in production pipelines
- Example: boundary-layer nulls not imputed, just noted
- **Risk:** Retraining on degraded data goes unnoticed
- **Fix:** Add data quality checks to `feature_pipeline.yml`

```yaml
- name: Validate data quality
  run: python -m src.data_ingestion.validate --check-freshness --check-nulls --max-missing-pct=5
```

🔴 **Open-Meteo Rate Limiting Unhandled**
- Backfill pipeline saw 429s (documented in code comments)
- No exponential backoff in `open_meteo_client.py`
- Retry logic has only 3 retries with 0.3s backoff (too weak)
- **Risk:** Backfill can take hours, blocking training
- **Fix:** Implement adaptive backoff + respect Retry-After header

```python
# Current (weak):
retry_session = retry(cache_session, retries=3, backoff_factor=0.3)

# Better:
retry_session = retry(cache_session, retries=5, backoff_factor=0.5)
# Plus parse 'Retry-After' header from 429 responses
```

🟡 **No Partition Strategy for Feature Store**
- Single Parquet file or Hopsworks table grows unbounded
- Future scaling to 100+ cities or months of hourly data could slow queries
- **Recommendation:** Partition by city + date (Parquet supports this)

🟡 **Missing Data Lineage**
- No record of which Open-Meteo API versions were used
- No audit trail of feature transformations
- Makes troubleshooting drifts harder

---

## 3. MODEL TRAINING & VALIDATION

### 3.1 Strengths

✅ **Walk-Forward Cross-Validation**
- Proper temporal validation (not shuffled CV)
- Prevents lookahead bias
- Pre-declared promotion gates all pass

✅ **Multi-Horizon Evaluation**
- Separate models for +24h, +48h, +72h (or single multi-output model)
- Honest reporting that skill degrades with horizon

✅ **Unseen-City Generalization Test**
- Sialkot validation proves model doesn't memorize city IDs
- RMSE/MAE/R² reported per city

### 3.2 Gaps & Weaknesses

🔴 **No Model Drift Detection**
- No continuous monitoring of prediction accuracy
- v11 → v12 "auto-promotion" happens without live A/B testing
- **Risk:** Worse model silently replaces good one for days
- **Fix:** Implement prediction-vs-actual tracking with alerting

```python
# Proposal in src/tracking/drift_detector.py:
class DriftDetector:
    def check_drift(self, predictions_df, actuals_df, threshold_rmse=3.0):
        rmse = np.sqrt(mean_squared_error(actuals_df, predictions_df))
        if rmse > threshold_rmse:
            alert_ops("Model drift detected: RMSE={rmse}")
```

🔴 **Prediction Tracking is Weak**
- Tracking table only has: `pred_time, city, horizon, pred_aqi, actual_aqi`
- No: model version, feature values, error magnitude, prediction confidence
- Can't debug why a specific prediction was wrong
- **Fix:** Expand tracking to include features and model metadata

🟡 **No Hyperparameter Sensitivity Analysis**
- `train.py` has hardcoded LightGBM hyperparameters
- No analysis of which params matter most
- Retraining daily could use cached hyperparams instead
- **Recommendation:** Run Optuna/Hyperopt weekly, not daily

🟡 **No Calibration Checks**
- Model outputs uncalibrated probabilities/predictions
- No check if confidence intervals are valid
- EPA health messages based on point predictions, not uncertainty bands

🟡 **LSTM Baseline Abandoned**
- `src/training/lstm.py` exists but is unused
- No comparison of LSTM vs LightGBM on holdout
- Decision to use LightGBM not empirically justified on final data

---

## 4. SERVING LAYER (API & DASHBOARD)

### 4.1 Strengths

✅ **Clean FastAPI Implementation**
- Proper HTTP status codes (503 when no model, 400 on bad coords)
- Structured logging middleware for every request
- `/health`, `/cities`, `/predict` endpoints well-defined
- Serializable response (current AQI + forecast + features)

✅ **Streamlit Dashboard**
- Multi-page layout (Dashboard, Map, Compare, Tracking, Analytics)
- Glassmorphism design system
- Geolocation awareness (browser GPS → IP fallback)
- SHAP explainability ("why" for every forecast)

### 4.2 Gaps & Weaknesses

🔴 **No Caching Strategy**
- Every page load fetches live weather forecast
- Global map redraws 6h data each load (documented in ARCHITECTURE)
- **Risk:** O(n) API calls per user session
- **Fix:** Add Redis/Streamlit caching with TTL

```python
@st.cache_data(ttl=3600)  # Cache forecast for 1h
def get_forecast(lat, lon):
    return fetch_live_frame(lat, lon)
```

🔴 **No Rate Limiting**
- API has no per-IP rate limiting
- Dashboard allows unlimited forecast requests
- Could be DoS'd by bot
- **Fix:** Add rate limiter middleware

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter

@app.get("/predict")
@limiter.limit("30/minute")
def predict_endpoint(...): ...
```

🔴 **Minimal Error Context in Responses**
- API returns `{"detail": "..."}` on 5xx errors
- No request ID for debugging
- Users can't report errors with sufficient context
- **Fix:** Add request IDs (UUID) to every response

```python
@app.get("/predict")
def predict_endpoint(...):
    request_id = str(uuid.uuid4())[:8]
    try:
        return {"data": ..., "request_id": request_id}
    except Exception as e:
        log_event(logger, "prediction_error", request_id=request_id, error=str(e))
        return JSONResponse(status_code=500, 
                           content={"error": str(e), "request_id": request_id})
```

🟡 **Streamlit State Management**
- Dashboard state (selected city, forecast horizon) stored in Streamlit's session cache
- Navigating away / back loses state
- **Recommendation:** Use URL query params + Streamlit query param sync

🟡 **No Offline Mode**
- Dashboard requires Open-Meteo API for every render
- Forecast endpoint dependency: if Open-Meteo is down, entire app breaks
- **Recommendation:** Cache last-known forecast in browser localStorage

🟡 **No Accessibility Audit**
- No WCAG 2.1 compliance check
- Glassmorphism design may have low contrast issues
- **Recommendation:** Run axe-core accessibility scanner

---

## 5. TESTING & CODE QUALITY

### 5.1 Strengths

✅ **95 Unit Tests**
- Good coverage of features, inference, API, app
- Mocked external dependencies (no network calls)
- CI gate on every push
- ~2min runtime (fast feedback)

✅ **Code Organization**
- Single-responsibility modules
- Consistent naming conventions
- Detailed docstrings (especially predict.py, train.py)
- Good use of config centralization

### 5.2 Gaps & Weaknesses

🔴 **Insufficient Code Coverage**
- 95 tests for 9,269 LOC = **10.5% coverage**
- Critical modules untested:
  - `model_registry.py` — no rollback/promotion tests
  - `tracking/store.py` — no accuracy tracking tests
  - `data_ingestion/historical_backfill.py` — brittle, high-risk
- **Fix:** Aim for 70%+ coverage on critical paths

```bash
# Current (from CI):
# Missing coverage for:
# - model_registry.py: promotion gate logic
# - feature_store.py: Hopsworks vs Parquet fallback
# - open_meteo_client.py: 429 handling
# - API middleware: error handling
```

🔴 **No Integration Tests**
- All tests are unit tests (mocked)
- No end-to-end tests (e.g., real Open-Meteo API call → full prediction)
- No Streamlit app automation tests
- **Risk:** Can't catch training-serving skew or API failures until production

🔴 **No Chaos Testing**
- No tests for:
  - Network timeouts (Open-Meteo unreachable)
  - Malformed API responses
  - Missing model artifact
  - Corrupted feature store
- **Fix:** Add pytest fixtures for common failure modes

```python
@pytest.fixture
def mock_open_meteo_timeout():
    with patch('src.data_ingestion.open_meteo_client.openmeteo') as m:
        m.side_effect = requests.Timeout("API unreachable")
        yield m

def test_predict_handles_api_timeout(mock_open_meteo_timeout):
    with pytest.raises(RuntimeError, match="Could not fetch forecast"):
        predict(lat=24.86, lon=67.01)
```

🟡 **No Load Testing**
- No measurement of concurrent user limits
- No stress test of Render's free tier
- Dashboard might crash under traffic spike

🟡 **No Security Testing**
- No SQL injection tests (not applicable, but ORM-level checks)
- No XSS checks in Streamlit inputs
- No authentication/authorization (public app, but still good practice)

---

## 6. DEPLOYMENT & OPERATIONS

### 6.1 Strengths

✅ **Automated Deployment (Render Blueprint)**
- Auto-deploy on `main` push
- Two services (API + Dashboard) versioned together
- HTTPS + geolocation support

✅ **GitHub Actions Automation**
- Hourly feature pipeline
- Daily training + auto-promotion
- CI gate on every push
- One-shot backfill with workflow_dispatch

✅ **Staged Model Rollout**
- New versions are "candidates" until they beat production
- Rollback is a pointer change (fast, safe)

### 6.2 Gaps & Weaknesses

🔴 **No Monitoring or Observability**
- No Datadog, New Relic, or Prometheus metrics
- Render's built-in logs are basic
- **Missing KPIs:**
  - Prediction latency (P50, P95, P99)
  - Feature pipeline success rate
  - Model drift (RMSE over time)
  - API error rate (4xx, 5xx)
  - Data freshness (age of latest training data)
- **Risk:** Silent failures go unnoticed for hours
- **Fix:** Add observability stack

```python
# Proposal: integrate Prometheus
from prometheus_client import Counter, Histogram, Gauge

prediction_latency = Histogram('prediction_latency_seconds', 'API latency')
model_drift = Gauge('model_rmse_holdout', 'Production model RMSE on latest holdout')
data_freshness = Gauge('feature_store_age_hours', 'Hours since last ingest')

@app.get("/predict")
def predict_endpoint(...):
    with prediction_latency.time():
        return predict(...)
```

🔴 **No Alerting Rules**
- No notifications when:
  - Feature pipeline fails
  - Training pipeline produces worse model (promotion blocked)
  - Prediction accuracy drops
  - Render service goes down
- **Fix:** Add GitHub Issues / Slack alerts

```yaml
# github_actions/alerts.yml
- name: Alert on training failure
  if: failure()
  uses: actions/github-script@v7
  with:
    script: |
      github.rest.issues.create({
        owner: context.repo.owner,
        repo: context.repo.repo,
        title: "🚨 Training pipeline failed",
        labels: ["alert"]
      })
```

🔴 **No Gradual Rollout**
- New model goes from candidate → production instantly
- No canary deployment (e.g., 10% traffic → 50% → 100%)
- **Risk:** Bad model affects all users immediately
- **Fix:** Implement canary via Render's blue-green deployment

🟡 **Limited Log Retention**
- Render's free tier deletes logs after 7 days
- Can't debug issues from last month
- **Recommendation:** Stream logs to CloudWatch or similar

🟡 **No Backup Strategy**
- Feature store committed to Git (good), but not replicated
- Model registry lives in `/data/` (gitignored)
- Single point of failure if Render's persistent volume fails

🟡 **No Disaster Recovery Plan**
- No RTO/RPO targets documented
- No procedure for data loss recovery
- **Recommendation:** Document "If X fails, run Y"

---

## 7. DEPENDENCIES & SECURITY

### 7.1 Strengths

✅ **Minimal Dependencies**
- No heavy frameworks (FastAPI is lightweight)
- Core libraries well-maintained (pandas, scikit-learn, LightGBM)
- No vendor lock-in (Open-Meteo is free/open)

✅ **Separated Environments**
- Main app (`requirements.txt`) isolated from feature store (`requirements-feature-store.txt`)
- Avoids protobuf conflicts documented in code comments

### 7.2 Gaps & Weaknesses

🔴 **No Dependency Pinning**
- `requirements.txt` uses loose version specs (`numpy>=2.0,<2.5`)
- Could break unexpectedly if a transitive dep updates
- **Fix:** Use pip-compile to pin all transitive deps

```bash
pip-compile requirements.in --output-file requirements.txt
# Ensures: pandas==2.1.3, numpy==2.0.1, etc. (exact)
```

🔴 **No Supply Chain Security**
- No hash verification (pip can be compromised)
- No Software Bill of Materials (SBOM)
- No automated dependency scanning (GitHub Dependabot, Snyk)
- **Fix:** Enable GitHub Dependabot

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

🟡 **Docker Image Security**
- Using `python:3.12-slim` (good choice for size)
- But running as root in containers
- No image scanning for vulnerabilities
- **Recommendation:** Add non-root user + image scanning

```dockerfile
RUN useradd -m -u 1000 appuser
USER appuser
```

---

## 8. DOCUMENTATION & MAINTAINABILITY

### 8.1 Strengths

✅ **Excellent Decision Documentation**
- ARCHITECTURE.md explains every design choice
- FINAL_MODEL_HEALTH_REPORT.md is thorough
- Code comments are detailed (especially predict.py, train.py)
- AUDIT_PLAN.md locks decisions before implementation

✅ **Roadmap Preserved**
- ROADMAP.md documents 31-day build log
- Every day has outcomes, next-day planning
- Serves as institutional memory

### 8.2 Gaps & Weaknesses

🟡 **No Runbook Documentation**
- No "How to respond to X" procedures:
  - "Model promotion blocked, what now?"
  - "Feature pipeline failed, how to restart?"
  - "Data looks stale, where to check?"
- **Recommendation:** Create `docs/RUNBOOKS.md`

```markdown
## Runbook: Feature Pipeline Failed

**Symptom:** GitHub Actions shows ❌ on `feature_pipeline`
**Impact:** Predictions use stale data (>24h old)
**Steps:**
1. Check logs: https://github.com/.../actions/runs/XXX
2. If network timeout: wait 30min, manually trigger
3. If auth error: rotate HOPSWORKS_API_KEY
4. If parse error: email @ayyan with logs
```

🟡 **No Troubleshooting Guide**
- No FAQ for common issues
- New contributors won't know where to start

🟡 **API Documentation Missing**
- No OpenAPI/Swagger UI enabled on FastAPI
- **Fix:** Add one line to api.py

```python
app = FastAPI(docs_url="/docs", redoc_url="/redoc")
```

---

## 9. SCALABILITY & FUTURE READINESS

### 9.1 Current Limitations

🟡 **Single-City-at-a-Time Architecture**
- Features for only 10 cities in training
- Can't quickly expand to 100 cities
- Each city needs backfill + training
- **Recommendation:** Batch ingest for multiple cities

🟡 **Daily Retraining is Rigid**
- Retrains every 24h regardless of data quality
- No early stopping if new data is bad
- **Recommendation:** Conditional retraining based on data validation

🟡 **Manual Feature Engineering**
- Features hard-coded in `build_features.py`
- Adding new weather variables requires code edit + test + deploy
- **Recommendation:** Feature store schema versioning + runtime schema inference

---

## 10. SUMMARY OF RECOMMENDATIONS (Priority Order)

### 🔴 CRITICAL (Do Now)
1. **Add Observability** — Prometheus/Grafana for model RMSE, API latency, data freshness
2. **Implement Error Handling** — Graceful degradation when Open-Meteo is down
3. **Add Data Quality Checks** — Automated validation in feature pipeline
4. **Increase Test Coverage** — Aim for 70%+ on critical paths (model_registry, tracking)
5. **Add Request IDs & Better Error Responses** — Improve debugging

### 🟠 HIGH (Do This Sprint)
6. **Circuit Breaker for API** — Rate limit handling, exponential backoff
7. **Model Drift Detection** — Auto-alert if RMSE increases >5%
8. **Feature Store Abstraction** — Remove Hopsworks/Parquet coupling
9. **Add Caching** — Redis/Streamlit cache for forecasts
10. **Rate Limiting** — Protect API from abuse

### 🟡 MEDIUM (Next Month)
11. **Integration Tests** — End-to-end prediction tests
12. **Monitoring Dashboard** — Grafana showing system health
13. **Dependency Pinning** — Use pip-compile for reproducibility
14. **Runbooks** — Operational procedures for common failures
15. **Canary Deployment** — Gradual rollout of new models

### 🟢 NICE-TO-HAVE (Backlog)
16. OpenAPI docs at `/docs`
17. SBOM generation
18. Load testing (k6, locust)
19. Security scanning (trivy, snyk)
20. Database abstraction for tracking

---

## 11. CODE EXAMPLES FOR TOP IMPROVEMENTS

### A. Observability Integration

```python
# src/utils/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Metrics
prediction_latency = Histogram(
    'aqi_prediction_latency_seconds',
    'Time to generate prediction',
    buckets=(0.1, 0.5, 1.0, 2.0),
    labelnames=['horizon']
)

model_accuracy = Gauge(
    'aqi_model_rmse_production',
    'RMSE of production model on holdout',
    labelnames=['horizon']
)

data_freshness = Gauge(
    'aqi_feature_store_age_hours',
    'Hours since last feature update'
)

api_errors = Counter(
    'aqi_api_errors_total',
    'Total API errors',
    labelnames=['error_type', 'endpoint']
)
```

### B. Error Recovery

```python
# src/inference/predict.py
import logging
from functools import wraps
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def fetch_live_frame(lat, lon, city):
    """Fetch with exponential backoff + retry."""
    try:
        return _fetch_live_frame_unsafe(lat, lon, city)
    except requests.Timeout as e:
        raise RuntimeError(f"Forecast API timeout: {e}") from e
    except requests.ConnectionError as e:
        raise RuntimeError(f"Forecast API unreachable: {e}") from e

def predict(lat, lon, city=None):
    """Predict with graceful degradation."""
    try:
        frame = fetch_live_frame(lat, lon, city)
        return _predict_unsafe(frame)
    except RuntimeError as e:
        # Serve stale cache if available
        logger.error(f"Prediction failed: {e}")
        cached = get_last_known_prediction(lat, lon)
        if cached and cached['age_hours'] < 24:
            return {**cached, 'warning': 'Using cached prediction (API unavailable)'}
        raise
```

### C. Data Quality Checks

```python
# src/data_ingestion/validate.py
class DataQualityValidator:
    def __init__(self, feature_df):
        self.df = feature_df
    
    def check_freshness(self, max_age_hours=6):
        latest = self.df['date'].max()
        age = (pd.Timestamp.now(tz='UTC') - latest).total_seconds() / 3600
        if age > max_age_hours:
            raise ValueError(f"Data stale: {age:.1f}h old")
        return True
    
    def check_nulls(self, max_missing_pct=2):
        null_pcts = (self.df.isnull().sum() / len(self.df) * 100).sort_values()
        if (null_pcts > max_missing_pct).any():
            raise ValueError(f"Excessive nulls: {null_pcts[null_pcts > max_missing_pct]}")
        return True
    
    def check_duplicates(self):
        dup_rows = self.df.duplicated(subset=['city', 'date'])
        if dup_rows.any():
            raise ValueError(f"Found {dup_rows.sum()} duplicate rows")
        return True
    
    def run_all(self):
        self.check_freshness()
        self.check_nulls()
        self.check_duplicates()
        logger.info("✅ All data quality checks passed")
```

### D. Circuit Breaker

```python
# src/data_ingestion/circuit_breaker.py
from pybreaker import CircuitBreaker

class OpenMeteoBreaker(CircuitBreaker):
    def __init__(self):
        super().__init__(
            fail_max=5,
            reset_timeout=300,  # 5 minutes
            exclude=[ValueError],  # Don't trip on validation errors
            listeners=[OpenMeteoListener()]
        )

class OpenMeteoListener:
    def state_change(self, cb, old_state, new_state):
        if new_state == 'open':
            alert_ops(f"Open-Meteo circuit breaker OPEN (will retry in {cb.reset_timeout}s)")

# Usage
open_meteo_breaker = OpenMeteoBreaker()

@open_meteo_breaker
def fetch_forecast(lat, lon):
    return requests.get(FORECAST_URL, ..., timeout=30)
```

---

## 12. RISK MATRIX

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Open-Meteo API down | Medium | High | Circuit breaker + fallback |
| Stale data goes unnoticed | High | Medium | Data freshness gauge + alert |
| Model degrades silently | Medium | High | Drift detection + A/B testing |
| Feature store corruption | Low | Critical | Backup + redundancy |
| Render cold start (>30s) | Medium | Low | Pre-warming + caching |
| Test coverage gap in critical code | High | Medium | Increase coverage to 70% |
| Rate limit by Open-Meteo | Low | Medium | Exponential backoff + cache |

---

## 13. SUCCESS METRICS (Post-Improvements)

| Metric | Current | Target | Timeline |
|--------|---------|--------|----------|
| Test coverage | 10.5% | 70%+ | 2 weeks |
| P95 API latency | ~1s | <500ms | 1 week (caching) |
| MTTR (mean time to recovery) | Unknown | <30min | 1 week (runbooks) |
| Data freshness alerts | None | Real-time | 1 week |
| Model drift detection | Manual | Automated | 2 weeks |
| Observability (metrics exposed) | 0% | 95% | 2 weeks |

---

## Conclusion

AQI Predictor has a **solid foundation** with excellent model validation and clean architecture. However, it has **critical gaps in production readiness**: error handling, monitoring, and testing for failure modes.

**Recommended approach:** Address the 🔴 CRITICAL items (§10) in the next 2-3 weeks. These will make the system substantially more robust without requiring architectural changes.

The codebase is well-positioned for these improvements — the separation of concerns and solid documentation make it straightforward to add observability, error handling, and testing incrementally.

---

**Next Step:** Prioritize the top 5 items and assign owners for each.
