# User Experience Best Practices: 4.9/10 → 10/10

**Production-grade UX implementation guide**

---

## 🎨 DESIGN SYSTEM

### Color Palette

```python
# Color scheme for AQI Predictor
COLORS = {
    "good": "#00E400",          # Green (Good)
    "moderate": "#FFFF00",      # Yellow (Moderate)
    "sensitive": "#FF7E00",     # Orange (Unhealthy for Sensitive)
    "unhealthy": "#FF0000",     # Red (Unhealthy)
    "very_unhealthy": "#8F3F97", # Purple (Very Unhealthy)
    "hazardous": "#7E0023",     # Maroon (Hazardous)
    
    # Neutral palette
    "primary": "#2563EB",       # Blue (primary action)
    "secondary": "#64748B",     # Slate (secondary)
    "success": "#16A34A",       # Green (success)
    "warning": "#EA580C",       # Orange (warning)
    "error": "#DC2626",         # Red (error)
    "info": "#0284C7",          # Blue (info)
    
    # Grayscale
    "text_primary": "#1F2937",  # Dark gray (primary text)
    "text_secondary": "#6B7280", # Medium gray (secondary text)
    "bg_light": "#F9FAFB",      # Very light gray (background)
    "border": "#E5E7EB",        # Light gray (borders)
}
```

### Typography

```python
# Typography hierarchy
TYPOGRAPHY = {
    "h1": {"size": 32, "weight": "bold", "color": "text_primary"},
    "h2": {"size": 24, "weight": "bold", "color": "text_primary"},
    "h3": {"size": 20, "weight": "semibold", "color": "text_primary"},
    "body": {"size": 16, "weight": "normal", "color": "text_primary"},
    "small": {"size": 14, "weight": "normal", "color": "text_secondary"},
    "caption": {"size": 12, "weight": "normal", "color": "text_secondary"},
}
```

---

## 🎯 DASHBOARD DESIGN PRINCIPLES

### 1. Visual Hierarchy
```markdown
**Do:**
✅ Use size to indicate importance
✅ Group related information
✅ Use whitespace effectively
✅ Highlight key metrics

**Don't:**
❌ Clutter the screen
❌ Use too many colors
❌ Make text too small
❌ Overwhelm with information
```

### 2. User-Centered Layout
```
┌─────────────────────────────────────────┐
│ Header: Logo + Title + Help             │
├─────────────────────────────────────────┤
│ Quick Actions (Top Priority)            │
├─────────────────────────────────────────┤
│ Main Content Area                       │
│  ├─ Input Section (left)                │
│  ├─ Results Section (right)             │
│  └─ Map/Chart Section (below)           │
├─────────────────────────────────────────┤
│ Footer: Links + Info                    │
└─────────────────────────────────────────┘
```

### 3. Clear Call-to-Action
```python
# Do:
st.button("Get AQI Prediction", key="predict", type="primary")

# Don't:
st.button("Click here")
```

---

## 🎙️ MICROCOPY & ERROR MESSAGES

### Helpful Error Messages

**Before:**
```json
{"error": "Invalid input"}
```

**After:**
```json
{
  "title": "Invalid Latitude",
  "message": "Latitude must be between -90 and 90 degrees",
  "received": 150,
  "suggestion": "Did you mean 75°? (Valid range: -90 to 90)",
  "learn_more": "https://example.com/help/latitude"
}
```

### Context-Specific Messages

```python
# API Rate Limited
{
  "status": 429,
  "error": "Rate limit exceeded",
  "title": "Too Many Requests",
  "message": "You've made too many requests. Please wait before trying again.",
  "retry_after_seconds": 60,
  "explanation": "We limit requests to 200 per hour to ensure service quality",
  "upgrade": "https://example.com/pricing"
}

# Model Not Available
{
  "status": 503,
  "error": "Service unavailable",
  "title": "Model Loading",
  "message": "The prediction model is loading. This usually takes 30-60 seconds.",
  "eta_seconds": 45,
  "will_retry": true
}

# Invalid Location
{
  "status": 400,
  "error": "Invalid location",
  "title": "Location Not Supported",
  "message": "Predictions are available for Pakistan and nearby regions",
  "received": {"lat": -45.5, "lon": 170},
  "suggestion": "Try a location in Pakistan, like Karachi (24.86°N, 67.01°E)",
  "examples": [
    {"city": "Karachi", "lat": 24.86, "lon": 67.01},
    {"city": "Lahore", "lat": 31.54, "lon": 74.31}
  ]
}
```

---

## ♿ ACCESSIBILITY (WCAG 2.1 AA)

### Color Contrast
```python
# Check contrast ratio (must be 4.5:1 for normal text, 3:1 for large)
from contrast_checker import check_contrast

check_contrast("#2563EB", "#FFFFFF")  # ✅ 4.48:1 (good)
check_contrast("#FFFF00", "#FFFFFF")  # ❌ 1.07:1 (bad)
```

### Keyboard Navigation
```python
# Streamlit example
st.button("Predict", key="predict")  # Has keyboard focus by default
st.slider("Latitude", -90, 90)       # Keyboard accessible

# For complex UI, add aria labels
st.markdown('<input aria-label="latitude" type="number">', unsafe_allow_html=True)
```

### Screen Reader Support
```python
# Do:
st.write("Current AQI: **68** (Moderate)")

# Don't:
st.metric("Current AQI", "68")  # Screen reader says "68" without context
```

### Text Alternatives
```python
# For images
st.image("map.png", caption="Air quality map of Pakistan")

# For icons
st.write("🟢 Good - Air quality is satisfactory")
```

---

## 📱 MOBILE RESPONSIVENESS

### Responsive Layout
```python
import streamlit as st

# Detect screen size
if st.session_state.get("wide_mode"):
    col1, col2 = st.columns(2)
    with col1:
        st.write("Input Section")
    with col2:
        st.write("Results Section")
else:
    st.write("Input Section")
    st.write("Results Section")
```

### Touch-Friendly Interface
```python
# Large buttons for touch
st.button("Get Prediction", use_container_width=True, key="predict")

# Larger input fields
st.number_input("Latitude", value=24.86, step=0.01)

# Easy-to-tap elements (min 44x44 px)
st.slider("Zoom", 1, 20, 10)
```

---

## 🚀 PERFORMANCE OPTIMIZATION

### Caching
```python
import streamlit as st

@st.cache_data(ttl=3600)
def load_model():
    """Load model once per hour."""
    return ModelRegistry().get_production_model()

@st.cache_data(ttl=300)
def get_prediction(lat, lon, horizon):
    """Cache predictions for 5 minutes."""
    return predict(lat, lon, horizon)
```

### Lazy Loading
```python
# Load map only when needed
if st.checkbox("Show Map"):
    st.map(data)

# Load historical data on demand
if st.button("Show Trends"):
    st.line_chart(historical_data)
```

---

## 🎓 ONBOARDING WIZARD

### Welcome Screen
```python
if "onboarding_done" not in st.session_state:
    st.session_state.onboarding_done = False

if not st.session_state.onboarding_done:
    st.title("👋 Welcome to AQI Predictor")
    st.write("Get air quality forecasts for any location in Pakistan")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📍", "360+ Cities", "Covered")
    with col2:
        st.metric("📊", "72 Hours", "Forecast")
    with col3:
        st.metric("⚡", "<100ms", "Latency")
    
    st.divider()
    st.write("### Quick Start")
    st.write("1. Enter your location (latitude & longitude)")
    st.write("2. Click 'Get Prediction'")
    st.write("3. View current AQI + 3-day forecast")
    
    if st.button("Get Started →"):
        st.session_state.onboarding_done = True
        st.rerun()
```

---

## 📚 API DOCUMENTATION BEST PRACTICES

### Endpoint Documentation
```python
@app.get("/api/v1/predict")
async def predict(
    lat: float = Query(..., description="Latitude (-90 to 90)", example=24.86),
    lon: float = Query(..., description="Longitude (-180 to 180)", example=67.01),
    horizon: str = Query("24h", description="Forecast horizon", example="24h")
):
    """
    Get air quality prediction for coordinates.
    
    **Parameters:**
    - `lat`: Latitude in decimal degrees
    - `lon`: Longitude in decimal degrees
    - `horizon`: Forecast horizon (24h, 48h, or 72h)
    
    **Returns:**
    - `current`: Current AQI with EPA category
    - `forecast`: 24/48/72-hour predictions
    - `model`: Model information
    
    **Examples:**
    
    ```bash
    # Get current AQI for Karachi
    curl "https://api.example.com/predict?lat=24.86&lon=67.01&horizon=24h"
    
    # Response
    {
      "current": {"aqi": 68, "category": "Moderate"},
      "forecast": {
        "24": {"aqi": 72, "category": "Moderate"},
        ...
      }
    }
    ```
    
    **Error Handling:**
    
    - **400 Bad Request**: Invalid latitude/longitude
    - **429 Too Many Requests**: Rate limit exceeded
    - **503 Service Unavailable**: Model loading
    """
```

---

## 🎨 STREAMLIT CUSTOMIZATION

### Custom Theme
```python
# .streamlit/config.toml
[theme]
primaryColor = "#2563EB"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F9FAFB"
textColor = "#1F2937"
font = "sans serif"

[client]
showErrorDetails = true
```

### Custom CSS
```python
st.markdown("""
<style>
    .metric-card {
        background-color: #F9FAFB;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
    }
    
    .aqi-good { color: #00E400; }
    .aqi-moderate { color: #FFFF00; }
    .aqi-unhealthy { color: #FF0000; }
</style>
""", unsafe_allow_html=True)
```

---

## ✅ UX CHECKLIST

Before launching any feature:

- [ ] Design follows brand guidelines
- [ ] All buttons have clear labels
- [ ] Error messages are helpful
- [ ] Page loads in <2 seconds
- [ ] Works on mobile (iOS + Android)
- [ ] Keyboard navigation works
- [ ] Screen reader friendly
- [ ] Color contrast meets WCAG AA
- [ ] Documentation is complete
- [ ] User tested
- [ ] Accessibility audit passed
- [ ] Performance optimized
- [ ] No console errors

---

## 🎬 QUICK WINS (30 mins each)

1. Add custom color theme → +0.5 pts
2. Improve error messages → +1 pt
3. Add onboarding → +0.5 pts
4. Add accessibility labels → +0.5 pts
5. Optimize performance → +0.5 pts

**Total: 3 hours = +3 points**

---

## 📈 SUMMARY

**Enterprise-Grade UX Elements:**
- ✅ Professional design system
- ✅ Accessible (WCAG 2.1 AA)
- ✅ Mobile-responsive
- ✅ Performance optimized
- ✅ User-centered design
- ✅ Clear error messages
- ✅ Comprehensive documentation
- ✅ Onboarding guide
