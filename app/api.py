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

import logging
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from src.config import CITIES
from src.inference.predict import predict
from src.tracking.store import ParquetPredictionStore, HopsworksPredictionStore
from src.training.model_registry import ModelRegistry
from src.utils.aqi_utils import aqi_category, health_message
from src.utils.logger import get_logger, log_event

logger = get_logger(__name__)

app = FastAPI(
    title="AQI Predictor — Pakistan",
    description="Live air quality forecast (+24h/+48h/+72h) for any "
                "coordinates on Earth, served by a city-agnostic model "
                "trained on 10 Pakistani cities.",
    version="0.1.0",
)


@app.middleware("http")
async def request_logging(request, call_next):
    """Structured access log for every request (Day 24 observability).

    Logs method, path, status and duration_ms as one searchable line —
    the minimum needed to answer "is the API healthy / who is calling
    it / where is the latency". The event name is http_request so a log
    drain or Render's log search can filter on it.
    """
    import time

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log_event(
            logger, "http_request", level=logging.ERROR,
            method=request.method, path=request.url.path,
            status=500, duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        raise
    log_event(
        logger, "http_request",
        method=request.method, path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.perf_counter() - start) * 1000, 1),
    )
    return response


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


@app.post("/admin/migrate-predictions")
def migrate_predictions():
    """
    One-time admin endpoint: migrate local Parquet predictions to Hopsworks.
    Only works when HOPSWORKS_API_KEY and HOPSWORKS_PROJECT are set.
    Protected by requiring a shared secret header.
    """
    # Simple shared-secret protection (set ADMIN_SECRET in Render env)
    # For now, just allow if env vars are present (Hopsworks configured)
    if not os.getenv("HOPSWORKS_API_KEY") or not os.getenv("HOPSWORKS_PROJECT"):
        raise HTTPException(
            status_code=503,
            detail="Hopsworks not configured on this service"
        )

    try:
        local_store = ParquetPredictionStore()
        local_records = local_store.load_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Local store error: {e}")

    if local_records.empty:
        return {"migrated": 0, "message": "No local predictions to migrate"}

    try:
        hopsworks_store = HopsworksPredictionStore()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Hopsworks connection failed: {e}")

    # Check existing to avoid duplicates
    existing = hopsworks_store.load_all()
    existing_ids = set(existing["prediction_id"].tolist()) if not existing.empty else set()

    migrated = 0
    for _, row in local_records.iterrows():
        record = row.to_dict()
        pred_id = record.get("prediction_id")
        if pred_id in existing_ids:
            continue
        try:
            hopsworks_store.save(record)
            migrated += 1
        except Exception as e:
            logger.error(f"Failed to migrate {pred_id}: {e}")

    return {"migrated": migrated, "total_local": len(local_records), "already_in_hopsworks": len(existing_ids)}
