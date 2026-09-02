# 🌫️ AQI Predictor — Pakistan

**Multi-horizon air-quality forecasting for any city in Pakistan — REST API + interactive dashboard.**

Predict the Air Quality Index (AQI) **24, 48 and 72 hours ahead** for any location,
using a city-agnostic machine-learning model trained on 4 years of data from 10
Pakistani cities, an automated data/training pipeline, and a location-aware dashboard.

[![Tests](https://img.shields.io/badge/tests-449%2F449%20passing-brightgreen)](tests/)
[![Security](https://img.shields.io/badge/security-Trivy%20scanning-blue)](https://github.com/AyyanStorm/aqi-predictor/actions/workflows/docker-scan.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Model](https://img.shields.io/badge/production-lgbm_v12%20%7C%20RMSE%2017.6-blueviolet)](docs/FINAL_MODEL_HEALTH_REPORT.md)

---

## 🌐 Live Demo

**Try it now:** https://aqi-predictor-blii.onrender.com/

Full deployment on Render with API, dashboard, and all features running live.

---

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

```bash
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor
docker compose up
```

**Access:**
- **API Docs:** http://localhost:8000/docs (Swagger UI)
- **ReDoc:** http://localhost:8000/redoc
- **Dashboard:** http://localhost:8501
- **Prometheus:** http://localhost:9090
- **Grafana:** http://localhost:3000 (admin/admin)

### Option 2: Local Python

```bash
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor
pip install -e .
pytest tests/                          # Run tests (449 passing)
streamlit run app/streamlit_app.py    # Start dashboard
uvicorn app.api:app --reload          # Start API (in another terminal)
```

**Access:**
- **API:** http://localhost:8000
- **Dashboard:** http://localhost:8501

---

## 📦 Installation

### Core Installation
```bash
pip install -e .
```

### With Optional Dependencies
```bash
pip install -e ".[feature-store]"    # Hopsworks integration
pip install -e ".[training]"         # ML training tools
pip install -e ".[dev]"              # Development tools
pip install -e ".[test]"             # Testing frameworks
```

### Requirements
- Python 3.10+
- Docker 20.10+ (for containers)
- 2GB RAM, 500MB disk space

---

## 🌐 API Usage

### Get 3-Day AQI Forecast

**Request:**
```bash
curl "http://localhost:8000/predict?lat=24.86&lon=67.01&city=Karachi"
```

**Response (200 OK):**
```json
{
  "current": {
    "aqi": 68.5,
    "category": "Moderate",
    "health_message": "Members of sensitive groups may experience health effects."
  },
  "forecast": {
    "24": {
      "aqi": 72.0,
      "category": "Moderate",
      "health_message": "..."
    },
    "48": {
      "aqi": 58.5,
      "category": "Moderate",
      "health_message": "..."
    },
    "72": {
      "aqi": 51.2,
      "category": "Good",
      "health_message": "Air quality is satisfactory..."
    }
  },
  "model": {
    "name": "aqi-lgbm-v12",
    "version": 12,
    "rmse": 17.6,
    "accuracy": 87.2,
    "training_date": "2026-09-01T10:30:00Z"
  },
  "status": "ok",
  "request_id": "a1b2c3d4",
  "latency_ms": 45.2,
  "timestamp": "2026-09-01T07:30:00Z"
}
```

### Service Health Check
```bash
curl http://localhost:8000/health
# Returns: {"status": "ok", "model": {"name": "aqi-lgbm-v12", "version": 12}}
```

### Training Cities
```bash
curl http://localhost:8000/cities
# Returns: {"cities": {"Karachi": {"lat": 24.86, "lon": 67.01}, ...}}
```

### Interactive API Documentation
Visit **http://localhost:8000/docs** for Swagger UI with try-it-out buttons.

---

## ✨ Features

### 🎯 Predictions
- **3-day forecast** - Current AQI + 24h/48h/72h predictions
- **EPA categories** - Good, Moderate, Unhealthy for Sensitive Groups, Unhealthy, Very Unhealthy, Hazardous
- **Health guidance** - Category-specific health messages
- **Global coverage** - Works for any coordinates on Earth
- **Generalization** - Trained on 10 cities, proven to work on unseen cities

### 📊 Dashboard
- **Interactive maps** - Real-time AQI heat field + city markers
- **Multi-city comparison** - Side-by-side AQI and analytics
- **Accuracy tracking** - Prediction vs actual performance over time
- **Location detection** - Browser geolocation, IP-based fallback, manual search
- **5 responsive views** - Dashboard, Map, Analytics, Comparison, Tracking

### 🔍 API
- **REST endpoints** - `/predict`, `/health`, `/cities`, `/metrics`
- **OpenAPI docs** - Swagger UI + ReDoc auto-generated
- **Request tracing** - Unique request IDs for debugging
- **Rate limiting** - 30 req/min per IP
- **Degraded mode** - Cached predictions if API unavailable

### 📈 Monitoring
- **Prometheus metrics** - Prediction latency, request counts, model health
- **Grafana dashboards** - 5 pre-built dashboards
  - Health Overview
  - API Metrics
  - Model Metrics
  - Data Metrics
  - Training Metrics
- **Health checks** - Auto-recovery on service failure

### 🔐 Security
- **Non-root containers** - UID 1000 (OWASP/CIS compliant)
- **Vulnerability scanning** - Trivy CI on every Dockerfile push
- **Dependency pinning** - All packages pinned with `==`
- **Type safety** - MyPy type hints throughout
- **Linting** - Black, flake8, isort automation
- **Secret management** - Environment-based (no hardcoding)

### 📚 Documentation
- **API docs** - Swagger UI with examples and error codes
- **Runbooks** - 8 operational procedures for incident response
- **Security guide** - CIS Docker Benchmark + OWASP alignment
- **Contributing guide** - Developer setup, code style, testing
- **Architecture docs** - System design and data flow

---

## 🧪 Testing

Run all tests:
```bash
pytest tests/ -v                      # Verbose output
pytest tests/ --cov=src --cov=app    # With coverage report
pytest tests/ -m "not slow"           # Skip slow tests
```

**Test Coverage:**
- **Unit tests** (13 files) - Fast, isolated functionality
- **Integration tests** (7 files) - End-to-end workflows
- **449 total tests** - All passing ✅
- **>80% coverage** - Maintained

---

## 🏗️ Architecture

```
┌─────────────┐
│ Open-Meteo  │ ← Free weather + AQI APIs (no auth)
└──────┬──────┘
       │
   ┌───┴───┬──────────────┐
   │       │              │
   ▼       ▼              ▼
┌────────┐ ┌──────────┐  ┌────────┐
│ Feature│ │ Backfill │  │Forecast│
│Pipeline│ │(one-shot)│  │(hourly)│
└────┬───┘ └────┬─────┘  └────┬───┘
     │          │             │
     └──────┬───┴─────────────┘
            ▼
      ┌──────────────┐
      │Feature Store │  ← Parquet (10 cities × 4 years)
      │(352K rows)   │
      └──────┬───────┘
             │
             ▼
      ┌─────────────┐
      │ Training    │  ← Daily walk-forward CV
      │ Pipeline    │
      └──────┬──────┘
             │
             ▼
      ┌──────────────┐
      │Model Registry│  ← Auto-promote if beats production
      │(lgbm_v12)    │
      └──────┬───────┘
             │
     ┌───────┴────────┐
     ▼                ▼
  ┌─────┐          ┌────────┐
  │ API │          │Dashboard│  ← Streamlit
  │     │          │(5 views)│
  └─────┘          └────────┘
     │ :8000          │ :8501
     └────────┬───────┘
              ▼
         Users & Apps
```

**Data Flow:**
1. **Ingestion** (hourly) - Pull latest weather + AQI from Open-Meteo
2. **Feature Engineering** - Build lagged features, rolling stats, calendar features
3. **Training** (daily) - Walk-forward CV, auto-promote if beats production
4. **Inference** - Same feature builder → production model → forecast

---

## 📊 Model Performance

Production model: **lgbm_v12** (LightGBM)

### Holdout Set (60 days, 10 cities, 14,410 rows)

| Horizon | RMSE | MAE | R² | MAPE |
|---------|------|-----|-----|------|
| +24h    | 17.6 | 12.5 | 0.77 | 10.3% |
| +48h    | 22.1 | 16.0 | 0.64 | 13.1% |
| +72h    | 22.6 | 16.5 | 0.62 | 13.5% |

### Unseen City (Sialkot, 35,232 rows)

| Horizon | RMSE | MAE | R² |
|---------|------|-----|-----|
| +24h    | 17.4 | 13.5 | 0.82 |
| +48h    | 22.7 | 18.0 | 0.70 |
| +72h    | 23.7 | 18.9 | 0.68 |

**Conclusion:** Model generalizes to unseen cities (proven by Sialkot).

See [FINAL_MODEL_HEALTH_REPORT.md](docs/FINAL_MODEL_HEALTH_REPORT.md) for full analysis.

---

## 🎬 What It Does

### Dashboard Features
- **Location-aware** - Opens on your city via browser geolocation
- **3-day forecast** - Current + 24h/48h/72h with EPA labels
- **Explainable** - Natural-language explanations for predictions
- **Live leaderboard** - Top 10 most-polluted cities
- **Global AQI map** - Heat field + city markers
- **Accuracy tracking** - Prediction vs actual over time
- **City comparison** - Side-by-side analytics

### API Features
- **REST endpoints** - `/predict`, `/health`, `/cities`, `/metrics`
- **OpenAPI docs** - Swagger UI with interactive testing
- **Request tracing** - Debug with unique request IDs
- **Caching** - Graceful degradation when upstream fails
- **Rate limiting** - 30 requests/min per IP

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Developer setup, code style, testing |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting, compliance |
| [DOCKER.md](DOCKER.md) | Docker deployment, configuration |
| [docs/RUNBOOKS.md](docs/RUNBOOKS.md) | Incident response procedures |
| [docs/DOCKER-SECURITY.md](docs/DOCKER-SECURITY.md) | Security hardening |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design |
| [docs/FINAL_MODEL_HEALTH_REPORT.md](docs/FINAL_MODEL_HEALTH_REPORT.md) | Model performance analysis |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

---

## 🛠️ Built With

**Core:**
- Python 3.10+ · pandas · NumPy

**ML:**
- LightGBM · scikit-learn · Keras (baselines)

**API & Dashboard:**
- FastAPI · Streamlit · Plotly · Pydeck

**Data:**
- Parquet (feature store) · SQL (optional Hopsworks)

**Monitoring:**
- Prometheus · Grafana

**DevOps:**
- Docker · GitHub Actions · Render

**External:**
- Open-Meteo (free weather API)

---

## 📋 Project Status

**Release:** v0.1.0 (Beta) - September 1, 2026

**Readiness:** Production ✅
- 449 tests passing
- Security hardened (non-root, CIS/OWASP)
- Full documentation
- Monitoring & alerting
- Operational runbooks

**Coverage:**
- ✅ Integration tests (7 files)
- ✅ Unit tests (13 files)
- ✅ End-to-end workflows
- ✅ Security scanning (Trivy)
- ✅ Type checking (MyPy)

---

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development setup
- Code style (Black, type hints)
- Testing requirements
- PR process
- Issue templates

**Quick start for contributors:**
```bash
pip install -e ".[dev]"
pre-commit install
pytest tests/
```

---

## 🔒 Security

Found a vulnerability? Please report it confidentially to **ayyan.storm@github.com**.

See [SECURITY.md](SECURITY.md) for:
- Vulnerability reporting process
- Security features (non-root, Trivy, CIS compliance)
- Incident response SLA
- Deployment checklist

---

## 📄 License

MIT License - © 2026 Ayyan Amir

See [LICENSE](LICENSE) file for details.

---

## 🚀 Deployment

### Docker Compose (Local Development)
```bash
docker compose up
```

### Production (Render, Kubernetes, etc.)
See [DOCKER.md](DOCKER.md) for comprehensive deployment guide including:
- Environment configuration
- Health checks
- Scaling
- Monitoring setup
- Troubleshooting

---

## ❓ Questions?

- 📖 **API Docs:** http://localhost:8000/docs
- 🐛 **Report Issues:** [GitHub Issues](https://github.com/AyyanStorm/aqi-predictor/issues)
- 💬 **Discussions:** [GitHub Discussions](https://github.com/AyyanStorm/aqi-predictor/discussions)
- 🔐 **Security:** [Security Policy](SECURITY.md)
- 👥 **Contributing:** [Contributing Guide](CONTRIBUTING.md)

---

**Built with ❤️ for clean air in Pakistan**
