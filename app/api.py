"""
api.py — Day 19: FastAPI serving endpoint (brief requirement: Streamlit
AND a REST API).

    GET /predict?lat=24.86&lon=67.01&city=Karachi
        -> full JSON forecast: current AQI + +24h/+48h/+72h, model
           provenance, and the exact feature vector.

    GET /health
        -> service + production-model status (used by Render uptime
           checks on Day 23).

    GET /cities
        -> the 10 training cities with coordinates (handy for clients
           to build a picker without hardcoding).

Reuses the EXACT same inference pipeline as the dashboard
(src.inference.predict.predict) — one code path for Streamlit, API,
and (later) the automation workflows. Errors become proper HTTP codes:
503 when no production model is registered, 400 on bad coordinates,
502 when the upstream data fetch fails.

Run locally:  uvicorn app.api:app --reload
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from src.config import CITIES
from src.inference.predict import predict
from src.training.model_registry import ModelRegistry
from src.utils.aqi_utils import aqi_category, health_message
from src.utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="AQI Predictor — Pakistan",
    description="Live air quality forecast (+24h/+48h/+72h) for any "
                "coordinates on Earth, served by a city-agnostic model "
                "trained on 10 Pakistani cities.",
    version="0.1.0",
)


@app.get("/health")
def health():
    """Service status + whether a production model is registered."""
    reg = ModelRegistry()
    prod = reg.production_entry()
    return {
        "status": "ok",
        "model": (
            {"name": prod["name"], "version": prod["version"]}
            if prod else None
        ),
    }


@app.get("/cities")
def cities():
    """The 10 training cities (name -> lat/lon)."""
    return {"cities": CITIES}


@app.get("/predict")
def predict_endpoint(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude"),
    city: str = Query("api", description="Display label for the location"),
):
    """
    Three-day AQI forecast for any coordinates.

    Returns the same payload the dashboard renders: current AQI,
    +24h/+48h/+72h forecast, model provenance, feature vector.
    """
    try:
        result = predict(lat, lon, city=city)
    except SystemExit as e:
        # No production model in the registry.
        raise HTTPException(
            status_code=503,
            detail=f"Model unavailable: {e}",
        )
    except (RuntimeError, KeyError, ValueError) as e:
        logger.error(f"/predict failed for ({lat}, {lon}): {e}")
        raise HTTPException(status_code=502, detail=str(e))

    # Enrich each horizon with its AQI band label + health message —
    # clients get presentation data without reimplementing EPA bands.
    for h in ("24", "48", "72"):
        aqi = result["forecast"][h]
        result["forecast"][h] = {
            "aqi": aqi,
            "category": aqi_category(aqi),
            "health_message": health_message(aqi),
        }
    result["current"] = {
        "aqi": result["current_aqi"],
        "category": aqi_category(result["current_aqi"]),
        "health_message": health_message(result["current_aqi"]),
    }
    return JSONResponse(content=result)
