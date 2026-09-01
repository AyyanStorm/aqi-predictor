# Deployment Guide — AQI Predictor

This guide covers deploying AQI Predictor to production on various platforms.

---

## Quick Start: Docker Compose (Local/Server)

### Prerequisites
- Docker 20.10+
- Docker Compose 1.29+
- 2GB RAM, 1GB disk space

### Deploy

```bash
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor
docker compose up -d
```

### Access
- **API:** http://localhost:8000
- **Swagger UI:** http://localhost:8000/docs
- **Dashboard:** http://localhost:8501
- **Prometheus:** http://localhost:9090
- **Grafana:** http://localhost:3000 (admin/admin)

### Environment Configuration

Create `.env` with your credentials:

```bash
cp .env.example .env
# Edit .env
export HOPSWORKS_API_KEY=your_key_here
export HOPSWORKS_PROJECT=your_project_name
```

Then start:
```bash
docker compose up -d
```

### View Logs

```bash
docker compose logs -f api
docker compose logs -f dashboard
```

### Stop

```bash
docker compose down
```

---

## Render Deployment

### Prerequisites
- Render account (free tier available)
- GitHub repository connected to Render

### Step 1: Create Web Service

1. Go to [render.com](https://render.com)
2. **New +** → **Web Service**
3. Select your GitHub repository
4. Configure:
   - **Name:** aqi-predictor-api
   - **Environment:** Docker
   - **Region:** Choose closest to your users
   - **Plan:** Free (or Starter for production)

### Step 2: Set Environment Variables

In Render dashboard, go to **Environment** and add:

```
HOPSWORKS_API_KEY=your_key_here
HOPSWORKS_PROJECT=your_project_name
HOPSWORKS_HOST=eu-west.cloud.hopsworks.ai
HOPSWORKS_PORT=443
LOG_FORMAT=json
SLOWAPI_ENABLED=true
RENDER_EXTERNAL_URL=https://your-service.onrender.com
```

### Step 3: Deploy

Click **Create Web Service**. Render builds and deploys automatically.

### Step 4: Add Dashboard (Optional)

Deploy dashboard as separate service:

1. **New +** → **Web Service**
2. Same repo, but configure:
   - **Name:** aqi-predictor-dashboard
   - **Build Command:** `pip install -e . && streamlit config set client.toolbarMode developer`
   - **Start Command:** `streamlit run app/streamlit_app.py --server.port 8501`
   - **Port:** 8501
   - Set same environment variables

### Monitoring Health

Render provides dashboards showing:
- Deployment status
- Log output
- CPU/memory usage
- Restart count

---

## Heroku Deployment (Legacy)

### Prerequisites
- Heroku CLI installed
- Free or Paid Heroku account
- Procfile and runtime.txt in repo

### Step 1: Prepare

Verify `Procfile` exists:

```bash
cat Procfile
# Should show:
# web: uvicorn app.api:app --host 0.0.0.0 --port $PORT
# worker: python src/training/pipeline.py
```

### Step 2: Deploy

```bash
heroku login
heroku create aqi-predictor
git push heroku main
```

### Step 3: Set Environment Variables

```bash
heroku config:set HOPSWORKS_API_KEY=your_key_here
heroku config:set HOPSWORKS_PROJECT=your_project_name
heroku config:set SLOWAPI_ENABLED=true
```

### Step 4: View Logs

```bash
heroku logs --tail
```

---

## AWS Deployment

### Option A: Elastic Container Service (ECS) + Fargate

#### Prerequisites
- AWS account
- AWS CLI configured
- Docker image pushed to ECR

#### Step 1: Create ECR Repository

```bash
aws ecr create-repository --repository-name aqi-predictor
```

#### Step 2: Build and Push Image

```bash
docker build -t aqi-predictor .
docker tag aqi-predictor:latest 123456789.dkr.ecr.us-east-1.amazonaws.com/aqi-predictor:latest
docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/aqi-predictor:latest
```

#### Step 3: Create ECS Task Definition

Create `task-definition.json`:

```json
{
  "family": "aqi-predictor",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "aqi-predictor",
      "image": "123456789.dkr.ecr.us-east-1.amazonaws.com/aqi-predictor:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "hostPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "HOPSWORKS_API_KEY",
          "value": "your_key_here"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/aqi-predictor",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

#### Step 4: Create ECS Service

```bash
aws ecs create-service \
  --cluster aqi-predictor-cluster \
  --service-name aqi-predictor-service \
  --task-definition aqi-predictor \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```

### Option B: EC2 + Docker

#### Prerequisites
- EC2 instance (t3.small or larger)
- Security group allowing ports 8000, 8501, 3000

#### Step 1: SSH into Instance

```bash
ssh -i your-key.pem ec2-user@your-instance.compute.amazonaws.com
```

#### Step 2: Install Docker

```bash
sudo yum update -y
sudo yum install docker -y
sudo systemctl start docker
sudo usermod -a -G docker ec2-user
```

#### Step 3: Deploy

```bash
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor
docker compose up -d
```

---

## Google Cloud Platform (GCP)

### Option A: Cloud Run

#### Prerequisites
- GCP account with billing enabled
- `gcloud` CLI installed

#### Step 1: Build and Push Image

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/aqi-predictor
```

#### Step 2: Deploy to Cloud Run

```bash
gcloud run deploy aqi-predictor \
  --image gcr.io/PROJECT_ID/aqi-predictor \
  --platform managed \
  --region us-central1 \
  --memory 1Gi \
  --set-env-vars HOPSWORKS_API_KEY=your_key_here,HOPSWORKS_PROJECT=your_project_name
```

#### Step 3: View URL

```bash
gcloud run services describe aqi-predictor --platform managed --region us-central1
```

### Option B: App Engine

#### Step 1: Create app.yaml

```yaml
runtime: python310

env: standard

entrypoint: gunicorn -w 4 -b 0.0.0.0:8080 app.api:app

env_variables:
  HOPSWORKS_API_KEY: "your_key_here"
  HOPSWORKS_PROJECT: "your_project_name"
```

#### Step 2: Deploy

```bash
gcloud app deploy
```

---

## Environment Configuration for Production

### Essential Variables

```env
# Hopsworks Feature Store
HOPSWORKS_API_KEY=your_api_key
HOPSWORKS_PROJECT=your_project_name
HOPSWORKS_HOST=eu-west.cloud.hopsworks.ai
HOPSWORKS_PORT=443

# API Configuration
SLOWAPI_ENABLED=true                    # Enable rate limiting
LOG_FORMAT=json                         # JSON logs for parsing
LOG_LEVEL=info                          # Set to 'warn' for less noise

# Optional: External URL (for Render)
RENDER_EXTERNAL_URL=https://your-domain.com
```

### Secrets Management Best Practices

**Never commit secrets.** Use your platform's secret management:

- **Docker:** Use `--secret` flag or environment files (not in Dockerfile)
- **Render:** Environment tab (encrypted at rest, rotated on deploy)
- **Heroku:** `heroku config:set` or use `Config Vars` dashboard
- **AWS:** Secrets Manager or Parameter Store
- **GCP:** Secret Manager

Example (Docker):
```bash
docker run -e HOPSWORKS_API_KEY="$(cat /run/secrets/hopsworks_key)" ...
```

---

## Monitoring Setup

### Prometheus + Grafana (Docker Compose)

Already included in `docker-compose.yml`:

```bash
docker compose up -d
# Access at http://localhost:3000 (admin/admin)
```

Metrics scraped from:
- **API:** http://localhost:8000/metrics
- **Node Exporter:** http://localhost:9100/metrics

### Grafana Dashboards

Pre-configured dashboards for:
- **API Performance:** requests/sec, latency, errors
- **Model Predictions:** forecast accuracy, processing time
- **System Health:** CPU, memory, disk usage

### Alert Configuration

In Grafana:
1. **Alerting** → **New Alert Rule**
2. Set thresholds (e.g., error rate > 5%, API latency > 2s)
3. Configure notification channels (email, Slack, PagerDuty)

---

## Health Checks & Uptime Monitoring

### Readiness Endpoint

The API exposes a health check:

```bash
curl http://localhost:8000/health
```

Response (200 OK):
```json
{
  "status": "ready",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Liveness Checks

Use this URL in your load balancer/orchestration:

- **Endpoint:** `/health`
- **Interval:** 30 seconds
- **Timeout:** 5 seconds
- **Healthy threshold:** 2 consecutive passes
- **Unhealthy threshold:** 3 consecutive failures

### Uptime Monitoring Services

- **Pingdom:** https://www.pingdom.com (free tier available)
- **Uptime Robot:** https://uptimerobot.com (free)
- **Better Stack:** https://betterstack.com

---

## Scaling Considerations

### Horizontal Scaling

For high traffic, run multiple API instances:

```bash
# Docker Compose: scale API service
docker compose up -d --scale api=3
```

This runs 3 instances behind a load balancer.

### Load Balancing

- **Cloud providers:** Use managed load balancers (AWS ELB, GCP Load Balancer)
- **Self-hosted:** Use NGINX or HAProxy
- **Docker:** Traefik or Docker Swarm

### Caching

The API caches predictions for 24 hours (configurable). This reduces:
- Database queries
- Model inference calls
- Latency for repeated requests

### Database/Feature Store

If using Hopsworks:
- Configure feature store batch size (default: 1000 rows)
- Enable online feature store for real-time lookups
- Monitor feature retrieval latency in Prometheus

---

## Backup & Disaster Recovery

### Backup Strategy

1. **Code:** GitHub (automatic)
2. **Models:** Hopsworks Model Registry (automatic)
3. **Data:** Feature Store backups (daily, configurable)
4. **Logs:** S3 or GCS (stream logs from Prometheus/Grafana)

### Recovery Plan

- **API down:** Traffic switches to standby instance (if deployed with load balancer)
- **Data corruption:** Restore from Feature Store backup
- **Model degradation:** Roll back to previous model version in Model Registry

---

## Production Checklist

- [ ] Environment variables configured (no secrets in code)
- [ ] HTTPS/TLS enabled (all platforms support)
- [ ] Rate limiting enabled (`SLOWAPI_ENABLED=true`)
- [ ] Health checks configured on load balancer
- [ ] Monitoring/alerting set up (Prometheus + Grafana)
- [ ] Logs aggregated and searchable
- [ ] Backups configured
- [ ] SSL certificate valid (non-self-signed)
- [ ] CORS configured appropriately
- [ ] API documentation accessible (`/docs`)
- [ ] Tests passing (`SLOWAPI_ENABLED=false pytest tests/`)
- [ ] Load tested (if expected to handle >100 req/sec)

---

## Support

- **Issues:** [GitHub Issues](https://github.com/AyyanStorm/aqi-predictor/issues)
- **Documentation:** [README.md](README.md), [SETUP.md](SETUP.md), [ARCHITECTURE.md](ARCHITECTURE.md)
- **API Docs:** http://your-domain/docs
- **Model Health:** [docs/FINAL_MODEL_HEALTH_REPORT.md](docs/FINAL_MODEL_HEALTH_REPORT.md)
