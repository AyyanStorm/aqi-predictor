# 🐳 Docker Setup & Deployment Guide

Complete guide for building, running, and deploying AQI Predictor in containers.

## Prerequisites

- Docker 20.10+ ([install](https://docs.docker.com/get-docker/))
- Docker Compose 2.0+ ([install](https://docs.docker.com/compose/install/))
- Python 3.12 (for local development)
- Git

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor
```

### 2. Environment Configuration

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Edit `.env` with your Hopsworks credentials:

```env
HOPSWORKS_API_KEY=your_api_key_here
HOPSWORKS_PROJECT=your_project_name
HOPSWORKS_HOST=eu-west.cloud.hopsworks.ai  # or your region
HOPSWORKS_PORT=443
```

**⚠️ Important:** Never commit `.env` — it's gitignored.

### 3. Build All Images

```bash
docker compose build
```

### 4. Start the Stack

```bash
docker compose up
```

This starts:
- **API**: http://localhost:8000
- **Dashboard**: http://localhost:8501

### 5. Verify Services

```bash
# API health check
curl http://localhost:8000/health

# Dashboard (opens in browser)
open http://localhost:8501

# API endpoints
curl http://localhost:8000/cities
curl "http://localhost:8000/predict?lat=24.8608&lon=67.0104&city=Karachi"
```

### 6. Stop Services

```bash
docker compose down

# Remove volumes (cleans data/ logs/ too)
docker compose down -v
```

---

## Building Individual Images

### Build API Only

```bash
docker build -f Dockerfile.api -t aqi-api:latest .
```

### Build Dashboard Only

```bash
docker build -f Dockerfile.dashboard -t aqi-dashboard:latest .
```

### Build Feature Pipeline Only

```bash
docker build -f Dockerfile.pipeline -t aqi-pipeline:latest .
```

---

## Running Containers Standalone

### Run API

```bash
docker run -p 8000:8000 \
  --env-file .env \
  --mount type=bind,source=$(pwd)/data,target=/app/data \
  aqi-api:latest
```

### Run Dashboard

```bash
docker run -p 8501:8501 \
  --env-file .env \
  --mount type=bind,source=$(pwd)/data,target=/app/data \
  aqi-dashboard:latest
```

### Run Feature Pipeline

```bash
docker run \
  --env-file .env \
  --mount type=bind,source=$(pwd)/data,target=/app/data \
  aqi-pipeline:latest
```

### Override Default Command

```bash
# Run training instead of ingest
docker run \
  --env-file .env \
  --mount type=bind,source=$(pwd)/data,target=/app/data \
  aqi-pipeline:latest \
  python -m src.training.train --model lgbm --register
```

---

## Docker Compose Services Reference

### Configuration

```yaml
version: '3.9'

services:
  aqi-api:           # FastAPI service (port 8000)
  aqi-dashboard:     # Streamlit dashboard (port 8501)

networks:
  aqi-network:       # Internal bridge network

volumes:
  aqi-data:          # Model artifacts & cache
  aqi-logs:          # Application logs
```

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `HOPSWORKS_API_KEY` | ✅ | — | Feature store authentication |
| `HOPSWORKS_PROJECT` | ✅ | — | Feature store project name |
| `HOPSWORKS_HOST` | — | `eu-west.cloud.hopsworks.ai` | Hopsworks region endpoint |
| `HOPSWORKS_PORT` | — | `443` | Hopsworks port |
| `STREAMLIT_SERVER_HEADLESS` | — | `true` | Run Streamlit in headless mode |
| `STREAMLIT_SERVER_ENABLECORS` | — | `false` | Disable CORS for containers |

### Volumes

| Mount | Type | Purpose |
|-------|------|---------|
| `/app/data` | Bind | Model artifacts, feature store cache |
| `/app/logs` | Bind | Application logs, predictions tracking |
| `/.streamlit` | Bind | Streamlit configuration (optional) |

### Health Checks

Both services have health checks configured:

```bash
# Check API health manually
docker exec aqi-api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Check Dashboard health manually
docker exec aqi-dashboard python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501')"
```

View health status:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

---

## Docker Ignore Rules

The `.dockerignore` file excludes unnecessary files from the build context:

```
# Excluded:
- .git, .github (version control)
- .venv* (local virtual environments)
- __pycache__, *.pyc (Python cache)
- .pytest_cache, .coverage (test artifacts)
- .cache*, *.sqlite (local caches)
- .streamlit/secrets.toml (secrets)
- logs/ (generated logs)
- notebooks/ (dev notebooks)
- .env (local configuration)
```

Reduces build context size & speeds up builds.

---

## Development Workflow

### Local Iteration

```bash
# 1. Start stack in background
docker compose up -d

# 2. Edit code locally
vim app/api.py

# 3. Rebuild only the changed service
docker compose build aqi-api

# 4. Restart service
docker compose up -d aqi-api

# 5. View logs
docker compose logs -f aqi-api
```

### Viewing Logs

```bash
# All services
docker compose logs

# Specific service
docker compose logs aqi-api
docker compose logs aqi-dashboard

# Follow in real-time
docker compose logs -f

# Last 50 lines
docker compose logs --tail=50
```

### Interactive Shell

```bash
# Enter API container
docker exec -it aqi-api /bin/bash

# Enter Dashboard container
docker exec -it aqi-dashboard /bin/bash

# Run Python REPL in API
docker exec -it aqi-api python
```

### Running Tests in Container

```bash
# Run tests (assumes pytest is in requirements.txt)
docker compose run --rm aqi-api pytest tests/ -q

# Run with coverage
docker compose run --rm aqi-api pytest tests/ --cov=src
```

---

## Production Deployment

### Push to Docker Registry

```bash
# Login to Docker Hub
docker login

# Tag images
docker tag aqi-api:latest yourusername/aqi-api:latest
docker tag aqi-dashboard:latest yourusername/aqi-dashboard:latest

# Push
docker push yourusername/aqi-api:latest
docker push yourusername/aqi-dashboard:latest
```

### Deploy with Docker Swarm

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml aqi
```

### Deploy with Kubernetes

Convert Compose to Kubernetes:

```bash
# Install kompose
curl -L https://github.com/kubernetes/kompose/releases/download/v1.28.0/kompose-linux-amd64 -o kompose
chmod +x kompose

# Convert
./kompose convert -f docker-compose.yml -o k8s/
```

### Deploy to Render

Render natively supports Docker Compose blueprints. Create `render-docker.yaml`:

```yaml
services:
  - type: web
    name: aqi-api
    dockerfilePath: ./Dockerfile.api
    envVars:
      - key: HOPSWORKS_API_KEY
        sync: false

  - type: web
    name: aqi-dashboard
    dockerfilePath: ./Dockerfile.dashboard
    envVars:
      - key: HOPSWORKS_API_KEY
        sync: false
```

Push & connect to Render as a Blueprint.

---

## Troubleshooting

### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill process
kill -9 <PID>

# Or use different port in compose
# Change ports: "9000:8000" in docker-compose.yml
```

### Service Won't Start

```bash
# Check logs
docker compose logs aqi-api

# Rebuild from scratch
docker compose build --no-cache aqi-api
docker compose up aqi-api
```

### Model Artifact Not Found

```bash
# Verify data volume is mounted
docker exec aqi-api ls -la /app/data/models/registry/

# If missing, copy from local
docker cp data/models/registry/lgbm_v12.pkl aqi-api:/app/data/models/registry/
```

### Hopsworks Connection Error

```bash
# Check credentials
docker exec aqi-api python -c "
import os
print(f'API Key: {os.getenv(\"HOPSWORKS_API_KEY\")[:10]}...')
print(f'Project: {os.getenv(\"HOPSWORKS_PROJECT\")}')
print(f'Host: {os.getenv(\"HOPSWORKS_HOST\")}')
"

# Test connection
docker exec aqi-api python -m src.data_ingestion.ingest --test
```

### Out of Disk Space

```bash
# Clean up unused images & containers
docker system prune

# More aggressive
docker system prune -a --volumes
```

---

## Performance Tuning

### Reduce Image Size

```dockerfile
# Use multi-stage builds
FROM python:3.12-slim as builder
RUN pip install -r requirements.txt

FROM python:3.12-slim
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
```

### Speed Up Builds

```bash
# Use BuildKit
DOCKER_BUILDKIT=1 docker build -f Dockerfile.api .

# Cache dependencies separately
docker build --target builder ...
```

### Memory & CPU Limits

```yaml
# docker-compose.yml
services:
  aqi-api:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G
```

---

## Security Best Practices

1. **Don't run as root**: Use `USER` in Dockerfile
2. **Scan for vulnerabilities**: `docker scan aqi-api:latest`
3. **Use secrets**: Never hardcode API keys
4. **Keep images updated**: Rebuild regularly
5. **Minimal base images**: Use `-slim` or `-alpine`
6. **No secrets in .env**: Load at runtime, never commit

Example hardened Dockerfile:

```dockerfile
FROM python:3.12-slim

RUN useradd -m -u 1000 appuser
WORKDIR /app
RUN chown -R appuser:appuser /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER appuser
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0"]
```

---

## Related

- [README.md](README.md) — Project overview
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — System design
- [Docker Compose Spec](https://docs.docker.com/compose/compose-file/)
- [Dockerfile Best Practices](https://docs.docker.com/develop/dev-best-practices/dockerfile_best-practices/)

---

## 📊 Monitoring Stack (Prometheus + Grafana)

Complete observability setup for monitoring AQI Predictor in production.

### Architecture

```
┌─────────────────────────────────────────────┐
│       AQI Predictor Services                │
│  ┌──────────────┐    ┌──────────────────┐  │
│  │  FastAPI API │    │  Streamlit App   │  │
│  │ :8000/metrics│    │ :8501/metrics    │  │
│  └──────┬───────┘    └────────┬─────────┘  │
│         │                     │             │
└─────────┼─────────────────────┼─────────────┘
          │ scrapes (30s)       │
          ▼                     ▼
      ┌────────────────────────────┐
      │   Prometheus              │
      │   :9090                   │
      │ (stores metrics 30 days)  │
      └────────────┬──────────────┘
                   │ queries
                   ▼
      ┌────────────────────────────┐
      │   Grafana                  │
      │   :3000                    │
      │  (visualizes metrics)      │
      │  [5 dashboards included]   │
      └────────────────────────────┘
```

### Quick Start with Monitoring

#### 1. Start Full Stack (API + Dashboard + Monitoring)

```bash
# Includes Prometheus, Grafana, API, Dashboard
docker compose up

# Or start in background
docker compose up -d
```

This starts all services:
- **API**: http://localhost:8000 (metrics: /metrics)
- **Dashboard**: http://localhost:8501 (metrics: /metrics)
- **Prometheus**: http://localhost:9090 (metric storage & querying)
- **Grafana**: http://localhost:3000 (dashboards & visualization)

#### 2. Access Monitoring Stack

**Prometheus:**
```bash
open http://localhost:9090
```
- View raw metrics: http://localhost:9090/metrics
- Query interface: http://localhost:9090/graph
- Targets status: http://localhost:9090/targets

**Grafana:**
```bash
open http://localhost:3000
```
- Login: `admin` / `admin` (change in .env.grafana)
- Pre-configured Prometheus datasource
- 5 pre-built dashboards included

#### 3. View Dashboards

Available dashboards (auto-provisioned):

| Dashboard | Purpose | Metrics |
|-----------|---------|---------|
| **Health Overview** | System status snapshot | Latency, RMSE, Data age, Error rate |
| **API Metrics** | API performance & reliability | Request rate, latency, error codes |
| **Model Metrics** | ML model health | RMSE, accuracy, age, drift detection |
| **Data Metrics** | Data pipeline status | Freshness, quality, row counts |
| **Training Metrics** | Training job history | Duration, success rate, versions |

### Configuration

#### Prometheus Configuration

Prometheus is configured in `prometheus.yml`:

```yaml
global:
  scrape_interval: 30s      # Scrape every 30 seconds
  evaluation_interval: 30s  # Evaluate alerts every 30 seconds

scrape_configs:
  - job_name: 'aqi-api'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    
  - job_name: 'aqi-dashboard'
    static_configs:
      - targets: ['localhost:8501']
    metrics_path: '/metrics'
```

**To modify scrape intervals:**

Edit `prometheus.yml`:
```yaml
global:
  scrape_interval: 15s      # Change to 15s for more frequent scraping
  evaluation_interval: 15s
```

Then restart Prometheus:
```bash
docker compose restart prometheus
```

#### Grafana Configuration

Configure in `.env.grafana`:

```env
# Admin credentials
GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD=admin      # CHANGE IN PRODUCTION!

# Server
GF_SERVER_ROOT_URL=http://localhost:3000
GF_SERVER_DOMAIN=localhost

# Optional: Enable OAuth
# GF_AUTH_GENERIC_OAUTH_ENABLED=true
# GF_AUTH_GENERIC_OAUTH_CLIENT_ID=your_client_id
```

**To apply changes:**
```bash
docker compose down grafana
docker compose up -d grafana
```

### Metrics Exposed by AQI Predictor

#### API Metrics (from FastAPI /metrics endpoint)

```
# Prediction performance
aqi_prediction_latency_seconds       # P50, P95, P99 latencies
aqi_api_requests_total              # Total requests by endpoint/status

# Cache performance
aqi_cache_hits_total                # Cache hits
aqi_cache_misses_total              # Cache misses
aqi_cache_hit_ratio                 # Hit rate %

# System health
aqi_api_requests_in_progress        # Current concurrent requests
aqi_http_request_duration_seconds   # Request duration histogram
```

#### Model Metrics (from prediction service)

```
aqi_model_rmse_production           # Production model RMSE
aqi_model_rmse_candidate            # Candidate model RMSE
aqi_model_accuracy_production       # Production accuracy %
aqi_model_accuracy_candidate        # Candidate accuracy %
aqi_model_age_days_production       # Days since model training
```

#### Data Metrics (from feature pipeline)

```
aqi_feature_store_age_hours         # Hours since last data update
aqi_feature_store_row_count         # Total rows in feature store
aqi_data_quality_null_percent       # Null percentage in data
aqi_data_quality_validation_checks_total  # Quality checks by type
```

#### Training Metrics (from training pipeline)

```
aqi_training_last_run_age_days      # Days since last training
aqi_training_last_run_success       # Last training success (1=yes, 0=no)
aqi_training_last_run_duration_minutes  # Last training duration
aqi_training_jobs_total             # Total training jobs by status
aqi_training_rmse_by_version        # RMSE per model version
```

### Health Checks

#### Check Prometheus Status

```bash
# Via curl
curl http://localhost:9090/-/healthy

# Via Docker
docker compose exec prometheus wget -q -O - http://localhost:9090/-/healthy
```

#### Check Grafana Status

```bash
# Via curl
curl http://localhost:3000/api/health

# Via Docker
docker compose exec grafana curl http://localhost:3000/api/health
```

#### Check Metric Scraping

```bash
# View Prometheus targets
curl http://localhost:9090/api/v1/targets

# Check if API is being scraped
curl "http://localhost:9090/api/v1/query?query=up{job=\"aqi-api\"}"

# Example response (1 = UP, 0 = DOWN)
# {"status":"success","data":{"resultType":"vector","result":[{"metric":{"job":"aqi-api"},"value":[timestamp,"1"]}]}}
```

### Querying Metrics

#### Via Prometheus UI

1. Go to http://localhost:9090
2. Click "Graph" tab
3. Enter query in expression field:

```promql
# Latest prediction latency (P95)
histogram_quantile(0.95, aqi_prediction_latency_seconds)

# API error rate (last 5 minutes)
rate(aqi_api_requests_total{status_code=~"5.."}[5m])

# Feature store age
aqi_feature_store_age_hours

# Model RMSE over time
aqi_model_rmse_production
```

#### Via curl

```bash
# Query current value
curl 'http://localhost:9090/api/v1/query?query=aqi_model_rmse_production'

# Query range (last 1 hour)
curl 'http://localhost:9090/api/v1/query_range?query=aqi_api_requests_total&start=1609459200&end=1609462800&step=300'
```

### Alerting (Optional)

Alert rules are defined in `prometheus-rules.yml`:

```yaml
groups:
  - name: aqi-alerts
    rules:
      # High error rate alert
      - alert: HighErrorRate
        expr: rate(aqi_api_requests_total{status_code=~"5.."}[5m]) > 0.05
        for: 5m
        
      # Stale data alert
      - alert: StaleData
        expr: aqi_feature_store_age_hours > 24
        for: 30m
        
      # Model drift alert
      - alert: ModelDrift
        expr: aqi_model_rmse_production > 50
        for: 1h
```

To enable alerting, configure Alertmanager (optional - advanced setup).

### Data Retention

**Prometheus** retains metrics for **30 days** by default.

To change retention:

```bash
# In docker-compose.yml, modify Prometheus command:
command:
  - '--storage.tsdb.retention.time=60d'  # 60 days
```

**Grafana** data persists in Docker volume `grafana-data`.

### Persistence & Volumes

```bash
# View volumes
docker volume ls | grep aqi

# View volume contents
docker volume inspect aqi-predictor_prometheus-data
docker volume inspect aqi-predictor_grafana-data

# Backup Prometheus data
docker run --rm -v aqi-predictor_prometheus-data:/data \
  -v $(pwd)/backups:/backup \
  busybox tar czf /backup/prometheus-backup.tar.gz -C /data .

# Backup Grafana data
docker run --rm -v aqi-predictor_grafana-data:/data \
  -v $(pwd)/backups:/backup \
  busybox tar czf /backup/grafana-backup.tar.gz -C /data .
```

### Troubleshooting

#### Prometheus not scraping metrics

```bash
# Check if API is running
curl http://localhost:8000/health

# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# View Prometheus logs
docker compose logs prometheus | grep error
```

#### Grafana dashboards not loading

```bash
# Check datasource connection
curl http://localhost:3000/api/datasources

# Verify Prometheus is reachable from Grafana container
docker compose exec grafana curl http://prometheus:9090/-/healthy

# Check Grafana logs
docker compose logs grafana | grep error
```

#### High memory usage

Prometheus stores metrics in memory. To reduce:

```bash
# Reduce scrape frequency in prometheus.yml
scrape_interval: 60s  # Instead of 30s

# Reduce retention
command:
  - '--storage.tsdb.retention.time=7d'  # Instead of 30d

# Restart
docker compose restart prometheus
```

### Production Deployment

#### 1. Change Grafana Password

```bash
# In .env.grafana
GF_SECURITY_ADMIN_PASSWORD=your_secure_password_here
```

#### 2. Enable HTTPS (if behind reverse proxy)

```bash
# In .env.grafana
GF_SERVER_PROTOCOL=https
GF_SERVER_CERT_FILE=/etc/grafana/certs/cert.pem
GF_SERVER_CERT_KEY=/etc/grafana/certs/key.pem
```

#### 3. Configure Authentication

```bash
# OAuth example in .env.grafana
GF_AUTH_GENERIC_OAUTH_ENABLED=true
GF_AUTH_GENERIC_OAUTH_CLIENT_ID=your_client_id
GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET=your_client_secret
GF_AUTH_GENERIC_OAUTH_AUTH_URL=https://provider.com/oauth/authorize
GF_AUTH_GENERIC_OAUTH_TOKEN_URL=https://provider.com/oauth/token
GF_AUTH_GENERIC_OAUTH_API_URL=https://provider.com/oauth/userinfo
```

#### 4. Remote Storage (Enterprise)

For distributed setups, store Prometheus data remotely:

```yaml
# In prometheus.yml
remote_write:
  - url: "http://remote-prometheus:9090/api/v1/write"
    queue_config:
      capacity: 10000
      max_shards: 200
      min_shards: 1
```

#### 5. Resource Limits (Production)

```yaml
# In docker-compose.yml
prometheus:
  deploy:
    resources:
      limits:
        cpus: '1'
        memory: 2G
      reservations:
        cpus: '0.5'
        memory: 1G

grafana:
  deploy:
    resources:
      limits:
        cpus: '0.5'
        memory: 512M
      reservations:
        cpus: '0.25'
        memory: 256M
```

### Dashboard Customization

#### Add Custom Dashboard

1. In Grafana UI: Create > Dashboard
2. Add panels with Prometheus queries
3. Save to `grafana/provisioning/dashboards/`
4. Restart Grafana:

```bash
docker compose restart grafana
```

#### Export Existing Dashboard

```bash
# In Grafana UI:
# Dashboard > Settings > JSON Model > Copy
# Save to grafana/provisioning/dashboards/custom.json

# Restart Grafana to auto-load
docker compose restart grafana
```

### Metrics Export

#### Export metrics to CSV (for analysis)

```bash
# Via Prometheus HTTP API
curl 'http://localhost:9090/api/v1/query_range' \
  --data-urlencode 'query=aqi_api_requests_total' \
  --data-urlencode 'start=1609459200' \
  --data-urlencode 'end=1609545600' \
  --data-urlencode 'step=300' \
  > metrics.json

# Parse and convert to CSV (requires jq)
jq '.data.result[] | {metric: .metric, values: .values}' metrics.json > metrics.csv
```

### References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/grafana/latest/)
- [Prometheus Queries (PromQL)](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana Dashboard Development](https://grafana.com/docs/grafana/latest/dashboards/)

---

## Environment Variables Reference

### API Environment Variables

```env
HOPSWORKS_API_KEY=your_api_key
HOPSWORKS_PROJECT=your_project
HOPSWORKS_HOST=eu-west.cloud.hopsworks.ai
HOPSWORKS_PORT=443
```

### Dashboard Environment Variables

```env
STREAMLIT_SERVER_HEADLESS=true
STREAMLIT_SERVER_ENABLECORS=false
STREAMLIT_SERVER_PORT=8501
```

### Grafana Environment Variables (in .env.grafana)

```env
GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD=admin
GF_SERVER_ROOT_URL=http://localhost:3000
GF_INSTALL_PLUGINS=grafana-piechart-panel
```

### Prometheus Environment Variables

Configured via `prometheus.yml` (not env vars)
