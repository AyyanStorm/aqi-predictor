# Contributing to AQI Predictor

Thank you for your interest in contributing! This guide will help you get started.

## Getting Started

### 1. Clone & Setup

```bash
git clone https://github.com/AyyanStorm/aqi-predictor.git
cd aqi-predictor
pip install -e ".[dev]"
```

### 2. Verify Installation

```bash
pytest tests/ -v
# Expected: 449+ tests passing
```

### 3. Run Linting (Before Commit)

```bash
black src/ app/
flake8 src/ app/ --max-line-length=100
mypy src/ app/ --strict
```

### 4. Start Development

```bash
git checkout -b feat/issue-123-description
# Make changes, add tests, commit
git push origin feat/issue-123-description
# Create PR on GitHub
```

---

## Code Style

### Python Code

**Format:** Black (100 character line limit)
```bash
black src/ app/ --line-length=100
```

**Linting:** Flake8
```bash
flake8 src/ app/ --max-line-length=100 --exclude=.venv
```

**Type Hints:** Required for public functions
```python
# ✅ Good
def predict(lat: float, lon: float, city: str = "api") -> dict:
    """Predict AQI for coordinates."""
    return {}

# ❌ Bad
def predict(lat, lon, city="api"):
    return {}
```

**Docstrings:** NumPy style
```python
def aqi_category(aqi: float) -> str:
    """
    Return EPA AQI category for given AQI value.
    
    Parameters
    ----------
    aqi : float
        Air Quality Index value (0-500+)
    
    Returns
    -------
    str
        EPA category name (e.g., 'Good', 'Moderate', 'Unhealthy')
    
    Examples
    --------
    >>> aqi_category(45)
    'Good'
    >>> aqi_category(125)
    'Unhealthy for Sensitive Groups'
    """
    if aqi < 50:
        return "Good"
    # ...
```

**Logging:** Use structured logging, NOT print()
```python
# ✅ Good
logger.info('Model loaded', extra={'model': name, 'version': version})
logger.error('Prediction failed', exc_info=True)

# ❌ Bad
print(f"Model loaded: {name}")
```

### Markdown

- **Line length:** 80-100 characters
- **Headers:** Use `#` (no underlines)
- **Code blocks:** Specify language (python, bash, json)
- **Links:** Use absolute URLs for cross-repo links

---

## Testing Requirements

### Test Coverage
- Minimum: **80%** code coverage
- Target: **90%+** coverage
- Run: `pytest --cov=src --cov=app tests/`

### Test Organization
```
tests/
├── unit/                    # Unit tests (fast, isolated)
│   ├── inference/
│   ├── training/
│   └── utils/
├── integration/             # Integration tests (slower, real data)
│   ├── test_prediction_pipeline.py
│   └── test_feature_store_integration.py
└── conftest.py             # Shared fixtures
```

### Writing Tests

```python
import pytest
from src.utils.aqi_utils import aqi_category

class TestAQICategory:
    """Test EPA AQI category classification."""
    
    def test_good_aqi(self):
        """AQI < 50 should return 'Good'."""
        assert aqi_category(45) == "Good"
    
    def test_moderate_aqi(self):
        """AQI 51-100 should return 'Moderate'."""
        assert aqi_category(75) == "Moderate"
    
    @pytest.mark.parametrize("aqi,expected", [
        (10, "Good"),
        (75, "Moderate"),
        (150, "Unhealthy for Sensitive Groups"),
    ])
    def test_all_categories(self, aqi, expected):
        """Test all EPA AQI categories."""
        assert aqi_category(aqi) == expected
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/unit/test_aqi_utils.py -v

# Specific test class
pytest tests/unit/test_aqi_utils.py::TestAQICategory -v

# With coverage report
pytest tests/ --cov=src --cov=app --cov-report=html

# Only fast tests (skip slow)
pytest tests/ -m "not slow" -v
```

---

## Git Workflow

### Branch Naming

```
feat/issue-123-brief-description     # Features
fix/issue-456-brief-description      # Bugs
docs/issue-789-brief-description     # Documentation
chore/some-maintenance-task          # Maintenance
```

### Commit Messages

```
feat(#123): Add API rate limiting endpoint

Add /rate-limit endpoint to retrieve current limits.

- POST /admin/configure-limits
- GET /rate-limits
- Returns: {limit, remaining, reset_at}

Closes #123
```

**Format:** `<type>(<issue>): <subject>`

**Types:**
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation
- `chore` - Maintenance (no code change)
- `test` - Test additions
- `refactor` - Code reorganization (no behavior change)

**Rules:**
- Subject < 50 characters
- Use imperative mood ("Add" not "Added")
- Reference related issue (#123)
- End with "Closes #123" if closing an issue

### Pull Request Process

1. **Push branch to GitHub**
   ```bash
   git push origin feat/issue-123-description
   ```

2. **Create PR on GitHub**
   - Title: Same as commit message subject
   - Description: Reference issue, explain changes
   - Checklist: Complete all items

3. **PR Template (Auto-filled)**
   ```markdown
   ## Description
   Brief description of changes
   
   ## Related Issue
   Closes #123
   
   ## Type of Change
   - [x] Bug fix
   - [ ] New feature
   
   ## Testing
   - [x] Unit tests added
   - [x] Integration tests pass
   - [x] Manual testing completed
   
   ## Checklist
   - [x] Code follows style guidelines
   - [x] Documentation updated
   - [x] Tests pass locally
   ```

4. **Wait for CI/CD**
   - Tests must pass (pytest)
   - Linting must pass (black, flake8, mypy)
   - Docker scan must pass (Trivy)
   - Security scan must pass

5. **Code Review**
   - Address reviewer feedback
   - Push fixes to same branch (auto-updates PR)
   - Request re-review when ready

6. **Merge**
   - Maintainer merges PR
   - Branch auto-deletes

---

## Common Tasks

### Add a New API Endpoint

1. **Create schema** in `app/schemas.py`
   ```python
   from pydantic import BaseModel, Field
   
   class MyResponse(BaseModel):
       """Response schema for my endpoint."""
       data: str = Field(..., description="Response data")
   ```

2. **Add endpoint** in `app/api.py`
   ```python
   @app.get("/my-endpoint", response_model=MyResponse, tags=["MyFeature"])
   def my_endpoint(param: str = Query(..., description="Parameter")):
       """Brief endpoint description."""
       return {"data": "result"}
   ```

3. **Add tests** in `tests/integration/test_api.py`
   ```python
   def test_my_endpoint():
       response = client.get("/my-endpoint?param=test")
       assert response.status_code == 200
       assert response.json()["data"] == "result"
   ```

4. **Document** in endpoint docstring with examples

### Add Model Training Code

1. **Create file** in `src/training/`
2. **Add tests** in `tests/unit/training/`
3. **Update** `docs/RUNBOOKS.md` if it's an operational procedure
4. **Add** to CI training workflow if needed

### Add Utility Function

1. **Create file** in `src/utils/`
2. **Include docstring** with examples
3. **Add type hints** for all parameters and return
4. **Add tests** in `tests/unit/` matching directory structure
5. **Test coverage** must stay ≥80%

---

## Debugging

### Local Development

```bash
# Run with debug logging
LOGLEVEL=DEBUG python -m app.streamlit_app

# Run API with auto-reload
uvicorn app.api:app --reload --log-level debug

# Debug specific test
pytest tests/unit/test_aqi_utils.py::TestAQICategory::test_good_aqi -vv --pdb
```

### Docker Debugging

```bash
# Build with debug logging
docker build -f Dockerfile.api --build-arg LOGLEVEL=DEBUG -t aqi-api .

# Run container with interactive shell
docker run -it aqi-api /bin/bash

# Check logs
docker logs <container-id> -f
```

---

## Documentation

### Update README.md
- If adding feature or changing installation
- Keep "Quick Start" section current
- Add examples of new functionality

### Update DOCKER.md
- If changing docker-compose.yml
- If adding new services or ports
- Update troubleshooting section

### Update CHANGELOG.md
- Add to "Unreleased" section
- Follow "Keep a Changelog" format
- Move to version when released

### API Documentation
- Update endpoint docstrings in `app/api.py`
- Pydantic models auto-generate OpenAPI schema
- Test at http://localhost:8000/docs

---

## Issues & Discussions

### Before Starting Work
1. Check if issue already exists (search)
2. Comment on issue to claim it
3. Get feedback from maintainers
4. Discuss approach for large changes

### Reporting Bugs
- Use [Bug Report template](https://github.com/AyyanStorm/aqi-predictor/issues/new?template=bug_report.md)
- Include reproducible steps
- Include environment (Python version, OS, Docker?)
- Include error logs with request_id if API

### Requesting Features
- Use [Feature Request template](https://github.com/AyyanStorm/aqi-predictor/issues/new?template=feature_request.md)
- Explain motivation
- Discuss alternatives
- Link to related issues

---

## Support

### Questions?
- Open an issue with label `question`
- Check [GitHub Discussions](https://github.com/AyyanStorm/aqi-predictor/discussions)
- Review existing issues and PRs

### Problems?
- Check [DOCKER.md](DOCKER.md) for deployment help
- Check [docs/RUNBOOKS.md](docs/RUNBOOKS.md) for operations
- Open an issue with full error context

---

## Code of Conduct

- Be respectful and inclusive
- Assume good intent
- Provide constructive feedback
- Welcome diverse perspectives
- Report violations to maintainers

---

## License

By contributing, you agree your code will be licensed under the [MIT License](LICENSE).

---

**Thank you for contributing! 🎉**
