# Docker Image Security Guide

## Overview

AQI Predictor implements security best practices in all Docker images, including non-root user execution, vulnerability scanning, and minimal base images.

## Security Principles

### 1. Non-Root User Execution

All Docker containers run as a non-root user (`appuser`, uid 1000) to limit the impact of container escapes or compromised applications.

**Benefits:**
- ✅ Prevents privilege escalation attacks
- ✅ Limits access to host filesystem
- ✅ Reduces blast radius of security incidents
- ✅ Complies with OWASP and CIS Docker Benchmarks

**Implementation:**
```dockerfile
# Create non-root user (uid 1000)
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Install dependencies as root
RUN pip install --no-cache-dir -r requirements.txt

# Switch to non-root user before CMD
USER appuser

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2. Minimal Base Images

All images use `python:3.12-slim` to minimize attack surface:

- **Size:** ~170 MB (vs ~900 MB for `python:3.12`)
- **Vulnerabilities:** Fewer packages = fewer vulnerabilities
- **Build time:** Faster builds and deployments
- **Security:** Regular updates from official Python images

### 3. Dependency Caching

Dependencies are installed separately from application code:

```dockerfile
# Copy only requirements first (cacheable)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code last (frequently changes)
COPY . .
```

**Benefits:**
- Docker layer caching speeds up builds
- Clean dependency installation
- `--no-cache-dir` reduces image size

### 4. Vulnerability Scanning

Automated scanning via [Trivy](https://aquasecurity.github.io/trivy/) detects vulnerabilities:

**Workflow:** `.github/workflows/docker-scan.yml`
- Scans on every Dockerfile change
- Reports CRITICAL and HIGH vulnerabilities
- Uploads results to GitHub Security tab
- Fails CI if HIGH/CRITICAL found

**Run locally:**
```bash
# Install Trivy
brew install aquasecurity/trivy/trivy

# Scan built image
trivy image aqi-api:latest

# Scan with CRITICAL/HIGH only
trivy image --severity CRITICAL,HIGH aqi-api:latest

# Generate SARIF report
trivy image --format sarif --output trivy-results.sarif aqi-api:latest
```

## Dockerfile Security Checklist

All AQI Predictor Dockerfiles implement:

- [x] Non-root user (uid 1000)
- [x] Minimal base image (python:3.12-slim)
- [x] Separate dependency installation
- [x] `--no-cache-dir` for pip
- [x] Health checks
- [x] Read-only root filesystem (optional, see below)
- [x] No secrets in images
- [x] Automated vulnerability scanning

### Dockerfiles in Scope

1. **Dockerfile.api** - FastAPI application server
2. **Dockerfile.dashboard** - Streamlit dashboard
3. **Dockerfile.pipeline** - Feature engineering & training pipeline

## Running Containers Securely

### With Non-Root User

```bash
# Verify container runs as appuser (uid 1000)
docker run --rm aqi-api:latest id
# Output: uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)
```

### Read-Only Root Filesystem (Optional)

For even stricter security, mount root filesystem as read-only:

```bash
docker run --read-only \
  --tmpfs /tmp \
  --tmpfs /app \
  aqi-api:latest
```

**Requires:**
- Writable `/tmp` for temporary files
- Writable `/app` for runtime data

### With Resource Limits

```bash
docker run \
  --memory 1g \
  --cpus 0.5 \
  --memory-swap 1g \
  aqi-api:latest
```

**Limits:**
- `--memory`: Max memory (1 GB)
- `--cpus`: Max CPU cores (0.5 = half core)
- `--memory-swap`: Total memory + swap

### Docker Compose Security

```yaml
services:
  aqi-api:
    image: aqi-api:latest
    
    # Run as non-root user
    user: "1000:1000"
    
    # Security options
    security_opt:
      - no-new-privileges:true
    
    # Capability restrictions
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # Required for port binding
    
    # Read-only root filesystem
    read_only: true
    tmpfs:
      - /tmp
      - /run
    
    # Resource limits
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 512M
```

## Vulnerability Scanning

### GitHub Security Tab

Scan results automatically appear in:
1. GitHub repo → Security tab
2. Code scanning alerts section
3. Pull request reviews (if PR-triggered)

### Local Scanning

```bash
# Scan built image
trivy image aqi-api:latest

# Scan with high/critical only
trivy image --severity HIGH,CRITICAL aqi-api:latest

# Scan with detailed output
trivy image --severity HIGH,CRITICAL \
  --format table \
  aqi-api:latest

# Scan and generate JSON report
trivy image --format json \
  --output trivy-report.json \
  aqi-api:latest

# Scan multiple images
trivy image aqi-api:latest aqi-dashboard:latest aqi-pipeline:latest
```

### Remediation Workflow

1. **Detect:** Trivy finds vulnerability in scan
2. **Report:** Results appear in GitHub Security
3. **Assess:** Determine if vulnerability affects AQI Predictor
4. **Remediate:** 
   - Update base image: `python:3.12-slim` → newer version
   - Update dependency: Pin specific version in requirements.txt
   - Workaround: If no fix available, document risk acceptance
5. **Verify:** Re-run scan to confirm fix
6. **Document:** Update CHANGELOG.md with security patch

### Common Vulnerability Types

| Type | Examples | Remediation |
|------|----------|-------------|
| **OS Package** | libssl, zlib, openssl | Update base image |
| **Python Dependency** | requests, cryptography, numpy | Update requirements.txt |
| **Known Exploits** | CVE-2024-XXXXX | Patch or upgrade |

## Secret Management

### Do NOT Include Secrets in Images

❌ **Bad:**
```dockerfile
ENV HOPSWORKS_API_KEY=secret123
RUN echo "API_KEY=${HOPSWORKS_API_KEY}" > /app/config.py
```

✅ **Good:**
```dockerfile
# Secrets passed at runtime
docker run -e HOPSWORKS_API_KEY=<secret> aqi-api:latest

# Or via environment file
docker run --env-file .env aqi-api:latest
```

### Secret Scanning

GitHub automatically scans for committed secrets:

```bash
# Run locally (requires gitleaks)
gitleaks detect --source . --verbose

# Check if secrets leaked
git log --all --pretty=fuller | grep -i "password\|api_key\|secret"
```

## Multi-Stage Builds (Optional Future Enhancement)

To further reduce image size and attack surface:

```dockerfile
# Stage 1: Builder
FROM python:3.12-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Copy only installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

COPY . .
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Benefits:**
- Final image size reduced by 50%+
- No build tools (gcc, pip cache) in final image
- Even smaller attack surface

## Registry & Image Signing (Enterprise)

For production deployments:

### Container Registry Security

```bash
# Push to private registry
docker tag aqi-api:latest myregistry.azurecr.io/aqi-api:latest
docker push myregistry.azurecr.io/aqi-api:latest

# Enable image scanning in registry
# (Azure Container Registry, ECR, GCR, etc.)
```

### Image Signing (Cosign)

```bash
# Install cosign
brew install sigstore/tap/cosign

# Sign image
cosign sign --key cosign.key myregistry.azurecr.io/aqi-api:latest

# Verify signature
cosign verify --key cosign.pub myregistry.azurecr.io/aqi-api:latest
```

## Compliance & Benchmarks

### CIS Docker Benchmark

Implements controls from [CIS Docker Benchmark v1.5.0](https://www.cisecurity.org/docker-benchmark):

- [x] 4.1 - Run as non-root
- [x] 4.4 - Sign and verify images
- [x] 4.11 - Use COPY instead of ADD
- [x] 4.12 - Configure health checks
- [x] 5.30 - Ensure container images are scanned for vulnerabilities

### OWASP Security

Aligns with [OWASP Container Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html):

- [x] Use non-root containers
- [x] Use minimal base images
- [x] Don't run privileged containers
- [x] Use read-only filesystems
- [x] Scan images for vulnerabilities
- [x] Don't store secrets in images

## Production Deployment

### Pre-Production Checklist

```bash
# 1. Run Trivy scan
trivy image --severity HIGH,CRITICAL aqi-api:latest

# 2. Run container as non-root
docker run --rm aqi-api:latest id
# Verify: uid=1000(appuser) gid=1000(appuser)

# 3. Run with security options
docker run --rm \
  --user 1000:1000 \
  --read-only \
  --cap-drop ALL \
  aqi-api:latest \
  id

# 4. Verify health check
docker run --rm -d aqi-api:latest
docker ps | grep aqi-api  # Check HEALTHCHECK status
docker logs <container-id> | grep -i health

# 5. Test with minimal permissions
docker run --rm \
  --user 1000:1000 \
  --cap-drop ALL \
  --cap-add NET_BIND_SERVICE \
  aqi-api:latest
```

### Kubernetes Deployment

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: aqi-api
spec:
  containers:
  - name: api
    image: aqi-api:latest
    
    # Run as non-root
    securityContext:
      runAsUser: 1000
      runAsNonRoot: true
      allowPrivilegeEscalation: false
      
      # Restrict capabilities
      capabilities:
        drop:
          - ALL
        add:
          - NET_BIND_SERVICE
      
      # Read-only root
      readOnlyRootFilesystem: true
    
    # Resource limits
    resources:
      limits:
        memory: "1Gi"
        cpu: "500m"
      requests:
        memory: "512Mi"
        cpu: "250m"
    
    # Volume mounts for writable directories
    volumeMounts:
    - name: tmp
      mountPath: /tmp
    - name: run
      mountPath: /run
  
  volumes:
  - name: tmp
    emptyDir: {}
  - name: run
    emptyDir: {}
```

## Security Incident Response

### If HIGH/CRITICAL Vulnerability Found

1. **Immediate:** Update base image or dependency
2. **Test:** Run Trivy scan to verify fix
3. **Build:** Rebuild container image
4. **Deploy:** Redeploy containers with new image
5. **Monitor:** Check logs for any issues
6. **Document:** Update CHANGELOG.md

### Timeline

- **CRITICAL:** Fix within 24-48 hours
- **HIGH:** Fix within 1 week
- **MEDIUM:** Fix within 1 month
- **LOW:** Fix during next scheduled release

## References

- [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
- [Trivy Documentation](https://aquasecurity.github.io/trivy/)
- [CIS Docker Benchmark](https://www.cisecurity.org/docker-benchmark)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)

## Testing Security Locally

```bash
# Test non-root execution
docker build -f Dockerfile.api -t aqi-api:test .
docker run --rm aqi-api:test id
# Expected: uid=1000(appuser)

# Test read-only filesystem
docker run --rm --read-only --tmpfs /tmp aqi-api:test ls /app

# Test security capabilities
docker run --rm --cap-drop=ALL aqi-api:test

# Comprehensive Trivy scan
trivy image --format table aqi-api:test

# Generate security report
trivy image --format json --output security-report.json aqi-api:test
```

---

**Last Updated:** 2026-09-01  
**Security Level:** 🟢 Compliant with OWASP & CIS benchmarks
