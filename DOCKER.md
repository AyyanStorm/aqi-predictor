# Docker Setup Guide

**Complete local development and deployment guide for AQI Predictor**

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Local Development](#local-development)
4. [Building Images](#building-images)
5. [Running Services](#running-services)
6. [Docker Compose](#docker-compose)
7. [Production Deployment](#production-deployment)
8. [Troubleshooting](#troubleshooting)
9. [Advanced Usage](#advanced-usage)

---

## 🚀 Quick Start

Get the full stack running in 3 commands:

```bash
# 1. Clone repository
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor

# 2. Build all images
docker-compose build

# 3. Start all services
docker-compose up
```

**Access:**
- 🌐 **API:** http://localhost:8000
- 📊 **Dashboard:** http://localhost:8501
- 📚 **API Docs:** http://localhost:8000/docs
- 📊 **Metrics:** http://localhost:8000/metrics

---

## ✅ Prerequisites

### Required
- **Docker** 20.10+ ([install](https://docs.docker.com/install/))
- **Docker Compose** 2.0+ ([install](https://docs.docker.com/compose/install/))
- **Git** (for cloning repository)
- **~4 GB disk space** (for images + data)

### Optional
- **Docker Desktop** (Windows/Mac)
- **VS Code + Docker extension**
- **Python 3.11** (if running tests locally without Docker)

### Verify Installation
```bash
docker --version          # Should be 20.10+
docker-compose --version  # Should be 2.0+
docker run hello-world    # Should succeed
```

---

## 💻 Local Development

### 1. Development Setup

Clone and setup:
```bash
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor

# Create .env file for local development
cp .env.example .env

# Edit .env with your settings
nano .env  # or use your editor
```

### 2. Environment Variables

**`.env` file** (local development):
```bash
# API Configuration
API_VERSION=1.0.0
ENVIRONMENT=development
SLOWAPI_ENABLED=true

# Logging
LOGLEVEL=DEBUG

# Optional: Sentry (error tracking)
# SENTRY_DSN=https://your-sentry-dsn@sentry.io/...

# Optional: Hopsworks (feature store)
# HOPSWORKS_API_KEY=your_api_key
# HOPSWORKS_PROJECT=your_project_name
```

### 3. Quick Commands

```bash
# Build images (first time)
docker-compose build

# Start services (background)
docker-compose up -d

# View logs (follow)
docker-compose logs -f

# Stop services
docker-compose down

# Rebuild single service
docker-compose build api

# Restart single service
docker-compose restart api
```

### 4. Interactive Shell

Access running container:
```bash
# Shell into API container
docker-compose exec api bash

# Inside container
cd /app
python -m src.training.model_registry list
python -c "from src.inference.predict import predict; print(predict(24.86, 67.01, '24h'))"

# Shell into Dashboard
docker-compose exec dashboard bash
```

---

## 🏗️ Building Images

### Build All Services

```bash
# Build all
docker-compose build

# Build with no cache (fresh)
docker-compose build --no-cache

# Build specific service
docker-compose build api
docker-compose build dashboard
```

### Build Single Service Manually

```bash
# Build API image
docker build -f Dockerfile.prod \
  -t aqi-api:latest \
  --build-arg PYTHONUNBUFFERED=1 .

# Build Dashboard
docker build -f Dockerfile.dashboard \
  -t aqi-dashboard:latest \
  --build-arg PYTHONUNBUFFERED=1 .
```

### View Images

```bash
# List all images
docker images | grep aqi

# Image details
docker inspect aqi-api:latest

# Show image layers
docker history aqi-api:latest
```

---

## 🚀 Running Services

### Option 1: Docker Compose (Recommended)

```bash
# Start all services
docker-compose up

# Start in background
docker-compose up -d

# Start specific service only
docker-compose up api

# View running containers
docker-compose ps

# Stop all
docker-compose down

# Stop and remove volumes (cleans database)
docker-compose down -v
```

### Option 2: Manual Docker Commands

#### Run API Only
```bash
docker run \
  -p 8000:8000 \
  -e ENVIRONMENT=development \
  --name aqi-api \
  aqi-api:latest
```

#### Run Dashboard Only
```bash
docker run \
  -p 8501:8501 \
  -e ENVIRONMENT=development \
  --name aqi-dashboard \
  aqi-dashboard:latest
```

### Option 3: With Environment File

```bash
# Run with .env file
docker run \
  -p 8000:8000 \
  --env-file .env \
  --name aqi-api \
  aqi-api:latest
```

---

## 🎼 Docker Compose

### Full Stack Configuration

**File:** `docker-compose.yml`

```yaml
version: '3.8'

services:
  # FastAPI Backend
  api:
    build:
      context: .
      dockerfile: Dockerfile.prod
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=development
      - LOGLEVEL=INFO
    volumes:
      - ./app:/app/app
      - ./src:/app/src
    command: uvicorn app.api:app --host 0.0.0.0 --port 8000 --reload

  # Streamlit Dashboard
  dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    ports:
      - "8501:8501"
    environment:
      - ENVIRONMENT=development
    volumes:
      - ./app:/app/app
      - ./src:/app/src
    depends_on:
      - api

networks:
  default:
    driver: bridge
```

### Common Tasks

#### Start Only API
```bash
docker-compose up api
```

#### Start API + Dashboard
```bash
docker-compose up
```

#### Scale Services (Dev)
```bash
# Start 2 API instances
docker-compose up -d --scale api=2
```

#### View Service Logs
```bash
# All logs
docker-compose logs

# Follow API logs
docker-compose logs -f api

# Last 100 lines
docker-compose logs --tail=100
```

#### Rebuild and Restart
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up
```

---

## 🌍 Production Deployment

### Option 1: Render.com (Current)

Automatically deploys from `Dockerfile.prod`:

```bash
# Push to main branch
git push origin main

# Render automatically:
# 1. Builds from Dockerfile.prod
# 2. Runs health checks
# 3. Deploys to production
# 4. Handles scaling & monitoring
```

**No Docker commands needed** - Render handles it!

### Option 2: Docker Hub

Push image to Docker Hub:

```bash
# Login
docker login

# Build and tag
docker build -f Dockerfile.prod -t yourusername/aqi-api:latest .

# Push
docker push yourusername/aqi-api:latest

# Pull & run anywhere
docker run -p 8000:8000 yourusername/aqi-api:latest
```

### Option 3: AWS ECR

Push to AWS Elastic Container Registry:

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 123456789.dkr.ecr.us-east-1.amazonaws.com

# Build and tag for ECR
docker build -f Dockerfile.prod \
  -t 123456789.dkr.ecr.us-east-1.amazonaws.com/aqi-api:latest .

# Push
docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/aqi-api:latest
```

### Option 4: Kubernetes

Deploy to Kubernetes cluster:

```bash
# Build image
docker build -f Dockerfile.prod -t aqi-api:latest .

# Tag for registry
docker tag aqi-api:latest your-registry/aqi-api:latest

# Push to registry
docker push your-registry/aqi-api:latest

# Create k8s manifests (example)
cat <<EOF > k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aqi-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: aqi-api
  template:
    metadata:
      labels:
        app: aqi-api
    spec:
      containers:
      - name: api
        image: your-registry/aqi-api:latest
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /readiness
            port: 8000
          initialDelaySeconds: 20
          periodSeconds: 5
EOF

# Deploy
kubectl apply -f k8s-deployment.yaml
```

---

## 🔧 Troubleshooting

### Common Issues

#### Port Already in Use
```bash
# Find what's using port 8000
lsof -i :8000

# Kill process (Linux/Mac)
kill -9 <PID>

# Or use different port
docker run -p 9000:8000 aqi-api:latest
```

#### Build Fails (Dependency Error)
```bash
# Build with no cache
docker-compose build --no-cache

# Increase Docker memory
# Docker Desktop → Preferences → Resources → Memory: 4GB+

# Clean up docker system
docker system prune -a
```

#### Container Keeps Crashing
```bash
# View logs
docker-compose logs api -f

# Check health
docker-compose ps

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up
```

#### HOPSWORKS_API_KEY Error
```bash
# Set env var
export HOPSWORKS_API_KEY=your_key

# Or add to .env
echo "HOPSWORKS_API_KEY=your_key" >> .env

# Restart
docker-compose down
docker-compose up
```

#### Can't Connect to API from Dashboard
```bash
# Check networks
docker network ls
docker network inspect aqi-predictor_default

# Ensure depends_on is set in docker-compose.yml
# Restart in correct order
docker-compose down
docker-compose up
```

### Debug Commands

```bash
# Get container ID
docker ps

# View full logs
docker logs <container_id>

# Inspect container
docker inspect <container_id>

# Execute command
docker exec <container_id> ps aux

# Check resource usage
docker stats

# View network
docker network inspect bridge
```

---

## 🎓 Advanced Usage

### Custom Builds

#### Build with Arguments
```bash
docker build -f Dockerfile.prod \
  --build-arg PYTHON_VERSION=3.11 \
  --build-arg PIP_CACHE_DIR=/cache \
  -t aqi-api:latest .
```

#### Multi-Stage Build Optimization
```bash
# Show layers
docker history aqi-api:latest

# Smaller image = less storage, faster pull
# Our multi-stage Dockerfile.prod does this automatically
```

### Docker Compose Overrides

**File:** `docker-compose.override.yml` (local overrides)

```yaml
version: '3.8'
services:
  api:
    environment:
      - LOGLEVEL=DEBUG
    ports:
      - "8000:8000"
    volumes:
      - ./app:/app/app  # Hot reload
      - ./src:/app/src
```

### Volume Management

```bash
# List volumes
docker volume ls

# Inspect volume
docker volume inspect aqi-predictor_data

# Remove unused volumes
docker volume prune

# Backup volume
docker run --rm -v aqi-predictor_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/data.tar.gz -C /data .

# Restore volume
docker run --rm -v aqi-predictor_data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/data.tar.gz -C /data
```

### Docker Networking

```bash
# Create custom network
docker network create aqi-network

# Connect container to network
docker network connect aqi-network <container_id>

# View network
docker network inspect aqi-network
```

### Performance Optimization

```bash
# BuildKit for faster builds
DOCKER_BUILDKIT=1 docker build -f Dockerfile.prod -t aqi-api:latest .

# Parallel builds
docker-compose build --parallel

# Use .dockerignore to exclude files
# Already configured in .dockerignore
```

### Health Checks

```bash
# Check health
docker-compose ps  # STATUS column shows "(healthy)"

# Manual health check
curl http://localhost:8000/health

# View health events
docker events --filter type=container
```

---

## 📦 Docker Images

### Image Information

**Dockerfile.prod** (Production API):
```
Base: python:3.11-slim
Size: ~200-300 MB (optimized)
Builder: Multi-stage (no build tools in final image)
User: Non-root (appuser, uid 1000)
Health Check: Every 30 seconds
```

**Dockerfile.dashboard** (Streamlit):
```
Base: python:3.11-slim
Size: ~300-400 MB
Optimized: Slim base image
Port: 8501
```

**Dockerfile.api** (Alternative):
```
Base: python:3.11-slim
Size: ~200-300 MB
Purpose: Standalone API
```

### Image Layers

```bash
# See layers
docker history aqi-api:latest

# Example output:
IMAGE          CREATED             CREATED BY                  SIZE
abc123         2 minutes ago       /bin/sh -c uvicorn...       0B
def456         5 minutes ago       /bin/sh -c useradd -m...    33kB
ghi789         10 minutes ago      COPY src/ ./src/            50MB
jkl012         15 minutes ago      COPY --from=builder...      120MB
```

---

## 🚀 Deployment Checklist

### Before Production Deployment

- [ ] All tests pass locally
- [ ] Docker image builds successfully
- [ ] No sensitive data in image
- [ ] Health checks configured
- [ ] Environment variables set
- [ ] Secrets in env vars (never in code)
- [ ] .dockerignore excludes unnecessary files
- [ ] Image size optimized (<500 MB)
- [ ] Multi-stage build used
- [ ] Non-root user configured

### Deployment Steps

```bash
# 1. Build locally and test
docker build -f Dockerfile.prod -t aqi-api:latest .
docker run -p 8000:8000 aqi-api:latest

# 2. Test health check
curl http://localhost:8000/health

# 3. Tag for registry
docker tag aqi-api:latest your-registry/aqi-api:v1.0.0

# 4. Push to registry
docker push your-registry/aqi-api:v1.0.0

# 5. Deploy to production
# (Render/Kubernetes/ECS/etc.)

# 6. Verify production health
curl https://production-api.example.com/health
```

---

## 📚 Resources

### Official Documentation
- [Docker Docs](https://docs.docker.com/)
- [Docker Compose Docs](https://docs.docker.com/compose/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Dockerfile Reference](https://docs.docker.com/engine/reference/builder/)

### Related Guides
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development setup
- [DEPLOYMENT_IMPROVEMENTS.md](DEPLOYMENT_IMPROVEMENTS.md) - Advanced deployment
- [README.md](README.md) - Project overview
- [render.yaml](render.yaml) - Render.com configuration

### Tools
- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- [Dive](https://github.com/wagoodman/dive) - Analyze layers
- [Trivy](https://github.com/aquasecurity/trivy) - Security scanning
- [Buildx](https://docs.docker.com/buildx/working-with-buildx/) - Multi-platform builds

---

## ✅ Quick Reference

### Essential Commands

```bash
# Build
docker build -f Dockerfile.prod -t aqi-api:latest .

# Run
docker run -p 8000:8000 aqi-api:latest

# Compose
docker-compose up
docker-compose down

# Logs
docker logs <container_id>
docker-compose logs -f

# Shell
docker exec -it <container_id> bash

# Health
curl http://localhost:8000/health

# Clean
docker system prune -a
```

---

## 📞 Support

### Common Questions

**Q: How do I run tests in Docker?**
```bash
docker-compose exec api pytest tests/
```

**Q: Can I edit code while Docker is running?**
```bash
# Yes! Volumes enable hot reload
# See docker-compose.yml volumes section
# Edit files locally, changes appear in container
```

**Q: How do I use production secrets?**
```bash
# Never hardcode secrets!
# Use environment variables:
export SENTRY_DSN=https://...
docker run -e SENTRY_DSN=$SENTRY_DSN aqi-api:latest

# Or .env file (add to .gitignore!)
```

**Q: Is the Docker setup production-ready?**
```bash
# Yes! Multi-stage build, health checks, non-root user
# Render.com uses Dockerfile.prod automatically
# Ready for Kubernetes, AWS, GCP, etc.
```

---

**Last Updated:** 2026-09-02  
**Status:** ✅ Complete and Production-Ready
