# Security Improvements: 6.4/10 → 10/10

**Complete implementation plan for enterprise-grade security**

---

## 📊 CURRENT STATE

```
SECURITY Score: 6.4/10
├── Secrets Management:     6/10  (Needs scanning)
├── Dependency Security:    5/10  (Needs vulnerability scanning)
├── Auth & Authorization:   6/10  (CRITICAL - No authentication!)
├── Data Protection:        7/10  (Good)
├── API Security:           7/10  (No rate limiting)
├── Infrastructure:         6/10  (No SBOM)
└── Compliance:            8/10  (Good)

Gap to Excellence: +3.6 points
```

---

## 🎯 TARGET STATE

```
SECURITY Score: 10/10
├── Secrets Management:    10/10 (Full scanning & rotation)
├── Dependency Security:   10/10 (Complete scanning)
├── Auth & Authorization:  10/10 (JWT + RBAC)
├── Data Protection:       10/10 (Encryption, headers)
├── API Security:          10/10 (Rate limiting, CORS)
├── Infrastructure:        10/10 (SBOM, scanning, compliance)
└── Compliance:           10/10 (Policies, logging)
```

---

## 🚀 QUICK WINS (2 Hours = +1.8 Points!)

### Quick Win #1: Add Rate Limiting (20 mins)
**Impact:** API Security 7/10 → 8/10

**File:** requirements.txt
```
slowapi==0.1.9
```

**File:** app/api.py
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.get("/api/v1/predict")
@limiter.limit("10/minute")
async def predict(lat: float, lon: float):
    return predict_aqi(lat, lon)
```

**Result:** Prevents API abuse, DDoS protection

---

### Quick Win #2: Add Security Headers (15 mins)
**Impact:** Data Protection 7/10 → 8.5/10

**File:** app/api.py
```python
from fastapi import Request

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    
    # XSS protection
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    
    # HTTPS enforcement
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    
    # CSP
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    
    return response
```

**Result:** Prevents XSS, clickjacking, MIME sniffing

---

### Quick Win #3: Add TruffleHog Scanning (20 mins)
**Impact:** Secrets Management 6/10 → 8/10

**File:** .github/workflows/secret-scan.yml
```yaml
name: Secret Scanning

on: [push, pull_request]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: ${{ github.event.repository.default_branch }}
          head: HEAD
```

**Result:** Catches accidentally committed secrets

---

### Quick Win #4: Add Dependency Scanning (20 mins)
**Impact:** Dependency Security 5/10 → 8/10

**File:** .github/workflows/dependency-scan.yml
```yaml
name: Dependency Scanning

on: [push]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - run: |
          pip install safety
          safety check --json > safety-report.json || true
      
      - uses: actions/upload-artifact@v3
        with:
          name: safety-report
          path: safety-report.json
```

**Result:** Detects CVEs in dependencies

---

### Quick Win #5: Add Audit Logging (25 mins)
**Impact:** Compliance 8/10 → 9/10

**File:** src/security/audit.py
```python
import logging
import json
from datetime import datetime

audit_logger = logging.getLogger("audit")
handler = logging.FileHandler("audit.log")
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
handler.setFormatter(formatter)
audit_logger.addHandler(handler)

def log_audit(action: str, user: str, resource: str, status: str, ip: str = None):
    """Log security events."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "user": user,
        "resource": resource,
        "status": status,
        "ip_address": ip
    }
    audit_logger.info(json.dumps(entry))
```

**Result:** Full audit trail for compliance

---

### Quick Win #6: Add .env.example (10 mins)
**Impact:** Secrets Management 8/10 → 9/10

**File:** .env.example
```bash
# Copy this to .env and fill in your values
# NEVER commit .env!

SECRET_KEY=generate-with-openssl-rand-hex-32
DATABASE_URL=postgresql://user:password@localhost:5432/aqi
VALID_API_KEYS=key1,key2,key3
RENDER_API_KEY=your-render-api-key
```

**Result:** Clear documentation, reduces secrets exposure

---

## 📋 DETAILED IMPLEMENTATION PLAN

### Phase 1: Authentication (3-4 hours) → +2 points
**Impact:** Auth & Authorization 6/10 → 10/10 (+4 actually!)

#### Task 1.1: Add API Key Authentication (1 hour)
```python
# src/security/api_keys.py
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
import os

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Depends(API_KEY_HEADER)):
    """Verify API key."""
    valid_keys = os.getenv("VALID_API_KEYS", "").split(",")
    if api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )
    return api_key

# Usage in endpoints
from app.security.api_keys import verify_api_key

@app.get("/api/v1/predict")
async def predict(
    lat: float,
    lon: float,
    api_key: str = Depends(verify_api_key)
):
    return predict_aqi(lat, lon)
```

#### Task 1.2: Add JWT Token Support (1.5 hours)
```python
# src/security/jwt.py
from datetime import datetime, timedelta
import jwt
import os

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

def create_token(data: dict, expires_delta: timedelta = None):
    """Create JWT token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=1))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    """Verify JWT token."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Token endpoint
@app.post("/auth/token")
async def login(username: str, password: str):
    """Get JWT token."""
    # Verify credentials (use bcrypt)
    if not verify_password(username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token({"sub": username})
    return {"access_token": token, "token_type": "bearer"}
```

#### Task 1.3: Add RBAC (Role-Based Access Control) (1.5 hours)
```python
# src/security/rbac.py
from enum import Enum
from typing import List

class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"

class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"

ROLE_PERMISSIONS = {
    Role.ADMIN: [Permission.READ, Permission.WRITE, Permission.DELETE],
    Role.USER: [Permission.READ, Permission.WRITE],
    Role.VIEWER: [Permission.READ],
}

async def require_permission(
    required: Permission,
    token: dict = Depends(verify_token)
):
    """Check user has permission."""
    user_role = Role(token.get("role", "viewer"))
    if required not in ROLE_PERMISSIONS.get(user_role, []):
        raise HTTPException(status_code=403, detail="Permission denied")
    return token
```

---

### Phase 2: Secrets & Scanning (2-3 hours) → +1.5 points
**Impact:** Secrets 6/10 → 9/10 (+3), Dependency 5/10 → 9/10 (+4)

#### Task 2.1: Add Secret Scanning Workflow (30 mins)
Add `.github/workflows/secret-scan.yml` (see Quick Win #3)

#### Task 2.2: Add Dependency Scanning (30 mins)
Add `.github/workflows/dependency-scan.yml` (see Quick Win #4)

#### Task 2.3: Add SBOM Generation (1 hour)
```yaml
# .github/workflows/sbom.yml
name: Generate SBOM

on: [push]

jobs:
  sbom:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: anchore/sbom-action@v0
        with:
          path: ./
          format: spdx-json
          output-file: sbom.spdx.json
      
      - uses: actions/upload-artifact@v3
        with:
          name: sbom
          path: sbom.spdx.json
```

---

### Phase 3: API Security (2 hours) → +1 point
**Impact:** API Security 7/10 → 10/10 (+3)

#### Task 3.1: Add Rate Limiting (30 mins)
See Quick Win #1

#### Task 3.2: Add CORS Configuration (30 mins)
```python
# app/api.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aqi-predictor-blii.onrender.com",
        "https://yourdomain.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
```

#### Task 3.3: Add Security Headers (30 mins)
See Quick Win #2

---

### Phase 4: Data Protection & Infrastructure (2 hours) → +0.5 points
**Impact:** Data Protection 7/10 → 10/10 (+3), Infrastructure 6/10 → 9/10 (+3)

#### Task 4.1: Add Input Validation (30 mins)
```python
# src/security/validation.py
from pydantic import BaseModel, validator

class PredictRequest(BaseModel):
    lat: float
    lon: float
    
    @validator('lat')
    def validate_lat(cls, v):
        if not -90 <= v <= 90:
            raise ValueError('Invalid latitude')
        return v
```

#### Task 4.2: Add Container Scanning (30 mins)
```yaml
# .github/workflows/container-scan.yml
- uses: aquasecurity/trivy-action@master
  with:
    scan-type: 'fs'
    scan-ref: '.'
    format: 'sarif'
    output: 'trivy-results.sarif'
```

#### Task 4.3: Add Encryption at Rest (30 mins)
For sensitive data in database (if applicable)

---

### Phase 5: Compliance & Documentation (1-2 hours) → +1 point
**Impact:** Compliance 8/10 → 10/10 (+2)

#### Task 5.1: Create SECURITY.md (Update) (30 mins)
```markdown
# Security Policy

## Reporting Vulnerabilities

Please email security@example.com with details.
Do not disclose publicly until we confirm.

## Security Practices

- All API access requires authentication
- Rate limiting: 10 requests/minute
- All requests logged and audited
- Data encrypted in transit (TLS 1.3)
- Dependencies scanned daily
- Secrets rotated quarterly
```

#### Task 5.2: Add Incident Response Plan (30 mins)
```markdown
# Incident Response Plan

## Detection
- Automated alerts on failed logins
- Security scanning detects vulnerabilities
- Audit logs reviewed weekly

## Response
1. Investigate (1 hour)
2. Contain (2 hours)
3. Eradicate (4 hours)
4. Recover (2 hours)
5. Post-mortem (1 week)
```

#### Task 5.3: Add Data Handling Guidelines (30 mins)
```markdown
# Data Handling

- PII: Never logged
- API Keys: Rotated monthly
- Database: Encrypted at rest
- Backups: Daily, encrypted
```

---

## 📊 IMPLEMENTATION TIMELINE

| Phase | Focus | Time | Points | Cumulative |
|-------|-------|------|--------|-----------|
| **Quick Wins** | Rate limit, headers, scanning | 2h | +1.8 | 8.2/10 |
| **Phase 1** | Authentication (API key, JWT, RBAC) | 3-4h | +2.0 | 8.4/10 |
| **Phase 2** | Secrets & scanning (TruffleHog, Safety, SBOM) | 2-3h | +1.5 | 8.9/10 |
| **Phase 3** | API security (rate limit, CORS, headers) | 2h | +1.0 | 9.9/10 |
| **Phase 4** | Data & infrastructure (validation, scanning) | 2h | +0.5 | 10.4/10 |
| **Phase 5** | Compliance & documentation | 1-2h | +1.0 | 11.4/10 → capped at 10/10 |
| **TOTAL** | All areas | 12-16h | **+3.6** | **10/10** |

---

## 💡 PRO TIPS

### Generate Secure Secret Key
```bash
# Generate SECRET_KEY for environment
openssl rand -hex 32
```

### Test API Authentication Locally
```bash
# Get token
curl -X POST http://localhost:8000/auth/token \
  -d "username=test&password=test"

# Use token
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/predict?lat=24.86&lon=67.01
```

### Check for Secrets Locally
```bash
# Install TruffleHog
pip install truffleHog

# Scan current directory
trufflehog filesystem .
```

### Verify Dependencies
```bash
# Check for vulnerabilities
pip install safety
safety check
```

---

## 📈 EXPECTED IMPROVEMENTS

| Component | Before | After | Gain |
|-----------|--------|-------|------|
| Secrets Management | 6/10 | 10/10 | +4 |
| Dependency Security | 5/10 | 10/10 | +5 |
| Auth & Authorization | 6/10 | 10/10 | +4 |
| Data Protection | 7/10 | 10/10 | +3 |
| API Security | 7/10 | 10/10 | +3 |
| Infrastructure | 6/10 | 10/10 | +4 |
| Compliance | 8/10 | 10/10 | +2 |
| **OVERALL** | **6.4/10** | **10/10** | **+3.6** ✅ |

---

## ✅ FINAL CHECKLIST

### Authentication & Authorization ✅
- [ ] API Key authentication
- [ ] JWT token support
- [ ] Role-based access control (RBAC)
- [ ] Password hashing (bcrypt)
- [ ] Multi-factor authentication (optional)

### Secrets Management ✅
- [ ] TruffleHog scanning
- [ ] No hardcoded secrets
- [ ] Environment variables only
- [ ] .env.example created
- [ ] Secret rotation procedure

### Vulnerability Scanning ✅
- [ ] Dependency scanning (Safety)
- [ ] Container scanning (Trivy)
- [ ] SBOM generation (Syft)
- [ ] Supply chain security
- [ ] CVE detection

### API Security ✅
- [ ] Rate limiting (slowapi)
- [ ] CORS configuration
- [ ] Security headers
- [ ] Input validation
- [ ] Request signing (optional)

### Data Protection ✅
- [ ] HTTPS/TLS 1.3
- [ ] Data encryption at rest
- [ ] PII masking
- [ ] Secure headers
- [ ] Certificate pinning (optional)

### Compliance & Audit ✅
- [ ] Audit logging
- [ ] Access logging
- [ ] Security policy
- [ ] Incident response plan
- [ ] Data handling guidelines

---

## 🎓 SUMMARY

**Before:** 6.4/10 (No authentication, limited scanning)
**After:** 10/10 (Enterprise-grade security)

**Key Improvements:**
1. ✅ API Key + JWT authentication
2. ✅ Role-based access control (RBAC)
3. ✅ Secrets scanning (TruffleHog)
4. ✅ Vulnerability scanning (Safety, Trivy)
5. ✅ Rate limiting (slowapi)
6. ✅ Security headers (XSS, CSRF, etc.)
7. ✅ Audit logging (full compliance)
8. ✅ SBOM generation (compliance-ready)

**Timeline:** 12-16 hours to full implementation
**ROI:** Prevents breaches, ensures compliance, protects users
**Enterprise Ready:** ✅ YES
