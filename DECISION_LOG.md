# Decision Log

**Architecture, design, and strategic decisions for AQI Predictor**

---

## ADR-001: Use LightGBM as Primary Model

**Date:** 2026-08-07  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need a production-grade ML model for AQI prediction with:
- Fast inference (<100ms)
- Good accuracy on time-series data
- Explainability (SHAP support)
- Proven in production

### Decision
Use LightGBM as primary model with:
- Separate models for 24h, 48h, 72h horizons
- Trained on 10 Pakistani cities
- SHAP for explainability
- Version control via model registry

### Alternatives Considered
- XGBoost (slower, heavier)
- Neural networks (less interpretable)
- Random Forest (slower)

### Consequences
✅ Fast inference
✅ Explainable
✅ Good accuracy
❌ Single model (mitigated by ensemble in Phase 2)

### Related Issues
- #1: Model selection

---

## ADR-002: Use Render.com for Hosting

**Date:** 2026-08-20  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need hosting platform for FastAPI + Streamlit with:
- Free tier for MVP
- Easy GitHub integration
- HTTPS by default
- Simple scaling to paid tier

### Decision
Deploy to Render.com with:
- Two services: API (FastAPI) + Dashboard (Streamlit)
- Free tier initially, upgrade as needed
- Blueprint for infrastructure-as-code
- Auto-deploy from main branch

### Alternatives Considered
- Heroku (paid only, end of free tier)
- AWS (complex, overkill)
- Railway (newer, less stable)
- Fly.io (good option, but Render simpler)

### Consequences
✅ Free tier available
✅ GitHub integration
✅ Easy scaling
❌ Cold start (15 min idle) - mitigated by uptime monitoring

### Related Issues
- #23: Deployment

---

## ADR-003: Python FastAPI for REST API

**Date:** 2026-08-15  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need REST API for:
- Real-time predictions
- Integration with dashboards
- Public access (no auth initially)
- OpenAPI documentation

### Decision
Use FastAPI with:
- Uvicorn ASGI server
- Pydantic for validation
- OpenAPI auto-documentation
- Rate limiting (slowapi)

### Alternatives Considered
- Flask (simpler, less features)
- Django (overkill, heavy)
- Go (different language)

### Consequences
✅ Modern, fast
✅ Great documentation
✅ Type hints built-in
❌ Smaller ecosystem than Flask

### Related Issues
- #19: API design

---

## ADR-004: Streamlit for Dashboard

**Date:** 2026-08-17  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need interactive dashboard for:
- Visualization
- Easy iteration
- No frontend dev needed
- Interactive maps

### Decision
Use Streamlit with:
- Pydeck for maps
- Plotly for charts
- Direct inference (not API calls)
- Session state for interactivity

### Alternatives Considered
- React (complex, frontend required)
- Vue (similar overhead)
- Dash (heavier than Streamlit)

### Consequences
✅ Rapid development
✅ Interactive
✅ Minimal frontend skills
❌ Not for heavy customization

### Related Issues
- #20: Dashboard

---

## ADR-005: Monorepo Structure

**Date:** 2026-08-10  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need to organize:
- Training code
- Inference code
- Web services
- Configuration
- Tests

### Decision
Use monorepo with structure:
```
src/
  training/    (model training)
  inference/   (prediction code)
  config.py    (centralized config)
  utils/       (shared utilities)
app/
  api.py       (FastAPI)
  streamlit_app.py  (Streamlit)
tests/         (all tests)
notebooks/     (experiments)
docs/          (documentation)
```

### Consequences
✅ Single deployment
✅ Shared code
✅ Easier to maintain
❌ Larger repo size

### Related Issues
- #15: Project structure

---

## ADR-006: Semantic Versioning

**Date:** 2026-09-02  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need versioning scheme that:
- Indicates compatibility
- Follows Python standard
- Enables automated releases

### Decision
Use Semantic Versioning (semver):
- MAJOR.MINOR.PATCH
- v1.0.0 as first release
- Automate bumping in CI/CD

### Format
- Major: Breaking changes
- Minor: New features (backward compatible)
- Patch: Bug fixes

### Related Issues
- #43: Release management

---

## ADR-007: Composite Index in Database

**Date:** 2026-08-25  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need fast queries for:
- Location + timestamp lookups
- Avoiding duplicate predictions

### Decision
Use composite index: (latitude, longitude, timestamp)

### Consequences
✅ Fast lookups
✅ Prevents duplicates
❌ Slight insert overhead

---

## ADR-008: JSON Configuration Over YAML

**Date:** 2026-08-12  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need config format for:
- Model parameters
- Feature store settings
- Deployment config

### Decision
Use Python dict + .env for secrets
Use JSON for structured config

### Advantages
✅ Type-safe
✅ No YAML parsing issues
✅ Python native

### Related Issues
- #40: Configuration

---

## ADR-009: GitHub Actions for CI/CD

**Date:** 2026-08-20  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need CI/CD for:
- Automated testing
- Linting & type checks
- Security scanning
- Automated deployment

### Decision
Use GitHub Actions with 8 workflows:
- lint.yml (code quality)
- ci.yml (testing)
- docker-scan.yml (security)
- release.yml (deployment)
- etc.

### Consequences
✅ Free tier
✅ GitHub native
✅ Simple setup
❌ Limited to GitHub ecosystem

---

## ADR-010: Type Hints for Python Code

**Date:** 2026-09-01  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Need Python code that:
- Is self-documenting
- Catches type errors early
- Improves IDE support

### Decision
Add type hints to all functions:
- Function arguments
- Return types
- Type aliases for complex types

### Consequences
✅ Better IDE support
✅ Early error detection
✅ Self-documenting code
❌ Slight verbosity

### Related Issues
- #34: Code quality

---

## ADR-011: Ensemble Model Strategy (Phase 2)

**Date:** 2026-09-02  
**Status:** PLANNED  
**Authors:** AYYAN

### Context
Current single LightGBM model has:
- Risk of single point of failure
- Limited diversity
- Potential 13% accuracy gain available

### Proposed Decision
Add ensemble with:
- LightGBM (50% weight)
- XGBoost (30% weight)
- CatBoost (20% weight)

### Expected Improvement
- Accuracy: RMSE 17.6 → 15.2 (+13.6%)
- Robustness: No single model failure
- Explainability: Ensemble SHAP values

### Timeline
Phase 2 (after current sprint)

### Related Issues
- #74: ML model audit

---

## ADR-012: Blue-Green Deployment

**Date:** 2026-09-02  
**Status:** ACCEPTED  
**Authors:** AYYAN

### Context
Current deployment has:
- 5-10 minute downtime per release
- No rollback procedure
- No smoke tests

### Decision
Implement blue-green deployment:
- Two identical production instances
- Route traffic gradually
- Automated smoke tests
- Instant rollback capability

### Consequences
✅ Zero-downtime deployments
✅ Easy rollback
✅ Tested before switch
❌ Slightly higher infrastructure cost

### Related Issues
- #23: Deployment

---

## Decision Review Process

1. **Create ADR** - Document decision and alternatives
2. **Discuss** - Get feedback in Discord/PR
3. **Accept/Reject** - Record decision
4. **Implement** - Build according to ADR
5. **Review** - Verify implementation matches ADR
6. **Retrospective** - Review consequences quarterly

---

**Last Updated:** 2026-09-02  
**Total Decisions:** 12 (11 Accepted, 1 Planned)
