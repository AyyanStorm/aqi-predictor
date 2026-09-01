# Security Policy

## Reporting a Vulnerability

**DO NOT** create public GitHub issues for security vulnerabilities.

Instead, email your findings to: **ayyan.storm@github.com**

### What to Include

- **Description:** Clear description of the vulnerability
- **Affected versions:** Which versions are vulnerable?
- **Steps to reproduce:** How to trigger the vulnerability
- **Impact:** What could an attacker do?
- **Suggested fix:** If you have one (optional)
- **Your contact:** How should we reach you?

### Response Timeline

- **Within 48 hours:** We'll acknowledge receipt
- **Within 7 days:** We'll provide initial assessment
- **Within 14 days:** We'll work on a fix or mitigation
- **Upon fix:** We'll coordinate disclosure and release

---

## Supported Versions

| Version | Supported | Status |
|---------|-----------|--------|
| 0.1.x   | ✅ Yes    | Beta (active development) |
| < 0.1   | ❌ No     | Not released |
| Nightly | ✅ Yes    | Development branch |

Security updates are released as soon as possible after discovery.

---

## Security Features

### Authentication & Authorization
- ✅ No authentication required (public API, rate-limited)
- ✅ API rate limiting: 30 req/min per IP
- ✅ Request IDs for tracing and abuse detection
- ✅ Admin endpoints protected by environment variables

### Container Security
- ✅ **Non-root execution:** All containers run as `uid 1000` (appuser)
- ✅ **Minimal base images:** `python:3.12-slim`
- ✅ **Read-only root filesystem:** Supported via docker-compose
- ✅ **Resource limits:** Memory/CPU constrained
- ✅ **Health checks:** Automated recovery
- ✅ **Security scanning:** Trivy CI on every Dockerfile change

### Dependency Security
- ✅ **Pinned versions:** All dependencies pinned with `==` (Issue #44)
- ✅ **Dependency verification:** Manual PyPI audit
- ✅ **Automated scanning:** GitHub Dependabot alerts
- ✅ **Transitive dependencies:** pip-compile resolves conflicts

### Secrets Management
- ✅ **Environment-based:** No hardcoded credentials
- ✅ **Local .env:** Loaded only for development
- ✅ **.env.example:** Template provided, credentials not stored
- ✅ **.gitignore:** Secrets never committed to git
- ✅ **Hopsworks API key:** Loaded from `HOPSWORKS_API_KEY` env var

### Data Protection
- ✅ **HTTPS:** Required in production (enforced by reverse proxy)
- ✅ **Input validation:** All query parameters validated (lat/lon ranges)
- ✅ **Output encoding:** JSON responses properly encoded
- ✅ **Caching:** Predictions cached only locally
- ✅ **Data retention:** Feature store in Parquet (queryable, auditable)

### Error Handling
- ✅ **No sensitive data in errors:** Error messages don't leak credentials
- ✅ **Proper HTTP codes:** 400, 503, 500 don't expose internals
- ✅ **Request ID tracing:** Every response has `request_id` for debugging
- ✅ **Structured logging:** All logs go through logger, not stdout

### Code Quality
- ✅ **Type hints:** Enable type safety with mypy
- ✅ **Linting:** Black, flake8, pylint enforce style
- ✅ **Testing:** 449+ tests with >80% coverage
- ✅ **Code review:** All changes via PRs with CI/CD checks

### CI/CD Security
- ✅ **Docker scan:** Trivy scans all Dockerfiles for vulnerabilities
- ✅ **Dependency check:** Dependabot alerts on outdated/vulnerable packages
- ✅ **Code scan:** GitHub security scanning (if enabled)
- ✅ **SAST:** Static analysis via mypy and flake8

---

## Compliance & Standards

### CIS Docker Benchmark v1.5.0
- ✅ **4.1** Image from Official Registry
- ✅ **4.4** Run containers as non-root user
- ✅ **4.11** Health checks enabled
- ✅ **4.12** No privileged containers
- ✅ **5.30** User namespace remapped (if using Docker swarm)

### OWASP Container Security

**Secure image composition:**
- ✅ Minimal base images
- ✅ Dependency pinning
- ✅ Vulnerability scanning
- ✅ Multi-stage builds (future optimization)

**Runtime security:**
- ✅ Non-root execution
- ✅ Read-only filesystem
- ✅ Resource limits
- ✅ No privileged mode

**Supply chain security:**
- ✅ Signed commits (recommended)
- ✅ Dependency verification
- ✅ Code review before merge

---

## Known Limitations

### Out of Scope (NOT Security Issues)
- Performance optimization requests
- Feature requests without security impact
- Documentation improvements (minor typos)

### Known Issues

None currently. If you discover a vulnerability, please report it confidentially.

---

## Security Checklist for Deployments

Use this checklist before deploying to production:

- [ ] **Environment variables set**
  - [ ] `HOPSWORKS_API_KEY` (if using feature store)
  - [ ] `HOPSWORKS_PROJECT` (if using feature store)
  - [ ] Docker secrets properly mounted

- [ ] **Docker security**
  - [ ] All images built with pinned `FROM` tags
  - [ ] Trivy scan passed (no CRITICAL/HIGH vulns)
  - [ ] Non-root user verified: `docker run image id` returns `uid=1000`
  - [ ] Health checks enabled in docker-compose

- [ ] **Network security**
  - [ ] HTTPS/TLS enabled (reverse proxy required)
  - [ ] Rate limiting active (30 req/min)
  - [ ] Firewall rules restrict access as needed
  - [ ] No public ports except API/Dashboard

- [ ] **Secrets management**
  - [ ] No .env files in git
  - [ ] All secrets via environment variables
  - [ ] Secrets not logged (check logs for sensitive data)
  - [ ] Rotation plan in place

- [ ] **Monitoring & Logging**
  - [ ] Prometheus scraping metrics
  - [ ] Grafana dashboards configured
  - [ ] Logs aggregated to central location
  - [ ] Alert rules for errors/latency

- [ ] **Backups & Recovery**
  - [ ] Feature store backed up
  - [ ] Model registry backed up
  - [ ] Recovery procedures tested
  - [ ] RTO/RPO defined

- [ ] **Compliance**
  - [ ] Security policy communicated to users
  - [ ] Incident response plan in place
  - [ ] Legal review completed (if needed)

---

## Incident Response

### If You Discover a Vulnerability

1. **Report confidentially** to security contact
2. **Do NOT** share details publicly or in issues
3. **Do NOT** exploit the vulnerability
4. **Provide** reproduction steps and impact assessment

### Our Incident Response Process

1. **Triage (24h):** Assess severity and impact
2. **Investigate (48h-7d):** Reproduce and understand root cause
3. **Fix (7d-14d):** Develop and test patch
4. **Release (by day 14):** Deploy fix via security release
5. **Disclose (after patch):** Publish CVE/advisory
6. **Postmortem (after patch):** Document lessons learned

---

## Security Resources

- [OWASP Container Security](https://owasp.org/www-project-container-security/)
- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)

---

## Questions?

- 📧 Email: ayyan.storm@github.com (for security issues)
- 🐛 GitHub Issues: (for non-security bugs)
- 💬 Discussions: (for questions)

**Thank you for helping keep AQI Predictor secure!** 🔒
