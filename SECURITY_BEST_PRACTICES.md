# Security Best Practices: 6.4/10 → 10/10

**Production-grade security implementation guide**

---

## 🔐 QUICK REFERENCE: What to Add

### 1. API Authentication (HIGHEST IMPACT)
```python
# Add to app/api.py
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from datetime import datetime, timedelta
import jwt
import os

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"

# ✅ API Key authentication
async def verify_api_key(api_key: str = Depends(API_KEY_HEADER)):
    """Verify API key for public endpoints."""
    valid_keys = os.getenv("VALID_API_KEYS", "").split(",")
    if api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )
    return api_key

# ✅ JWT token authentication
async def verify_token(token: str = Depends(APIKeyHeader(name="Authorization"))):
    """Verify JWT token."""
    try:
        payload = jwt.decode(token.replace("Bearer ", ""), SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ✅ Protected endpoints
@app.get("/api/v1/predict")
async def predict(lat: float, lon: float, api_key: str = Depends(verify_api_key)):
    """Predict AQI (requires API key)."""
    return predict_aqi(lat, lon)
```

### 2. Rate Limiting (Prevent Abuse)
```python
# Add to requirements.txt
# slowapi==0.1.9

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ✅ Apply rate limiting
@app.get("/api/v1/predict")
@limiter.limit("10/minute")  # 10 requests per minute
async def predict(request: Request, lat: float, lon: float):
    """Predict AQI with rate limiting."""
    return predict_aqi(lat, lon)
```

### 3. Secrets Scanning (GitHub Actions)
```yaml
# .github/workflows/secret-scan.yml
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

### 4. Vulnerability Scanning
```yaml
# .github/workflows/security-scan.yml
name: Security Scanning

on: [push]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      # Scan Python dependencies
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - run: |
          pip install safety
          safety check --json
      
      # Scan container image
      - uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '.'
```

### 5. Audit Logging (Track Access)
```python
# Add to app/api.py
import logging
from datetime import datetime

audit_logger = logging.getLogger("audit")

def log_audit(action: str, user: str, resource: str, status: str):
    """Log security-relevant events."""
    audit_logger.info(
        f"[{datetime.utcnow().isoformat()}] "
        f"Action={action} User={user} Resource={resource} Status={status}"
    )

@app.get("/api/v1/predict")
async def predict(lat: float, lon: float, api_key: str = Depends(verify_api_key)):
    """Predict AQI with audit logging."""
    log_audit("PREDICT", api_key, f"({lat},{lon})", "START")
    try:
        result = predict_aqi(lat, lon)
        log_audit("PREDICT", api_key, f"({lat},{lon})", "SUCCESS")
        return result
    except Exception as e:
        log_audit("PREDICT", api_key, f"({lat},{lon})", f"FAILED: {str(e)}")
        raise
```

---

## 📚 DETAILED IMPLEMENTATION PATTERNS

### Pattern 1: API Key Management

**Problem:** No way to control who can access the API

**Solution:**
```python
# src/security/api_keys.py
from datetime import datetime, timedelta
from enum import Enum
import secrets

class Tier(str, Enum):
    FREE = "free"      # 10 requests/minute
    PRO = "pro"        # 100 requests/minute
    ENTERPRISE = "enterprise"  # Unlimited

class APIKey:
    def __init__(self, key: str, tier: Tier, created_at: datetime):
        self.key = key
        self.tier = tier
        self.created_at = created_at
        self.last_used = None
        self.is_revoked = False
    
    @staticmethod
    def generate():
        """Generate secure API key."""
        return f"aqi_{secrets.token_urlsafe(32)}"
    
    def is_valid(self):
        """Check if key is valid."""
        return not self.is_revoked
    
    def revoke(self):
        """Revoke the key."""
        self.is_revoked = True

# Store in database or environment
API_KEYS = {
    "aqi_demo_key_123": APIKey("aqi_demo_key_123", Tier.FREE, datetime.now()),
}

async def verify_api_key(api_key: str = Depends(APIKeyHeader(name="X-API-Key"))):
    """Verify and track API key usage."""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    key_obj = API_KEYS[api_key]
    if not key_obj.is_valid():
        raise HTTPException(status_code=403, detail="API key revoked")
    
    key_obj.last_used = datetime.now()
    return key_obj
```

---

### Pattern 2: JWT Authentication

**Problem:** Stateless authentication for users

**Solution:**
```python
# src/security/jwt.py
from datetime import datetime, timedelta
from typing import Optional
import jwt
import os

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
EXPIRATION_MINUTES = 60

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create JWT token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=EXPIRATION_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> dict:
    """Verify JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Usage in API
from fastapi.security import HTTPBearer, HTTPAuthCredentials

security = HTTPBearer()

@app.post("/login")
async def login(username: str, password: str):
    """Login and get JWT token."""
    # Verify username/password (use bcrypt for real implementation)
    if not verify_password(username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_access_token({"sub": username})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/v1/predict")
async def predict(
    lat: float,
    lon: float,
    credentials: HTTPAuthCredentials = Depends(security)
):
    """Protected endpoint requiring JWT."""
    payload = verify_token(credentials.credentials)
    user = payload.get("sub")
    return predict_aqi(lat, lon)
```

---

### Pattern 3: Role-Based Access Control (RBAC)

**Problem:** All users have all permissions

**Solution:**
```python
# src/security/rbac.py
from enum import Enum
from typing import List

class Role(str, Enum):
    ADMIN = "admin"           # Full access
    USER = "user"             # Read access
    VIEWER = "viewer"         # Limited read

class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"

ROLE_PERMISSIONS = {
    Role.ADMIN: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.ADMIN],
    Role.USER: [Permission.READ, Permission.WRITE],
    Role.VIEWER: [Permission.READ],
}

async def verify_permission(
    required_permission: Permission,
    current_user: dict = Depends(verify_token)
):
    """Check user has required permission."""
    user_role = Role(current_user.get("role", "viewer"))
    permissions = ROLE_PERMISSIONS.get(user_role, [])
    
    if required_permission not in permissions:
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied. Required: {required_permission}"
        )
    return current_user

# Protect endpoints
@app.delete("/api/v1/predictions/{id}")
async def delete_prediction(
    id: str,
    user = Depends(verify_permission(Permission.DELETE))
):
    """Only admins can delete."""
    return {"deleted": id}
```

---

### Pattern 4: Audit Logging

**Problem:** No trace of who accessed what

**Solution:**
```python
# src/security/audit.py
import logging
from datetime import datetime
from typing import Any
import json

# Configure audit logger
audit_logger = logging.getLogger("audit")
handler = logging.FileHandler("audit.log")
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
handler.setFormatter(formatter)
audit_logger.addHandler(handler)

class AuditLog:
    @staticmethod
    def log(
        action: str,
        user: str,
        resource: str,
        details: dict = None,
        status: str = "SUCCESS",
        ip_address: str = None
    ):
        """Log security-relevant events."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "user": user,
            "resource": resource,
            "status": status,
            "ip_address": ip_address,
            "details": details or {}
        }
        audit_logger.info(json.dumps(log_entry))

# Usage in endpoints
from fastapi import Request

@app.get("/api/v1/predict")
async def predict(
    request: Request,
    lat: float,
    lon: float,
    user = Depends(verify_token)
):
    """Predict with audit logging."""
    AuditLog.log(
        action="PREDICT",
        user=user.get("sub"),
        resource=f"predict({lat},{lon})",
        status="START",
        ip_address=request.client.host
    )
    
    try:
        result = predict_aqi(lat, lon)
        AuditLog.log(
            action="PREDICT",
            user=user.get("sub"),
            resource=f"predict({lat},{lon})",
            status="SUCCESS",
            details={"aqi": result}
        )
        return result
    except Exception as e:
        AuditLog.log(
            action="PREDICT",
            user=user.get("sub"),
            resource=f"predict({lat},{lon})",
            status="FAILED",
            details={"error": str(e)}
        )
        raise
```

---

### Pattern 5: CORS & Security Headers

**Problem:** Missing security headers, no CORS configuration

**Solution:**
```python
# Add to app/api.py
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

# ✅ CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aqi-predictor-blii.onrender.com",
        "https://yourdomain.com",
    ],  # Only allow specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # Only needed methods
    allow_headers=["Content-Type", "Authorization"],
)

# ✅ Trusted host middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["aqi-predictor-blii.onrender.com", "yourdomain.com"]
)

# ✅ Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    
    # Prevent XSS
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    
    # HTTPS enforcement
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # Prevent MIME sniffing
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    
    # Prevent referrer leakage
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    return response
```

---

### Pattern 6: Input Validation & Sanitization

**Problem:** No input validation on API endpoints

**Solution:**
```python
# src/security/validation.py
from pydantic import BaseModel, validator
from typing import Optional

class PredictRequest(BaseModel):
    lat: float
    lon: float
    
    @validator('lat')
    def validate_latitude(cls, v):
        """Validate latitude is in valid range."""
        if not -90 <= v <= 90:
            raise ValueError('Latitude must be between -90 and 90')
        return v
    
    @validator('lon')
    def validate_longitude(cls, v):
        """Validate longitude is in valid range."""
        if not -180 <= v <= 180:
            raise ValueError('Longitude must be between -180 and 180')
        return v

# Usage in endpoint
@app.post("/api/v1/predict")
async def predict(
    request: PredictRequest,
    user = Depends(verify_token)
):
    """Predict AQI with validated input."""
    # request.lat and request.lon are guaranteed valid
    return predict_aqi(request.lat, request.lon)
```

---

### Pattern 7: Secrets Management

**Problem:** Secrets stored in code or .env files

**Solution:**
```bash
# .env.example (NEVER commit secrets!)
SECRET_KEY=use-environment-variable
DATABASE_URL=use-environment-variable
API_KEYS=use-environment-variable

# Render deployment
# Set environment variables in Render dashboard:
# - SECRET_KEY: (generate with `openssl rand -hex 32`)
# - DATABASE_URL: postgres://...
# - API_KEYS: key1,key2,key3

# Python code
import os
from dotenv import load_dotenv

load_dotenv()  # Load .env locally only

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY not set in environment")

# Never hardcode secrets!
```

---

### Pattern 8: Password Hashing

**Problem:** No password hashing if storing user passwords

**Solution:**
```python
# Add to requirements.txt
# bcrypt==4.0.1

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash password securely."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(plain_password, hashed_password)

# Usage in user creation
@app.post("/users")
async def create_user(username: str, password: str):
    """Create user with hashed password."""
    hashed_pwd = hash_password(password)
    # Store hashed_pwd in database, never the plain password
    return {"username": username, "created": True}
```

---

### Pattern 9: SBOM Generation

**Problem:** No software bill of materials for compliance

**Solution:**
```yaml
# .github/workflows/sbom.yml
name: Generate SBOM

on: [push]

jobs:
  sbom:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      # Generate SBOM with Syft
      - uses: anchore/sbom-action@v0
        with:
          path: ./
          format: spdx-json
          output-file: sbom.spdx.json
      
      # Upload SBOM
      - uses: actions/upload-artifact@v3
        with:
          name: sbom
          path: sbom.spdx.json
```

---

## 📋 SECURITY CHECKLIST

### Authentication ✅
- [ ] API key authentication
- [ ] JWT token support
- [ ] Password hashing (bcrypt)
- [ ] Multi-factor authentication

### Authorization ✅
- [ ] Role-based access control (RBAC)
- [ ] Permission system
- [ ] Endpoint protection
- [ ] Resource-level access control

### Secrets ✅
- [ ] No hardcoded secrets
- [ ] Environment variables
- [ ] TruffleHog scanning
- [ ] Secret rotation procedures

### Scanning ✅
- [ ] Dependency vulnerability scanning
- [ ] Container image scanning
- [ ] SBOM generation
- [ ] Supply chain security

### API Security ✅
- [ ] Rate limiting
- [ ] CORS configuration
- [ ] Security headers
- [ ] Request validation
- [ ] Input sanitization

### Audit & Compliance ✅
- [ ] Audit logging
- [ ] Access logging
- [ ] Error logging
- [ ] Compliance reports

### Data Protection ✅
- [ ] HTTPS enforced
- [ ] TLS 1.3
- [ ] Data encryption at rest
- [ ] PII masking

---

## ✅ SUMMARY

**Key Improvements:**
1. ✅ API Key + JWT authentication
2. ✅ Rate limiting (slowapi)
3. ✅ Secrets scanning (TruffleHog)
4. ✅ Vulnerability scanning (Safety, Trivy)
5. ✅ Audit logging (all access tracked)
6. ✅ RBAC (role-based permissions)
7. ✅ Security headers (XSS, CSRF, etc.)
8. ✅ SBOM generation (compliance ready)

**Enterprise Ready:** ✅ YES
