# Architecture — AQI Predictor

This document explains the codebase structure, design patterns, and data flow of AQI Predictor.

---

## Project Structure

```
aqi-predictor/
├── app/                           # REST API and Dashboard
│   ├── api.py                     # FastAPI application
│   ├── streamlit_app.py           # Streamlit dashboard
│   ├── components/                # Reusable dashboard components
│   │   ├── metrics.py             # KPI cards, charts
│   │   ├── maps.py                # Geographic visualizations
│   │   └── filters.py             # Location/time selectors
│   ├── views/                     # Page-level Streamlit views
│   │   ├── forecast.py            # 72-hour forecast view
│   │   ├── analysis.py            # Historical trend analysis
│   │   └── model_health.py        # Model performance metrics
│   ├── schemas/                   # Pydantic request/response models
│   │   ├── prediction.py          # PredictionRequest, PredictionResponse
│   │   └── health.py              # HealthResponse
│   └── __pycache__/               # Python bytecode (gitignored)
│
├── src/                           # Core machine-learning pipeline
│   ├── data_ingestion/            # Fetch & process raw data
│   │   ├── fetcher.py             # Download from APIs
│   │   ├── validator.py           # Data quality checks
│   │   └── preprocessor.py        # Cleaning & aggregation
│   │
│   ├── features/                  # Feature engineering
│   │   ├── engineer.py            # Create lag, rolling stats
│   │   ├── store.py               # Push features to Hopsworks
│   │   └── retriever.py           # Fetch from Hopsworks
│   │
│   ├── training/                  # Model training
│   │   ├── pipeline.py            # End-to-end training flow
│   │   ├── splitter.py            # Train/val/test split
│   │   ├── models.py              # LightGBM model definitions
│   │   ├── hyperparameters.py     # Tuning experiments
│   │   └── evaluator.py           # Metrics computation
│   │
│   ├── inference/                 # Real-time predictions
│   │   ├── predictor.py           # Load model, generate forecasts
│   │   ├── postprocessor.py       # Clip, categorize AQI
│   │   └── cache.py               # Prediction caching
│   │
│   ├── tracking/                  # Experiment logging
│   │   ├── experiment.py          # Log runs to Hopsworks
│   │   └── logger.py              # Structured logging
│   │
│   └── utils/                     # Helpers
│       ├── config.py              # Environment variables
│       ├── logger.py              # Logging setup
│       └── constants.py           # Magic numbers, enums
│
├── tests/                         # Test suite (442 tests)
│   ├── unit/                      # Isolated component tests
│   │   ├── test_api.py            # API endpoint tests
│   │   ├── test_features.py       # Feature engineering tests
│   │   ├── test_inference.py      # Prediction logic tests
│   │   └── test_schemas.py        # Data validation tests
│   │
│   ├── integration/               # Cross-module tests
│   │   ├── test_pipeline.py       # Data → features → model
│   │   └── test_end_to_end.py     # Full flow tests
│   │
│   └── conftest.py                # Pytest fixtures & mocks
│
├── data/                          # Persistent storage (gitignored files stored here)
│   ├── raw/                       # Downloaded raw data
│   ├── processed/
│   │   ├── feature_store_parquet/ # Engineered features (Parquet format)
│   │   └── feature_store.parquet  # Merged feature set
│   │
│   ├── models/
│   │   ├── registry/              # Trained models (.joblib)
│   │   │   ├── lgbm_v12.joblib    # Production model
│   │   │   ├── lgbm_v11.joblib    # Previous version
│   │   │   └── ...
│   │   └── artifacts/             # Training checkpoints
│   │
│   └── tracking/                  # Experiment logs
│
├── scripts/                       # Utility scripts
│   ├── train.py                   # Run training pipeline
│   ├── ingest.py                  # Fetch data from APIs
│   ├── predict.py                 # CLI prediction tool
│   └── benchmark/                 # Performance benchmarking
│
├── docs/                          # Documentation
│   ├── FINAL_MODEL_HEALTH_REPORT.md
│   └── API_REFERENCE.md
│
├── grafana/                       # Grafana dashboards & provisioning
│   └── provisioning/              # Auto-configured dashboards
│
├── notebooks/                     # Jupyter notebooks (exploration)
│
├── docker-compose.yml             # Local/dev orchestration
├── Dockerfile                     # Container image
├── .dockerignore                  # Docker build exclusions
├── .gitignore                     # Git exclusions
├── .env.example                   # Environment template
├── .env.grafana.example           # Grafana config template
├── .editorconfig                  # Editor settings
│
├── pyproject.toml                 # Project metadata & dependencies
├── setup.py                       # Legacy setup script
├── requirements.txt               # Pinned dependencies
├── Procfile                       # Heroku deployment
├── runtime.txt                    # Python version (Heroku)
│
├── LICENSE                        # MIT license
├── README.md                      # Project overview
├── SETUP.md                       # Local development guide
├── DEPLOYMENT.md                  # Production deployment
├── ARCHITECTURE.md                # This file
└── .github/
    └── workflows/                 # CI/CD pipelines
        ├── test.yml               # Run tests on every push
        ├── train.yml              # Scheduled training
        └── docker-scan.yml        # Security scanning

```

---

## Data Flow

### 1. Data Ingestion → Feature Engineering → Model Training

```
┌─────────────────────────────────────────────────────────────┐
│ Raw Data Sources                                            │
│ ├─ OpenWeather API (weather, AQI)                           │
│ ├─ WAQI API (air quality stations)                          │
│ └─ Historical CSV files                                    │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
        ┌────────────────┐
        │ Data Ingestion │  (src/data_ingestion/)
        ├────────────────┤
        │ - Fetch APIs   │
        │ - Validate     │
        │ - Clean        │
        └────────┬───────┘
                 │
                 ▼
        ┌────────────────┐
        │   Features     │  (src/features/)
        ├────────────────┤
        │ - Lag features │
        │ - Rolling stats│
        │ - Timestamps   │
        └────────┬───────┘
                 │
                 ▼
        ┌────────────────┐
        │   Hopsworks    │  Feature Store
        │ Feature Store  │  (online/offline)
        └────────┬───────┘
                 │
                 ▼
        ┌────────────────┐
        │   Training     │  (src/training/)
        ├────────────────┤
        │ - Load features│
        │ - Train LightGBM
        │ - Evaluate     │
        │ - Register     │
        └────────┬───────┘
                 │
                 ▼
        ┌────────────────┐
        │  Model Store   │  data/models/registry/
        │  (Model Reg.)  │
        └────────────────┘
```

### 2. Prediction: API Request → Feature Retrieval → Inference → Response

```
┌──────────────────────────────────────────────┐
│ User Request (HTTP)                          │
│ GET /predict?lat=24.86&lon=67.01&city=Kara… │
└─────────┬────────────────────────────────────┘
          │
          ▼
  ┌───────────────────┐
  │  FastAPI Route    │  (app/api.py)
  │ /predict endpoint │
  └─────────┬─────────┘
            │
            ▼
  ┌───────────────────────────────┐
  │ Validation & Caching          │
  ├───────────────────────────────┤
  │ 1. Validate lat/lon           │
  │ 2. Check prediction cache     │
  │ 3. Return cached (if exists)  │
  └─────────┬─────────────────────┘
            │ (cache miss)
            ▼
  ┌───────────────────────────────┐
  │ Feature Retrieval             │
  ├───────────────────────────────┤
  │ 1. Query Hopsworks            │
  │    (online feature store)     │
  │ 2. Get historical features   │
  │    (lag, rolling stats)       │
  └─────────┬─────────────────────┘
            │
            ▼
  ┌───────────────────────────────┐
  │ Prediction                    │
  ├───────────────────────────────┤
  │ 1. Load model (lgbm_v12)      │
  │ 2. Generate 3 forecasts      │
  │    (24h, 48h, 72h ahead)     │
  │ 3. Post-process:             │
  │    - Clip to [0, 500]        │
  │    - Categorize              │
  │    - Health message          │
  └─────────┬─────────────────────┘
            │
            ▼
  ┌───────────────────────────────┐
  │ Cache & Response              │
  ├───────────────────────────────┤
  │ 1. Cache for 24h              │
  │ 2. Return JSON response       │
  │ 3. Log to Prometheus          │
  └─────────┬─────────────────────┘
            │
            ▼
  ┌──────────────────────────────┐
  │ HTTP Response (200 OK)        │
  │ {                             │
  │   "current": {...},           │
  │   "forecast": {               │
  │     "24": {...},              │
  │     "48": {...},              │
  │     "72": {...}               │
  │   }                           │
  │ }                             │
  └──────────────────────────────┘
```

### 3. Dashboard: User Interaction → API Calls → Visualization

```
┌──────────────────────────────┐
│  User Browser               │
│  (Streamlit Dashboard)      │
└──────────┬───────────────────┘
           │
           ▼
  ┌────────────────────┐
  │ Streamlit App      │  (app/streamlit_app.py)
  │ (app/views/*.py)   │
  ├────────────────────┤
  │ Views:             │
  │ - Forecast page    │
  │ - Analysis page    │
  │ - Model health     │
  └────────┬───────────┘
           │
           ▼
  ┌────────────────────────┐
  │ Sidebar Filters        │
  ├────────────────────────┤
  │ - Select city          │
  │ - Enter coordinates    │
  │ - Choose date range    │
  └────────┬───────────────┘
           │
           ▼
  ┌─────────────────────────────────┐
  │ API Calls                       │
  ├─────────────────────────────────┤
  │ GET /predict?lat=...&lon=...    │
  │ GET /forecast/historical?...    │
  └────────┬────────────────────────┘
           │
           ▼
  ┌──────────────────────────┐
  │ Components              │
  ├──────────────────────────┤
  │ - Metrics cards (KPIs)   │
  │ - Time series charts     │
  │ - Geographic maps        │
  │ - Forecast tables        │
  └──────────────────────────┘
```

---

## Key Design Patterns

### 1. **Feature Store Architecture**

- **Purpose:** Centralized, versioned feature management
- **Implementation:** Hopsworks
- **Offline Store:** Parquet files (training, historical analysis)
- **Online Store:** Real-time feature lookups during inference
- **Benefits:**
  - Avoid training/serving skew
  - Reuse features across models
  - Easy rollback to previous features

### 2. **Model Registry**

- **Purpose:** Version, track, and manage models
- **Implementation:** Hopsworks Model Registry (with local `.joblib` backup)
- **Versioning:** `lgbm_v12`, `lgbm_v11`, etc.
- **Metadata:** Training parameters, metrics, dataset version
- **Benefits:**
  - Reproducibility
  - A/B testing (quick rollback)
  - Audit trail

### 3. **Caching Layer**

- **Purpose:** Reduce latency and API calls for repeated requests
- **Implementation:** In-memory cache (`.prediction_cache.json`)
- **TTL:** 24 hours
- **Key:** `f"{lat}_{lon}_{date}"`
- **Benefits:**
  - Sub-50ms response for cached predictions
  - Reduced model inference load

### 4. **Separation of Concerns**

**API Layer** (`app/api.py`)
- HTTP routing, request/response handling
- Does NOT contain business logic

**Service Layer** (`src/inference/predictor.py`)
- Prediction logic, feature fetching, model loading
- Testable, reusable

**Data Layer** (`src/features/`, `src/data_ingestion/`)
- Raw data, feature engineering
- Pluggable (easy to swap Hopsworks for PostgreSQL, etc.)

### 5. **Dependency Injection**

- Models and feature stores are injected, not hardcoded
- Enables testing with mocks
- Example: `src/inference/predictor.py` accepts a `feature_store` parameter

### 6. **Schema Validation**

- **Tools:** Pydantic
- **Location:** `app/schemas/`
- **Purpose:** Type-safe request/response handling
- **Benefits:** Auto-generated API documentation, runtime validation

---

## Core Modules

### `app/` — REST API & Dashboard

**FastAPI Application** (`app/api.py`)
```python
# Key endpoints:
GET  /health              # Liveness check
GET  /predict             # Main inference endpoint
GET  /forecast/historical # Historical data
GET  /docs               # Interactive API documentation
GET  /metrics            # Prometheus metrics
```

**Streamlit Dashboard** (`app/streamlit_app.py`)
```
Main page (forecast.py)
├─ City selector + coordinates
├─ Current AQI display
├─ 72-hour forecast chart
└─ Health recommendations

Analysis tab (analysis.py)
├─ Historical trends
├─ Seasonal patterns
└─ Comparison charts

Model Health tab (model_health.py)
├─ Performance metrics
├─ Validation scores
└─ Feature importance
```

**Schemas** (`app/schemas/`)
```python
class PredictionRequest(BaseModel):
    lat: float  # Latitude
    lon: float  # Longitude
    city: str   # City name

class AQIForecast(BaseModel):
    aqi: float
    category: str  # "Good", "Moderate", etc.
    health_message: str

class PredictionResponse(BaseModel):
    current: AQIForecast
    forecast: Dict[int, AQIForecast]  # 24, 48, 72 hours
```

---

### `src/data_ingestion/` — Fetch & Clean Data

**Fetcher** (`fetcher.py`)
- Calls OpenWeather API, WAQI API
- Handles retries & rate limits
- Returns raw data as dictionaries

**Validator** (`validator.py`)
- Checks for nulls, duplicates, out-of-range values
- Logs data quality issues
- Raises exceptions on critical failures

**Preprocessor** (`preprocessor.py`)
- Fills missing values (forward-fill, interpolation)
- Resamples to consistent intervals (hourly)
- Aggregates city-level data from multiple stations

---

### `src/features/` — Feature Engineering

**Engineer** (`engineer.py`)
```python
# Key features:
- Lag features: [t-1, t-2, ..., t-24] hours
- Rolling statistics: mean/std over [3h, 6h, 24h] windows
- Time-based: hour of day, day of week, month
- Spatial: distance to coast, city size, elevation
```

**Store** (`store.py`)
- Pushes engineered features to Hopsworks Feature Store
- Versioning & timestamp management
- Offline store (for training) & online store (for inference)

**Retriever** (`retriever.py`)
- Fetches features for a given lat/lon and time
- Handles missing features gracefully
- Returns numpy arrays for model inference

---

### `src/training/` — Model Training

**Pipeline** (`pipeline.py`)
```python
def train():
    # 1. Fetch data from Hopsworks
    X_train, y_train = fetch_features()
    
    # 2. Train LightGBM model
    model = train_lgbm(X_train, y_train)
    
    # 3. Evaluate
    metrics = evaluate(model, X_val, y_val)
    
    # 4. Register in Model Registry
    register_model(model, metrics)
```

**Models** (`models.py`)
```python
def create_lgbm_model():
    return LGBMRegressor(
        num_leaves=31,
        max_depth=5,
        learning_rate=0.05,
        n_estimators=1000,
        objective='regression',
        metric='rmse'
    )
```

**Hyperparameters** (`hyperparameters.py`)
- Grid search / Bayesian optimization
- Logs all experiments to Hopsworks

**Evaluator** (`evaluator.py`)
```python
# Metrics:
- RMSE (root mean squared error)
- MAE (mean absolute error)
- R² (coefficient of determination)
- MAPE (mean absolute percentage error)
```

---

### `src/inference/` — Real-Time Predictions

**Predictor** (`predictor.py`)
```python
class Predictor:
    def __init__(self, model, feature_store):
        self.model = model
        self.feature_store = feature_store
    
    def predict(self, lat: float, lon: float) -> Dict:
        # 1. Retrieve features from store
        features = self.feature_store.get(lat, lon)
        
        # 2. Generate predictions for t+24, t+48, t+72
        forecasts = [
            self.model.predict(features[t:]) 
            for t in [24, 48, 72]
        ]
        
        # 3. Post-process
        return self.postprocess(forecasts)
```

**Postprocessor** (`postprocessor.py`)
```python
def postprocess(aqi_value: float) -> Dict:
    # Clip to valid range [0, 500]
    aqi = min(max(aqi_value, 0), 500)
    
    # Categorize
    if aqi <= 50:
        category = "Good"
    elif aqi <= 100:
        category = "Moderate"
    # ... etc
    
    # Health message
    health_msg = get_health_message(category)
    
    return {
        "aqi": aqi,
        "category": category,
        "health_message": health_msg
    }
```

**Cache** (`cache.py`)
- Persistent JSON file or Redis
- TTL: 24 hours
- Reduces repeated predictions

---

### `src/tracking/` — Experiment Logging

**Experiment** (`experiment.py`)
- Logs run metadata (model, features, params)
- Pushes to Hopsworks Experiment Tracker
- Integrates with Model Registry

**Logger** (`logger.py`)
- Structured JSON logging
- Log levels: DEBUG, INFO, WARNING, ERROR
- Exportable to CloudWatch, ELK, Datadog

---

## Dependencies & Integrations

### Core
- **FastAPI:** REST API framework
- **Pydantic:** Data validation
- **LightGBM:** ML model
- **scikit-learn:** Feature scaling, metrics

### Feature Store
- **Hopsworks:** Feature Store + Model Registry
- **Pandas:** Data manipulation
- **NumPy:** Numerical operations

### Dashboard
- **Streamlit:** Interactive web app
- **Plotly:** Interactive charts
- **Folium:** Geographic visualizations

### Monitoring
- **Prometheus:** Metrics scraping
- **Grafana:** Dashboard & alerting
- **python-json-logger:** Structured logging

### Testing
- **pytest:** Test framework
- **pytest-cov:** Coverage reporting
- **responses:** HTTP mocking

### Development
- **black:** Code formatting
- **ruff:** Linting
- **mypy:** Type checking
- **pre-commit:** Git hooks

---

## Deployment Architecture

### Local Development
```
Developer machine
├─ Python venv
├─ FastAPI (port 8000)
├─ Streamlit (port 8501)
└─ SQLite cache
```

### Docker Compose (Local/Server)
```
Server
├─ API container (FastAPI)
├─ Dashboard container (Streamlit)
├─ Prometheus container (metrics)
└─ Grafana container (dashboards)
```

### Production (Render/AWS/GCP)
```
Cloud Provider
├─ API service (auto-scaling)
├─ Dashboard service (optional)
├─ Monitoring (managed service)
├─ Load balancer
└─ CDN (optional)
```

---

## Testing Strategy

### Unit Tests (`tests/unit/`)
- Test individual functions in isolation
- Mock external dependencies (APIs, databases)
- Fast execution (<5 seconds)

### Integration Tests (`tests/integration/`)
- Test components together (feature eng. + model)
- May use real Hopsworks or mock
- Slower execution (30-60 seconds)

### Coverage
- Target: >80% of critical paths
- Excluded: Configuration, CLI-only code, notebooks
- Run: `pytest tests/ --cov=src --cov=app`

---

## Security Considerations

1. **Secrets Management**
   - Never commit `.env` files
   - Use environment variables only
   - Rotate API keys regularly

2. **API Security**
   - Rate limiting (SlowAPI)
   - HTTPS only in production
   - CORS configured
   - Input validation (Pydantic)

3. **Monitoring**
   - Log all predictions for audit
   - Alert on unusual patterns
   - Monitor for attacks (e.g., brute-force lat/lon)

4. **Container Security**
   - Non-root user in Dockerfile
   - Minimal base image (python:3.10-slim)
   - Regular vulnerability scanning (Trivy)

---

## Performance Characteristics

| Operation | Latency | Notes |
|-----------|---------|-------|
| Cache hit | <50ms | In-memory lookup |
| Feature retrieval | 100-300ms | Hopsworks online store |
| Model inference | 50-200ms | 3 predictions (24/48/72h) |
| Full prediction (miss) | 200-600ms | Retrieval + inference |
| Train full model | 2-5 hours | On CPU (GPU 10-20 min) |

---

## Future Improvements

1. **Multi-horizon output:** Currently single model for all horizons; consider separate models for 24h, 48h, 72h
2. **Uncertainty quantification:** Confidence intervals on forecasts
3. **Ensemble models:** Combine LightGBM with neural networks
4. **Auto-scaling:** Horizontal scaling based on demand
5. **Distributed training:** GPU-accelerated, multi-node training
6. **Online learning:** Continuous model updates with new data

---

## Related Documentation

- **SETUP.md** — Local development guide
- **DEPLOYMENT.md** — Production deployment
- **README.md** — Project overview
- **docs/FINAL_MODEL_HEALTH_REPORT.md** — Model performance details
