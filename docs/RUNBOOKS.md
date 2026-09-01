# Operational Runbooks

Complete incident response procedures for AQI Predictor production system. Each runbook provides diagnosis steps, recovery procedures, and escalation paths for common failure scenarios.

**Quick Links:**
- [Render Dashboard](https://dashboard.render.com)
- [GitHub Actions](https://github.com/AyyanStorm/aqi-predictor/actions)
- [Open-Meteo Status](https://status.open-meteo.com)
- [Prometheus Metrics](https://aqi-predictor.onrender.com/metrics)
- [Prediction Cache Status](https://aqi-predictor.onrender.com/health)

---

## Runbook 1: Feature Pipeline Failed

**Symptom:** GitHub Actions shows ❌ on `feature_pipeline` workflow  
**Impact:** Predictions use stale data (24h+ old), model not retraining  
**Severity:** 🔴 HIGH  
**Time to fix:** 5-30 minutes  
**MTTR:** < 30 minutes

### Quick Diagnosis

```bash
# 1. Check workflow status
gh run list --workflow feature_pipeline.yml --limit 5

# 2. Get most recent failed run
FAILED_RUN=$(gh run list --workflow feature_pipeline.yml --limit 1 --json databaseId | jq -r '.[0].databaseId')

# 3. View logs
gh run view $FAILED_RUN --log
```

### Error Type Analysis

| Error | Cause | Fix Time |
|-------|-------|----------|
| `HTTPError 429` | Rate limited by Open-Meteo | Wait 1-2h or use cache |
| `Timeout` | API slow/down | Retry in 5-10 min |
| `KeyError` | Missing data column | Check data schema |
| `ValidationError` | Data quality check failed | Investigate data quality |
| `MemoryError` | Out of memory | Check available disk/RAM |

### Diagnosis Steps

**For HTTP 429 (Rate Limited):**
```bash
# Check Open-Meteo status
curl -s https://status.open-meteo.com/api/v2/summary.json | jq '.components[] | select(.name | contains("API"))'

# View rate limit details in logs
gh run view $FAILED_RUN --log | grep -i "429\|rate"

# Wait for reset (usually 1 hour from first 429)
echo "Rate limit resets at: $(date -d '+1 hour')"
```

**For Timeout:**
```bash
# Check if Open-Meteo is responding
curl -I https://api.open-meteo.com/v1/forecast 2>&1 | head -5

# Check network connectivity
ping -c 1 api.open-meteo.com

# View timeout details
gh run view $FAILED_RUN --log | grep -i "timeout\|connection"
```

**For Data Quality Failure:**
```bash
# Run locally to diagnose
python3 << 'EOF'
from src.data_ingestion.validators import DataQualityValidator
from src.features.backends import get_feature_store_backend
import pandas as pd

# Load latest data
store = get_feature_store_backend()
df = store.read_features()

# Run validation
validator = DataQualityValidator(df)
passed, errors, warnings = validator.run_all()

print("Errors:", errors)
print("Warnings:", warnings)

# Check specific issues
if 'stale_data' in errors:
    print("Data is older than 24h - check ingestion pipeline")
if 'missing_cities' in errors:
    print("Missing cities - check data quality gates")
if 'nulls' in errors:
    print(f"High null rate - check source data quality")
EOF
```

### Recovery Steps

**Priority 1: Retry Pipeline**
```bash
# Go to Actions tab
# Click "feature_pipeline" workflow
# Click "Run workflow" (top right)
# Select branch: main
# Click "Run workflow"

# Wait 10-30 minutes for completion
# Check status: gh run list --workflow feature_pipeline.yml --limit 1
```

**Priority 2: Use Cached Features (if retry fails)**
```bash
# Check cache age
python3 << 'EOF'
from src.features.backends import get_feature_store_backend
import time
import os

store = get_feature_store_backend()
cache_file = ".feature_cache.json"

if os.path.exists(cache_file):
    mtime = os.path.getmtime(cache_file)
    age_hours = (time.time() - mtime) / 3600
    print(f"Cache age: {age_hours:.1f} hours")
    if age_hours < 24:
        print("✅ Cache still fresh, using cached features")
    else:
        print("⚠️ Cache stale (>24h), investigate pipeline")
else:
    print("❌ No cache found - pipeline may never have succeeded")
EOF
```

**Priority 3: Manual Data Ingestion**
```bash
# If automated pipeline fails repeatedly
python3 << 'EOF'
from src.data_ingestion.open_meteo_client import OpenMeteoClient
from src.data_ingestion.historical_backfill import backfill_city

client = OpenMeteoClient()

# Check which cities are failing
for city in ['Karachi', 'Lahore', 'Islamabad', 'Peshawar', 'Quetta']:
    try:
        data = client.fetch_city_data(city)
        print(f"✅ {city}: {len(data)} rows")
    except Exception as e:
        print(f"❌ {city}: {e}")

# If specific cities fail, manually backfill
# backfill_city(city='Karachi', start_date='2026-08-31', end_date='2026-09-01')
EOF
```

### Escalation

If issue persists > 1 hour:
1. Check Open-Meteo status page
2. Post to #ops Slack:
   ```
   📢 Feature Pipeline Alert
   - Status: FAILED (> 1 hour)
   - Error: [error type from logs]
   - Data age: [hours since last success]
   - Action: Attempted retry, waiting for Open-Meteo resolution
   - Runbook: docs/RUNBOOKS.md#feature-pipeline-failed
   ```
3. Consider temporary manual backfill

---

## Runbook 2: Training Pipeline Failed

**Symptom:** GitHub Actions shows ❌ on `training_pipeline` workflow  
**Impact:** Model not retraining (using stale model), accuracy degrading  
**Severity:** 🟡 MEDIUM  
**Time to fix:** 15-45 minutes  
**MTTR:** < 1 hour

### Quick Diagnosis

```bash
# Check training job status
gh run list --workflow training_pipeline.yml --limit 5

# View logs for latest failed run
FAILED=$(gh run list --workflow training_pipeline.yml --limit 1 --json databaseId | jq -r '.[0].databaseId')
gh run view $FAILED --log | tail -100
```

### Common Causes

| Error | Cause | Fix |
|-------|-------|-----|
| `InsufficientDataError` | < 30 days of data | Wait for backfill |
| `OOMError` | Out of memory | Reduce batch size |
| `ValidationError` | Training data quality | Check data validators |
| `ModelError` | LightGBM/Keras issue | Check feature compatibility |

### Diagnosis Steps

**Check Training Data Quality:**
```bash
python3 << 'EOF'
from src.features.backends import get_feature_store_backend
from src.data_ingestion.validators import DataQualityValidator

store = get_feature_store_backend()
df = store.read_features()

print(f"Total rows: {len(df)}")
print(f"Date range: {df['date'].min()} to {df['date'].max()}")
print(f"Cities: {df['city'].nunique()}")
print(f"Null %: {df.isnull().sum().sum() / df.size * 100:.1f}%")

# Validate
validator = DataQualityValidator(df)
passed, errors, warnings = validator.run_all()
print(f"Data quality: {'✅ PASS' if passed else '❌ FAIL'}")
if not passed:
    print(f"Errors: {errors}")
EOF
```

**Check Model Registry:**
```bash
# List all model versions
python3 -c "
from src.training.model_registry import ModelRegistry
registry = ModelRegistry()
print(registry.status('lgbm'))
"
```

**Check Training Logs:**
```bash
# View full training output
gh run view $FAILED --log | grep -E "Training|Epoch|Loss|Accuracy|Error"
```

### Recovery Steps

**Step 1: Validate Data Quality**
```bash
# Ensure data is fresh enough for training
python3 << 'EOF'
from src.features.backends import get_feature_store_backend
from datetime import datetime, timedelta

store = get_feature_store_backend()
df = store.read_features()

latest_date = df['date'].max()
data_age_days = (datetime.now() - latest_date).days

if data_age_days > 30:
    print("❌ Insufficient data (< 30 days) - wait for feature pipeline")
elif data_age_days > 7:
    print("⚠️ Limited data (7-30 days) - training may be suboptimal")
else:
    print(f"✅ Good data ({data_age_days} days recent)")
EOF
```

**Step 2: Retry Training**
```bash
# Method A: Retry via GitHub Actions
gh workflow run training_pipeline.yml

# Method B: Train locally (if urgent)
python3 << 'EOF'
from src.training.train import train_lightgbm_model
from src.training.model_registry import ModelRegistry

# Train new model
model = train_lightgbm_model()

# Register and test
registry = ModelRegistry()
version = registry.register_candidate_model(
    model=model,
    name='lgbm',
    rmse=model.test_rmse
)
print(f"✅ Registered version: {version}")

# Verify
print(registry.status('lgbm'))
EOF
```

**Step 3: Verify New Model**
```bash
# Check model drift after training
python3 << 'EOF'
from src.training.model_registry import ModelRegistry
from src.tracking.drift_detector import DriftDetector
from src.tracking.store import ParquetPredictionStore

registry = ModelRegistry()
store = ParquetPredictionStore()
detector = DriftDetector(store)

# Get new model version
status = registry.status('lgbm')
new_version = status['candidate_version']

# Check for drift
metrics = detector.detect_drift()
if metrics['rmse_drift']:
    print("⚠️ New model shows drift - investigate")
else:
    print("✅ New model healthy")
EOF
```

### Escalation

If training fails > 2 times:
1. Check feature pipeline (is it producing fresh data?)
2. Manually verify training data quality
3. Post to #ops:
   ```
   🚨 Training Pipeline Alert
   - Attempts: 2 failed
   - Latest error: [error message]
   - Data quality: [PASS/FAIL]
   - Last successful model: [version, date]
   - Action: [being taken]
   ```

---

## Runbook 3: Model Drift Detected

**Symptom:** GitHub issue created with ⚠️ "Model drift detected" or Prometheus alert  
**Impact:** Production model accuracy degrading, predictions less reliable  
**Severity:** 🟡 MEDIUM  
**Time to fix:** 30-60 minutes  
**MTTR:** < 2 hours

### Quick Diagnosis

```bash
# View drift report
python3 << 'EOF'
from src.tracking.store import ParquetPredictionStore
from src.tracking.drift_detector import DriftDetector

store = ParquetPredictionStore()
detector = DriftDetector(store)

# Get latest metrics
metrics = detector.detect_drift()
print(f"RMSE: {metrics.get('rmse', 'N/A')}")
print(f"MAE: {metrics.get('mae', 'N/A')}")
print(f"Accuracy: {metrics.get('accuracy', 'N/A')}%")
print(f"Drifted: {metrics.get('drifted', False)}")
EOF

# View drift report in GitHub issue
gh issue list --label "drift" --state open
```

### Drift Analysis Decision Tree

```
┌─ Is drift real?
│  ├─ YES (> 2 stdev from baseline)
│  │  └─→ Compare versions (Step 1)
│  └─ NO (< 2 stdev, likely noise)
│     └─→ Monitor next 24h, no action needed
│
├─ Can rollback?
│  ├─ YES (previous version exists)
│  │  └─→ Rollback procedure (Step 2)
│  └─ NO (only one version)
│     └─→ Retrain immediately (Step 3)
│
└─ Root cause?
   ├─ Data quality issue → Fix validators
   ├─ Distribution shift → Retrain
   └─ Open-Meteo change → Monitor & adjust
```

### Diagnosis Steps

**Step 1: Confirm Drift is Real**
```bash
python3 << 'EOF'
from src.tracking.store import ParquetPredictionStore
from src.tracking.drift_detector import DriftDetector
import numpy as np

store = ParquetPredictionStore()
detector = DriftDetector(store)

# Get 7-day trend
trend = detector.get_trend(window_days=7)

# Calculate variance
rmse_values = [m.get('rmse', 0) for m in trend]
rmse_mean = np.mean(rmse_values)
rmse_std = np.std(rmse_values)
latest_rmse = rmse_values[-1]

# Check if drift is significant (> 2 stdev)
zscore = (latest_rmse - rmse_mean) / rmse_std if rmse_std > 0 else 0

if abs(zscore) > 2:
    print(f"✅ REAL DRIFT DETECTED (z-score: {zscore:.2f})")
else:
    print(f"⚠️ Possible noise (z-score: {zscore:.2f})")

print(f"RMSE trend: {[f'{r:.2f}' for r in rmse_values[-7:]]}")
EOF
```

**Step 2: Compare Model Versions**
```bash
python3 << 'EOF'
from src.training.model_registry import ModelRegistry
from src.tracking.drift_detector import DriftDetector
from src.tracking.store import ParquetPredictionStore

registry = ModelRegistry()
store = ParquetPredictionStore()
detector = DriftDetector(store)

# Get current production model
status = registry.status('lgbm')
prod_version = status['production_version']
candidate_version = status.get('candidate_version')

print(f"Production: v{prod_version}")
print(f"Candidate: v{candidate_version}")

# Compare metrics
if candidate_version:
    metrics_prod = detector.compare_versions(v1=prod_version, v2=candidate_version)
    print(f"\nMetrics Comparison:")
    for metric, values in metrics_prod.items():
        print(f"  {metric}: {values}")
EOF
```

**Step 3: Analyze Root Cause**
```bash
python3 << 'EOF'
from src.features.backends import get_feature_store_backend
from src.tracking.store import ParquetPredictionStore
import pandas as pd

store = get_feature_store_backend()
pred_store = ParquetPredictionStore()

# Check feature quality
features = store.read_features()
print(f"Feature quality:")
print(f"  - Age: {(pd.Timestamp.now() - features['date'].max()).days} days")
print(f"  - Nulls: {features.isnull().sum().sum() / features.size * 100:.1f}%")
print(f"  - Cities: {features['city'].nunique()}")

# Check prediction quality
predictions = pred_store.load_all()
if len(predictions) > 0:
    print(f"\nPrediction quality:")
    print(f"  - Count: {len(predictions)}")
    print(f"  - Mean error: {predictions['error'].abs().mean():.2f}")
    print(f"  - Error range: [{predictions['error'].min():.2f}, {predictions['error'].max():.2f}]")
EOF
```

### Recovery Steps

**Option A: Rollback to Previous Version** (if drift is recent)
```bash
python3 << 'EOF'
from src.training.model_registry import ModelRegistry

registry = ModelRegistry()
status = registry.status('lgbm')

# Show history
versions = registry.list_versions('lgbm')
print("Model history (newest first):")
for v in versions[:5]:
    print(f"  v{v['version']}: {v['status']}, RMSE={v.get('rmse', 'N/A')}")

# Rollback to previous
previous_version = versions[1]['version']  # Second most recent
registry.rollback('lgbm', previous_version)

print(f"✅ Rolled back to v{previous_version}")
EOF
```

**Option B: Retrain Model** (if only one version exists)
```bash
# Trigger training pipeline
gh workflow run training_pipeline.yml

# Monitor progress
watch -n 30 "gh run list --workflow training_pipeline.yml --limit 1"

# After success, verify new model
python3 -c "
from src.training.model_registry import ModelRegistry
registry = ModelRegistry()
print(registry.status('lgbm'))
"
```

**Option C: Investigate & Monitor** (if drift is < 2 stdev)
```bash
# Set up 24h monitoring
python3 << 'EOF'
import json
from datetime import datetime
from src.tracking.drift_detector import DriftDetector
from src.tracking.store import ParquetPredictionStore

store = ParquetPredictionStore()
detector = DriftDetector(store)

# Create monitoring checkpoint
checkpoint = {
    'timestamp': datetime.now().isoformat(),
    'baseline_metrics': detector.detect_drift(),
    'alert_threshold': 2.0  # stdev
}

with open('.drift_checkpoint.json', 'w') as f:
    json.dump(checkpoint, f)

print("✅ Monitoring checkpoint created")
print("   Will alert if drift exceeds 2 stdev over next 24h")
EOF
```

### Escalation

If drift confirmed AND model not recovering:
```bash
# Post to #ops with detailed info
gh issue create \
  --title "🚨 MODEL DRIFT UNRESOLVED" \
  --body "
- Production model v[N] showing significant drift
- RMSE increased by X%
- Root cause: [DATA/TRAINING/DISTRIBUTION]
- Action taken: [ROLLBACK/RETRAIN/MONITORING]
- Need assistance: [YES/NO]
  " \
  --label "critical,drift"
```

---

## Runbook 4: API Error Rate High

**Symptom:** /health returns error rate > 5% OR Prometheus alert triggered  
**Impact:** Users getting 5xx responses, predictions unavailable  
**Severity:** 🔴 CRITICAL  
**Time to fix:** 5-15 minutes  
**MTTR:** < 15 minutes

### Quick Health Check (< 1 minute)

```bash
# 1. Check health endpoint
curl -s https://aqi-predictor.onrender.com/health | jq .

# 2. Check error rate
curl -s https://aqi-predictor.onrender.com/metrics | grep http_requests_total

# 3. Check system resources
# (on render server if SSH access available)
# df -h /data
# free -h
```

### Triage Decision Tree

```
┌─ Check Open-Meteo status
│  └─ DOWN? → Our circuit breaker active, degraded mode OK
│
├─ Check Render status
│  └─ DOWN? → No quick fix, wait for Render to recover
│
├─ Check disk/memory
│  ├─ > 90% full? → Clear cache (Step 1)
│  └─ Normal? → Continue...
│
└─ Check application logs
   ├─ Timeouts? → API slow, likely Open-Meteo (Step 2)
   ├─ 5xx errors? → App crash, restart (Step 3)
   └─ Other? → Investigate specific error
```

### Diagnosis Steps

**Check External Dependencies:**
```bash
# Open-Meteo status
curl -s https://status.open-meteo.com/api/v2/summary.json | \
  jq '.components[] | select(.name | contains("API")) | {name, status}'

# Render status (if available)
curl -s https://status.render.com/api/v2/summary.json | \
  jq '.components[0] | {name, status}'
```

**Check Application Logs:**
```bash
# Get Render logs (via web dashboard or CLI)
# Recent errors in logs
curl -s https://aqi-predictor.onrender.com/health | jq '.status, .errors'
```

**Check System Resources:**
```bash
# Check space/memory (if you have SSH)
# ssh user@host "df -h /data && free -h"

# Or check via prediction cache size
python3 << 'EOF'
import os
import subprocess

cache_file = ".prediction_cache.json"
if os.path.exists(cache_file):
    size_mb = os.path.getsize(cache_file) / 1024 / 1024
    print(f"Prediction cache: {size_mb:.1f} MB")
    if size_mb > 100:
        print("⚠️ Cache large, consider cleanup")

# Check available space
result = subprocess.run(['df', '/'], capture_output=True, text=True)
print(result.stdout)
EOF
```

### Recovery Steps

**Priority 1: Clear Cache (if disk > 90%)**
```bash
python3 << 'EOF'
import os
import glob

cache_patterns = [
    ".prediction_cache.json",
    ".forecast_cache/*",
    ".feature_cache/*"
]

freed_mb = 0
for pattern in cache_patterns:
    for file in glob.glob(pattern):
        size = os.path.getsize(file) / 1024 / 1024
        os.remove(file)
        freed_mb += size
        print(f"Deleted {file} ({size:.1f} MB)")

print(f"✅ Freed {freed_mb:.1f} MB")
EOF
```

**Priority 2: Restart Application**
```bash
# Via Render dashboard:
# 1. Go to https://dashboard.render.com
# 2. Select aqi-predictor service
# 3. Click "Restart" button
# 4. Wait 2-3 minutes

# OR via CLI:
# render app restart aqi-predictor
```

**Priority 3: Rollback Recent Changes**
```bash
# If error rate spiked after recent deployment
gh run list --limit 5 --json conclusion,commitMessageHeadline

# Find last successful deploy
LAST_GOOD=$(git log --oneline --grep="deploy" | head -1)
echo "Last known good: $LAST_GOOD"

# Rollback via Render:
# 1. Dashboard -> aqi-predictor
# 2. Deployments tab
# 3. Click on last successful deployment
# 4. Click "Redeploy"
```

**Priority 4: Scale Resources** (if memory constrained)
```bash
# Via Render dashboard:
# 1. Select service -> Settings
# 2. Increase "Plan" to next tier
# 3. Apply changes
# Note: This may restart the service
```

### Escalation

If error rate persists > 10 minutes:
```bash
# Post to #ops
echo "
🚨 CRITICAL: API Error Rate Alert
- Current error rate: [X%]
- Started: [time] UTC
- Users affected: [estimate]
- Circuit breaker: [ACTIVE/INACTIVE]
- Open-Meteo status: [UP/DOWN]
- Recent changes: [if any]
- Action taken: [RESTART/CLEAR_CACHE/SCALE]
- ETA to resolution: [estimate]

Runbook: docs/RUNBOOKS.md#api-error-rate-high
"
```

If external service down (Open-Meteo):
- Monitor their status page
- Post user update: "Predictions temporarily unavailable due to data source outage"
- No recovery action needed, our circuit breaker handles this

---

## Runbook 5: Data Staleness Alert

**Symptom:** Alert triggered "Latest data > 24h old" OR manual check shows stale data  
**Impact:** Model making predictions on old data, reduced accuracy  
**Severity:** 🟡 MEDIUM  
**Time to fix:** 5-15 minutes  
**MTTR:** < 30 minutes

### Quick Check

```bash
python3 << 'EOF'
from src.features.backends import get_feature_store_backend
from datetime import datetime, timedelta
import pandas as pd

store = get_feature_store_backend()
features = store.read_features()

latest_date = features['date'].max()
age = datetime.now() - latest_date
age_hours = age.total_seconds() / 3600

print(f"Latest data: {latest_date}")
print(f"Age: {age_hours:.1f} hours")

if age_hours > 24:
    print("🔴 DATA STALE - Feature pipeline may have failed")
elif age_hours > 12:
    print("🟡 DATA OLD - Check feature pipeline status")
else:
    print("✅ DATA FRESH - No action needed")
EOF
```

### Diagnosis Steps

**Step 1: Check Feature Pipeline Status**
```bash
# See if latest run succeeded
gh run list --workflow feature_pipeline.yml --limit 3 --json status,conclusion,createdAt

# If failed, view logs
LAST=$(gh run list --workflow feature_pipeline.yml --limit 1 --json databaseId | jq -r '.[0].databaseId')
gh run view $LAST --log | tail -50
```

**Step 2: Check Data Ingestion**
```bash
python3 << 'EOF'
from src.data_ingestion.open_meteo_client import OpenMeteoClient
from datetime import datetime, timedelta

client = OpenMeteoClient()

# Test Open-Meteo connectivity
cities = ['Karachi', 'Lahore', 'Islamabad']
for city in cities:
    try:
        data = client.fetch_city_data(city)
        latest = data['date'].max()
        age_hours = (datetime.now() - latest).total_seconds() / 3600
        print(f"{city}: {len(data)} rows, latest {age_hours:.1f}h old")
    except Exception as e:
        print(f"{city}: ERROR - {e}")
EOF
```

**Step 3: Check Open-Meteo Status**
```bash
# Is the API responding?
curl -s -w "Status: %{http_code}\n" https://api.open-meteo.com/v1/forecast

# Full health check
curl -s https://status.open-meteo.com/api/v2/summary.json | jq '.status'
```

### Recovery Steps

**Option A: Retry Feature Pipeline**
```bash
# Simplest fix - retry the pipeline
gh workflow run feature_pipeline.yml

# Monitor progress
watch -n 30 "gh run list --workflow feature_pipeline.yml --limit 1 --json status,conclusion"

# Verify success
python3 -c "
from src.features.backends import get_feature_store_backend
store = get_feature_store_backend()
features = store.read_features()
print(f'Latest data: {features[\"date\"].max()}')
"
```

**Option B: Manual Backfill**
```bash
python3 << 'EOF'
from src.data_ingestion.historical_backfill import backfill_city
from datetime import datetime, timedelta

# Backfill last 48 hours for all cities
cities = ['Karachi', 'Lahore', 'Islamabad', 'Peshawar', 'Quetta']
end_date = datetime.now()
start_date = end_date - timedelta(days=2)

for city in cities:
    try:
        print(f"Backfilling {city}...", end='')
        result = backfill_city(city, start_date, end_date)
        print(f" ✅ ({len(result)} rows)")
    except Exception as e:
        print(f" ❌ {e}")
EOF
```

**Option C: Use Cached Predictions (temporary)**
```bash
# If data is truly unavailable, fall back to cache
# (system does this automatically via circuit breaker)

# Check cache status
python3 << 'EOF'
from src.inference.cache import PredictionCache
import os

cache = PredictionCache()
cache_file = ".prediction_cache.json"

if os.path.exists(cache_file):
    size = os.path.getsize(cache_file) / 1024
    print(f"✅ Cache available: {size:.1f} KB")
    print("Using cached predictions until data pipeline recovers")
else:
    print("❌ No cache, predictions unavailable")
EOF
```

### Escalation

If data stale > 48 hours:
```bash
gh issue create \
  --title "🔴 DATA PIPELINE CRITICAL: No data for 48h" \
  --body "
- Latest data: [timestamp]
- Age: 48+ hours
- Feature pipeline status: [FAILED/SUCCESS]
- Open-Meteo status: [UP/DOWN]
- Last successful backfill: [time]

Action: Immediate investigation required
"
```

---

## Runbook 6: High Memory Usage

**Symptom:** Application slower than usual OR memory alert triggered  
**Impact:** Slow predictions, potential crashes  
**Severity:** 🟡 MEDIUM  
**Time to fix:** 5-10 minutes  
**MTTR:** < 10 minutes

### Quick Check

```bash
# Check system memory
free -h

# Check Python process
ps aux | grep python | grep -v grep

# Estimate cache size
du -sh .prediction_cache.json .feature_cache.json 2>/dev/null
```

### Diagnosis Steps

```bash
python3 << 'EOF'
import psutil
import os

# Get memory usage
process = psutil.Process(os.getpid())
memory = process.memory_info()

print(f"Process memory: {memory.rss / 1024 / 1024:.1f} MB")
print(f"System memory:")
print(f"  - Available: {psutil.virtual_memory().available / 1024 / 1024:.0f} MB")
print(f"  - Used: {psutil.virtual_memory().percent}%")

# Check what's using memory
for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
    if proc.info['memory_percent'] > 5:
        print(f"  - {proc.info['name']}: {proc.info['memory_percent']:.1f}%")
EOF
```

### Recovery Steps

**Step 1: Clear Prediction Cache**
```bash
rm -f .prediction_cache.json
python3 -c "
from src.inference.cache import PredictionCache
cache = PredictionCache()
cache.clear()
print('✅ Cache cleared')
"
```

**Step 2: Clear Feature Cache**
```bash
python3 << 'EOF'
import glob
import os

for file in glob.glob('.feature_cache/*'):
    os.remove(file)
    print(f'Deleted {file}')

print('✅ Feature cache cleared')
EOF
```

**Step 3: Optimize Cache Retention**
```bash
python3 << 'EOF'
from src.inference.cache import PredictionCache

# Reduce max cache entries
cache = PredictionCache(max_entries=100)  # Default 500

# Clear old entries
cache.cleanup()

print('✅ Cache optimized for lower memory')
EOF
```

**Step 4: Restart Application** (if memory still high)
```bash
# Via Render dashboard -> Restart button
# Or wait for next automatic deployment

# Monitor recovery
while true; do
    free -h | grep Mem
    sleep 30
done
```

---

## Runbook 7: Model Performance Degradation

**Symptom:** Model accuracy/RMSE showing gradual decline  
**Impact:** Predictions less reliable, trust eroding  
**Severity:** 🟡 MEDIUM  
**Time to fix:** 1-3 hours  
**MTTR:** < 3 hours

### Diagnosis Steps

```bash
python3 << 'EOF'
from src.tracking.drift_detector import DriftDetector
from src.tracking.store import ParquetPredictionStore
import pandas as pd

store = ParquetPredictionStore()
detector = DriftDetector(store)

# Get 30-day trend
trend = detector.get_trend(window_days=30)

# Analyze trend
metrics = ['rmse', 'mae', 'accuracy']
print("30-day performance trend:")
for metric in metrics:
    values = [t.get(metric) for t in trend if metric in t]
    if values:
        print(f"  {metric}: {values[0]:.2f} → {values[-1]:.2f}")
        
        # Check if degrading
        change_pct = (values[-1] - values[0]) / values[0] * 100
        if change_pct > 5:
            print(f"    ⚠️ Degraded {change_pct:.1f}%")
EOF
```

### Root Cause Analysis

**Check if issue is data-related:**
```bash
python3 << 'EOF'
from src.features.backends import get_feature_store_backend
from src.data_ingestion.validators import DataQualityValidator
import pandas as pd

store = get_feature_store_backend()
features = store.read_features()

# Validate data
validator = DataQualityValidator(features)
passed, errors, warnings = validator.run_all()

print(f"Data quality: {'✅ PASS' if passed else '❌ FAIL'}")
if not passed:
    print(f"Issues: {errors}")
    
# Check for distribution shift
print(f"\nFeature statistics:")
print(features.describe())
EOF
```

**Check if issue is model-related:**
```bash
python3 << 'EOF'
from src.training.model_registry import ModelRegistry

registry = ModelRegistry()
status = registry.status('lgbm')

print(f"Production model: v{status['production_version']}")
print(f"RMSE: {status.get('rmse', 'N/A')}")
print(f"Last trained: {status.get('trained_at', 'N/A')}")

# Check how old the model is
from datetime import datetime
model_age_days = (datetime.now() - status.get('trained_at')).days
if model_age_days > 30:
    print(f"⚠️ Model is {model_age_days} days old - likely needs retraining")
EOF
```

### Recovery Steps

**If data quality issue:**
```bash
# Fix data validators, increase data collection frequency
# See: Runbook 5 (Data Staleness)
```

**If model is stale (> 30 days):**
```bash
# Trigger immediate retraining
gh workflow run training_pipeline.yml

# Monitor
watch -n 60 "gh run list --workflow training_pipeline.yml --limit 1"

# Verify
python3 -c "
from src.training.model_registry import ModelRegistry
registry = ModelRegistry()
print(registry.status('lgbm'))
"
```

**If new model is worse:**
```bash
# Rollback to previous version
python3 << 'EOF'
from src.training.model_registry import ModelRegistry

registry = ModelRegistry()
versions = registry.list_versions('lgbm')
print(f"Current: v{registry.status('lgbm')['production_version']}")
print(f"Previous: v{versions[1]['version']}")

# Rollback
registry.rollback('lgbm', versions[1]['version'])
print("✅ Rolled back to previous version")
EOF
```

---

## Runbook 8: Render Service Unresponsive

**Symptom:** Application not responding to requests OR slow HTTP responses  
**Impact:** Users cannot access predictions  
**Severity:** 🔴 CRITICAL  
**Time to fix:** 5-15 minutes  
**MTTR:** < 15 minutes

### Quick Check

```bash
# Test connectivity
curl -I https://aqi-predictor.onrender.com/health

# Test response time
time curl https://aqi-predictor.onrender.com/health > /dev/null

# If > 30s or timeout, service is unresponsive
```

### Diagnosis

```bash
# Check Render dashboard status
# https://dashboard.render.com -> aqi-predictor

# Check recent deployments
# Dashboard -> Deployments tab

# Check logs
# Dashboard -> Logs tab -> View recent errors
```

### Recovery Steps

**Step 1: Restart Service**
```bash
# Via Render dashboard:
# 1. Select aqi-predictor service
# 2. Click "Restart" button (top right)
# 3. Wait 2-3 minutes for cold start

# Verify
curl -I https://aqi-predictor.onrender.com/health
```

**Step 2: Check Resource Limits**
```bash
# Dashboard -> Settings
# Check if:
# - Memory exhausted (> 90%)
# - Disk full (> 90%)
# - CPU constantly at 100%

# If resource constrained, upgrade plan
```

**Step 3: Redeploy**
```bash
# If restart doesn't work, redeploy
# Dashboard -> Deployments -> Last successful -> Redeploy

# Or trigger via GitHub
gh workflow run deploy.yml
```

**Step 4: Rollback** (if recent changes broke it)
```bash
# Find last stable deployment
gh run list --limit 10 | grep "SUCCESS"

# Redeploy that version via dashboard
```

---

## Quick Reference

### Health Checks (Run Daily)

```bash
#!/bin/bash
# save as: check_health.sh

echo "=== AQI Predictor Health Check ==="
date

echo -e "\n1. API Health:"
curl -s https://aqi-predictor.onrender.com/health | jq '.status'

echo -e "\n2. Data Freshness:"
python3 << 'EOF'
from src.features.backends import get_feature_store_backend
from datetime import datetime
store = get_feature_store_backend()
df = store.read_features()
age_hours = (datetime.now() - df['date'].max()).total_seconds() / 3600
print(f"Latest data: {age_hours:.1f} hours old")
EOF

echo -e "\n3. Model Status:"
python3 << 'EOF'
from src.training.model_registry import ModelRegistry
registry = ModelRegistry()
status = registry.status('lgbm')
print(f"Production: v{status['production_version']}")
print(f"RMSE: {status.get('rmse', 'N/A')}")
EOF

echo -e "\n✅ Health check complete"
```

### Common Commands

```bash
# View recent errors
gh run list --limit 5 | grep FAILURE

# Check specific workflow
gh run list --workflow feature_pipeline.yml --limit 3

# View logs
gh run view <run-id> --log

# Trigger workflow
gh workflow run <workflow-name>

# Check service logs (if SSH available)
# ssh render_server "tail -f /var/log/app.log"
```

### Escalation Contacts

| Issue | Contact | Method |
|-------|---------|--------|
| Critical downtime | @team | Slack #ops or phone |
| Data pipeline failure | @data-team | Slack #data-engineering |
| Model drift | @ml-team | Slack #ml-ops or GitHub issue |
| Render issues | Render support | https://status.render.com |
| Open-Meteo issues | Check status page | https://status.open-meteo.com |

---

## Document Updates

**Last Updated:** 2026-09-01  
**Reviewed By:** AQI Predictor Operations Team  
**Next Review:** 2026-10-01

When new failure modes occur:
1. Document the symptom and fix
2. Add new runbook section
3. Update date and review status
4. Notify team of addition
