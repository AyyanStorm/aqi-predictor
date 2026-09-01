# Setup Guide — AQI Predictor

This guide walks you through setting up AQI Predictor for local development.

## Prerequisites

- **Python 3.10+** (check with `python --version`)
- **pip** (package manager, usually comes with Python)
- **git** (version control)
- **2GB RAM** and **500MB disk space** (minimum)
- **Docker 20.10+** (optional, for containerized setup)

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor
```

### 2. Create a Virtual Environment

Virtual environments isolate project dependencies from your system Python.

```bash
# Create virtual environment
python -m venv .venv

# Activate it
# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate
```

You should see `(.venv)` in your prompt when activated.

### 3. Install Core Dependencies

```bash
pip install -e .
```

This installs AQI Predictor in "editable" mode, making your code changes immediately effective.

### 4. Install Development Dependencies (Optional)

If you plan to contribute, install dev tools:

```bash
pip install -e ".[dev]"
```

This includes:
- **pytest** — testing framework
- **pytest-cov** — coverage reporting
- **black** — code formatter
- **ruff** — linter
- **mypy** — type checker

### 5. Configure Environment Variables

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
# Edit .env and add your Hopsworks credentials:
# HOPSWORKS_API_KEY=your_key_here
# HOPSWORKS_PROJECT=your_project_name
```

If you don't have Hopsworks yet, the API will still work locally with cached features.

### 6. (Optional) Configure Grafana

If running with Docker Compose, copy the Grafana config:

```bash
cp .env.grafana.example .env.grafana
```

For local setup, you can skip this (Grafana monitoring is optional).

---

## Running the Application

### Option A: Local Python Setup

#### Start the API Server

```bash
uvicorn app.api:app --reload
```

- Runs on `http://localhost:8000`
- `--reload` watches for code changes and restarts automatically
- API docs: `http://localhost:8000/docs` (interactive Swagger UI)

#### Start the Dashboard (in another terminal)

```bash
# Activate venv if needed
source .venv/bin/activate

streamlit run app/streamlit_app.py
```

- Runs on `http://localhost:8501`
- Shows interactive weather maps and AQI forecasts

### Option B: Docker Compose (Recommended)

```bash
docker compose up
```

This starts:
- **API:** http://localhost:8000
- **Dashboard:** http://localhost:8501
- **Prometheus:** http://localhost:9090 (metrics)
- **Grafana:** http://localhost:3000 (dashboards, admin/admin)

---

## Running Tests

### Run All Tests

```bash
# Disable rate limiting for test mode
SLOWAPI_ENABLED=false pytest tests/
```

**Expected:** ~442 tests passing

### Run Specific Tests

```bash
# Unit tests only
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v

# With coverage report
pytest tests/ --cov=src --cov=app --cov-report=html
```

Coverage report saved to `htmlcov/index.html`.

### Run a Single Test File

```bash
pytest tests/unit/test_api.py -v
```

### Run Tests Matching a Pattern

```bash
pytest tests/ -k "test_predict" -v
```

---

## Troubleshooting

### "Python 3.10+ not found"

Check your Python version:
```bash
python --version
```

Install from [python.org](https://www.python.org/downloads/) if needed.

### "No module named 'app'" or "No module named 'src'"

You skipped step 3 (installing with `pip install -e .`).

```bash
pip install -e .
```

### API not starting / "Address already in use"

Port 8000 is occupied. Use a different port:

```bash
uvicorn app.api:app --reload --port 8001
```

### Dashboard not loading data

1. Ensure the API is running on port 8000
2. Check `.env` has valid Hopsworks credentials (optional)
3. Restart the Streamlit app

### Tests failing with "Hopsworks connection error"

This is normal in test mode. Tests mock Hopsworks by default. If you see many failures:

```bash
# Ensure SLOWAPI_ENABLED is false
SLOWAPI_ENABLED=false pytest tests/ -v
```

### Virtual environment not activating

On Linux/macOS, ensure you're using `source`:
```bash
source .venv/bin/activate  # Correct
.venv/bin/activate         # Wrong
```

On Windows, use:
```bash
.venv\Scripts\activate
```

### "pip install -e . failed"

Check your Python version (need 3.10+) and try:

```bash
pip install --upgrade pip
pip install -e .
```

---

## Development Workflow

### Making Code Changes

1. Activate your venv: `source .venv/bin/activate`
2. Edit files in `src/` or `app/`
3. If running with `--reload`, changes apply instantly
4. Run tests to verify: `SLOWAPI_ENABLED=false pytest tests/`

### Formatting & Linting

```bash
# Format with black
black src/ app/ tests/

# Lint with ruff
ruff check src/ app/ tests/

# Type check with mypy
mypy src/ app/
```

### Committing Changes

```bash
git add .
git commit -m "descriptive message"
git push origin your-branch
```

---

## Next Steps

- **Read the architecture:** See [ARCHITECTURE.md](ARCHITECTURE.md)
- **Deploy to production:** See [DEPLOYMENT.md](DEPLOYMENT.md)
- **View model health:** See [docs/FINAL_MODEL_HEALTH_REPORT.md](docs/FINAL_MODEL_HEALTH_REPORT.md)
- **Explore the API:** Visit http://localhost:8000/docs in your browser

---

## Support

- **Issues:** [GitHub Issues](https://github.com/AyyanStorm/aqi-predictor/issues)
- **Docs:** [README.md](README.md), [API docs](http://localhost:8000/docs)
- **Model details:** [FINAL_MODEL_HEALTH_REPORT.md](docs/FINAL_MODEL_HEALTH_REPORT.md)
