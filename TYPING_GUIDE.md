# Type Hints Guide for AQI Predictor

**Quick reference for adding type hints to improve code quality from 6.4/10 → 10/10**

---

## 🎯 Why Type Hints?

```python
# ❌ Without type hints (confusing)
def predict(coords, model):
    return model.infer(coords)

# ✅ With type hints (crystal clear)
from typing import Tuple
import numpy as np

def predict(coords: Tuple[float, float], model: LGBMRegressor) -> float:
    """Predict AQI for coordinates.
    
    Args:
        coords: (latitude, longitude) tuple
        model: Trained LightGBM model
        
    Returns:
        Predicted AQI value (0-500+)
    """
    return model.predict([coords])[0]
```

**Benefits:**
- IDE autocomplete works perfectly ✅
- Type checkers (mypy) catch bugs before runtime ✅
- Self-documenting code ✅
- Easier refactoring ✅
- New contributors understand faster ✅

---

## 📚 Type Hints Cheat Sheet

### Basic Types
```python
def func(
    x: int,                    # Integer
    y: float,                  # Floating point
    name: str,                 # String
    flag: bool,                # Boolean
) -> None:                     # Returns nothing
    pass
```

### Optional (Can be None)
```python
from typing import Optional

def get_city(name: str) -> Optional[str]:
    """Return city name or None if not found."""
    if name in CITIES:
        return name
    return None
```

### Collections
```python
from typing import List, Dict, Tuple, Set

def batch_process(
    items: List[str],                          # List of strings
    config: Dict[str, float],                  # Dict with string keys, float values
    coords: Tuple[float, float],               # Tuple of (lat, lon)
    tags: Set[str],                            # Set of strings
) -> List[Dict[str, Any]]:                     # Return list of dicts
    pass
```

### Union (Multiple Types)
```python
from typing import Union

def get_value(key: str) -> Union[int, str, None]:
    """Return int, str, or None."""
    ...
```

### Generic/Custom Types
```python
from typing import Callable, Any

def apply(
    func: Callable[[int], str],                # Function that takes int, returns str
    values: List[int],
) -> List[str]:
    return [func(v) for v in values]
```

### Type Aliases (Define once, reuse everywhere)
```python
from typing import Tuple, Dict

# Define aliases at module level
Coordinates = Tuple[float, float]  # (lat, lon)
Location = Dict[str, float]        # {"lat": 24.86, "lon": 67.01}
Predictions = Dict[str, float]     # {"24h": 68.5, "48h": 72.0, ...}

# Use in functions
def predict(coords: Coordinates) -> Predictions:
    """Predict AQI for coordinates."""
    ...
```

---

## 🔧 How to Add Type Hints to a File

### Step 1: Add Imports
```python
# At top of file, after docstring
from typing import Optional, List, Dict, Tuple, Union, Any, Callable
import numpy as np
import pandas as pd
```

### Step 2: Add Type Aliases (if complex types)
```python
# After imports
AQIBand = Tuple[int, int, str, str, str]  # (min, max, label, color, msg)
Location = Dict[str, float]
Predictions = Dict[str, float]
```

### Step 3: Add Type Hints to Functions
```python
# Before: No type hints
def aqi_category(aqi):
    """Get category name for AQI value."""
    return _band_for(aqi)[2]

# After: With type hints
def aqi_category(aqi: float) -> str:
    """Get category name for AQI value.
    
    Args:
        aqi: Air Quality Index (0-500+)
        
    Returns:
        Category name ('Good', 'Moderate', 'Unhealthy', etc.)
    """
    return _band_for(aqi)[2]
```

### Step 4: Update Docstrings (NumPy format)
```python
def resolve_timezone(lat: float, lon: float, name: Optional[str] = None) -> Optional[str]:
    """Resolve IANA timezone for geographic coordinates.
    
    Uses two strategies:
    1. City name lookup (if provided)
    2. Lat/lon + Open-Meteo timezone lookup
    
    Args:
        lat: Latitude in degrees (-90 to 90)
        lon: Longitude in degrees (-180 to 180)
        name: Optional city name for faster lookup
        
    Returns:
        IANA timezone string (e.g., 'Asia/Karachi'), or None if unresolvable
        
    Raises:
        ValueError: If coordinates are out of valid range
        requests.RequestException: If API call fails
        
    Examples:
        >>> resolve_timezone(24.86, 67.01)
        'Asia/Karachi'
        
        >>> resolve_timezone(24.86, 67.01, 'Karachi')
        'Asia/Karachi'
    """
    ...
```

---

## ✅ Type Hints Checklist

For each function, ensure:
- [ ] Function name is descriptive
- [ ] All parameters have type hints: `param: Type`
- [ ] Return type is specified: `-> Type:`
- [ ] Docstring includes Args, Returns sections
- [ ] Complex types use aliases for readability
- [ ] Optional params use `Optional[Type]` or default=None
- [ ] No bare `Any` types (use when really needed, document why)

---

## 🚀 Converting a File: Example

### Before (No Type Hints)
```python
# src/utils/aqi_utils.py

def aqi_category(aqi):
    """Band label for an AQI value, e.g. 42 -> 'Good'."""
    return _band_for(aqi)[2]

def is_hazardous(aqi):
    """True when AQI >= 151 — the 'Unhealthy' band and above."""
    return aqi >= HAZARDOUS_THRESHOLD

def _band_for(aqi):
    """Return the band tuple for an AQI."""
    for band in AQI_BANDS:
        lo, hi = band[0], band[1]
        if lo <= aqi <= hi:
            return band
    if aqi < 0:
        return AQI_BANDS[0]
    return AQI_BANDS[-1]
```

**Issues:**
- ❌ No idea what types `aqi` should be
- ❌ No idea what `_band_for()` returns
- ❌ IDE can't help with autocomplete
- ❌ mypy can't validate calls to these functions

### After (With Type Hints)
```python
# src/utils/aqi_utils.py

from typing import Tuple

# Type alias for clarity
AQIBand = Tuple[int, int, str, str, str]  # (min, max, label, color, message)

def aqi_category(aqi: float) -> str:
    """Band label for an AQI value, e.g. 42 -> 'Good'.
    
    Args:
        aqi: Air Quality Index value (0-500+)
        
    Returns:
        Category name ('Good', 'Moderate', 'Unhealthy', etc.)
    """
    return _band_for(aqi)[2]

def is_hazardous(aqi: float) -> bool:
    """Check if AQI is in hazardous range (>= 151).
    
    Args:
        aqi: Air Quality Index value (0-500+)
        
    Returns:
        True if hazardous, False otherwise
    """
    return aqi >= HAZARDOUS_THRESHOLD

def _band_for(aqi: float) -> AQIBand:
    """Get the AQI band tuple for a value.
    
    Args:
        aqi: Air Quality Index value (0-500+)
        
    Returns:
        AQIBand tuple (min, max, label, color, message)
    """
    for band in AQI_BANDS:
        lo, hi = band[0], band[1]
        if lo <= aqi <= hi:
            return band
    if aqi < 0:
        return AQI_BANDS[0]
    return AQI_BANDS[-1]
```

**Benefits:**
- ✅ Crystal clear: `aqi` is a `float`, returns `str` or `bool`
- ✅ IDE autocomplete works perfectly
- ✅ mypy validates all calls
- ✅ New developers understand instantly

---

## 🎯 Priority Files to Type (Highest Impact)

1. **`src/inference/predict.py`** (Core logic)
   - `predict()` - Main prediction function
   - `predict_cached()` - Cache-aware prediction
   
2. **`src/training/model_registry.py`** (Model management)
   - `get_production()` - Get production model
   - `promote()` - Promote candidate model
   
3. **`app/api.py`** (REST API)
   - All route handlers
   - Response models
   
4. **`src/features/backends.py`** (Feature store)
   - All backend methods
   - Return types for features
   
5. **`src/tracking/drift_detector.py`** (Monitoring)
   - Drift detection methods
   - Report generation

---

## 🔍 Validate with Mypy

**Install mypy:**
```bash
pip install mypy
```

**Check a file:**
```bash
mypy src/utils/aqi_utils.py
```

**Check entire project:**
```bash
mypy src/ app/ --ignore-missing-imports
```

**Expected output (0 errors):**
```
Success: no issues found in 3 source files
```

---

## 📊 Scoring

| Type Hint Coverage | Code Quality Score |
|-------------------|-------------------|
| 0% (current) | 0/10 |
| 25% | 2.5/10 |
| 50% | 5/10 |
| 75% | 7.5/10 |
| **100%** | **10/10** ✅ |

**Current:** 0% → **0/10**
**Target:** 100% → **10/10**

---

## ✨ Summary

Adding type hints transforms code from:
- 🔴 Confusing & error-prone
- To 🟢 Crystal clear & validated

**Time per function:** ~2 minutes
**Total functions:** 252
**Estimated time:** ~8 hours
**Impact:** Code quality 6.4/10 → 10/10

Start with the **Priority Files** above for maximum impact!
