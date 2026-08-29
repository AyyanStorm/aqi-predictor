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
