"""
Response schemas for API documentation (Pydantic models).

Automatically generates OpenAPI/Swagger schema with proper type hints,
examples, and descriptions for all API endpoints.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class AQIReading(BaseModel):
    """Single AQI reading with EPA category and health guidance."""
    aqi: float = Field(
        ...,
        description="Air Quality Index (0-500+)",
        examples=[45.5, 87.2, 125.0]
    )
    category: str = Field(
        ...,
        description="EPA AQI category (Good, Moderate, Unhealthy for Sensitive Groups, Unhealthy, Very Unhealthy, Hazardous)",
        examples=["Good", "Moderate", "Unhealthy"]
    )
    health_message: str = Field(
        ...,
        description="Health guideline message for the AQI category",
        examples=[
            "Air quality is satisfactory, and air pollution poses little or no risk.",
            "Members of sensitive groups may experience health effects.",
            "Everyone may begin to experience health effects."
        ]
    )

    class Config:
        json_schema_extra = {
            "example": {
                "aqi": 65.5,
                "category": "Moderate",
                "health_message": "Members of sensitive groups may experience health effects."
            }
        }


class Forecast(BaseModel):
    """24/48/72-hour AQI forecast with categories."""
    h24: AQIReading = Field(
        ...,
        description="Air quality forecast for 24 hours ahead",
        alias="24"
    )
    h48: AQIReading = Field(
        ...,
        description="Air quality forecast for 48 hours ahead",
        alias="48"
    )
    h72: AQIReading = Field(
        ...,
        description="Air quality forecast for 72 hours ahead",
        alias="72"
    )

    class Config:
        allow_population_by_field_name = True
        json_schema_extra = {
            "example": {
                "24": {
                    "aqi": 72.0,
                    "category": "Moderate",
                    "health_message": "Members of sensitive groups may experience health effects."
                },
                "48": {
                    "aqi": 58.5,
                    "category": "Moderate",
                    "health_message": "Members of sensitive groups may experience health effects."
                },
                "72": {
                    "aqi": 51.2,
                    "category": "Good",
                    "health_message": "Air quality is satisfactory, and air pollution poses little or no risk."
                }
            }
        }


class FeatureVector(BaseModel):
    """Input features used for the prediction."""
    description: Optional[str] = Field(
        None,
        description="Description of feature vector (e.g., observation time)"
    )
    values: Optional[Dict[str, Any]] = Field(
        None,
        description="Named feature values used in model inference"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "description": "Features at 2026-09-01 07:30 UTC",
                "values": {
                    "temperature_2m": 28.5,
                    "relative_humidity_2m": 65.0,
                    "precipitation": 0.0,
                    "wind_speed_10m": 8.5,
                    "surface_pressure": 1013.25
                }
            }
        }


class ModelProvenance(BaseModel):
    """Production model metadata and performance info."""
    name: str = Field(
        ...,
        description="Model name/identifier",
        examples=["aqi-lgbm-v3", "production-model"]
    )
    version: int = Field(
        ...,
        description="Model version number",
        examples=[3, 5, 10]
    )
    rmse: Optional[float] = Field(
        None,
        description="Root Mean Squared Error on test set",
        examples=[15.5, 12.3]
    )
    accuracy: Optional[float] = Field(
        None,
        description="Classification accuracy on test set (0-100%)",
        examples=[85.5, 92.1]
    )
    training_date: Optional[str] = Field(
        None,
        description="ISO 8601 timestamp when model was trained",
        examples=["2026-08-25T10:30:00Z"]
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "aqi-lgbm-v3",
                "version": 3,
                "rmse": 15.5,
                "accuracy": 87.2,
                "training_date": "2026-08-25T10:30:00Z"
            }
        }


class PredictionResponse(BaseModel):
    """Complete AQI forecast response with metadata."""
    current: AQIReading = Field(
        ...,
        description="Current air quality index"
    )
    forecast: Dict[str, AQIReading] = Field(
        ...,
        description="3-day forecast (24/48/72 hour ahead)"
    )
    model: Optional[ModelProvenance] = Field(
        None,
        description="Production model metadata"
    )
    status: str = Field(
        default="ok",
        description="Response status (ok, degraded)",
        examples=["ok", "degraded"]
    )
    request_id: str = Field(
        ...,
        description="Unique request identifier for debugging",
        examples=["a1b2c3d4"]
    )
    latency_ms: float = Field(
        ...,
        description="Server processing time in milliseconds",
        examples=[45.2, 123.5]
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 timestamp of prediction",
        examples=["2026-09-01T07:30:00Z"]
    )
    feature_vector: Optional[FeatureVector] = Field(
        None,
        description="Input features used for prediction"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "current": {
                    "aqi": 68.5,
                    "category": "Moderate",
                    "health_message": "Members of sensitive groups may experience health effects."
                },
                "forecast": {
                    "24": {
                        "aqi": 72.0,
                        "category": "Moderate",
                        "health_message": "Members of sensitive groups may experience health effects."
                    },
                    "48": {
                        "aqi": 58.5,
                        "category": "Moderate",
                        "health_message": "Members of sensitive groups may experience health effects."
                    },
                    "72": {
                        "aqi": 51.2,
                        "category": "Good",
                        "health_message": "Air quality is satisfactory, and air pollution poses little or no risk."
                    }
                },
                "model": {
                    "name": "aqi-lgbm-v3",
                    "version": 3,
                    "rmse": 15.5,
                    "accuracy": 87.2,
                    "training_date": "2026-08-25T10:30:00Z"
                },
                "status": "ok",
                "request_id": "a1b2c3d4",
                "latency_ms": 45.2,
                "timestamp": "2026-09-01T07:30:00Z"
            }
        }


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(
        ...,
        description="Error type/title",
        examples=["Invalid coordinates", "Model service unavailable"]
    )
    details: Optional[str] = Field(
        None,
        description="Detailed error explanation"
    )
    request_id: str = Field(
        ...,
        description="Unique request ID for debugging"
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 timestamp when error occurred"
    )
    retry_after: Optional[int] = Field(
        None,
        description="Recommended seconds to wait before retrying (HTTP 503 only)"
    )
    support: Optional[str] = Field(
        None,
        description="Support contact information"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error": "Model service unavailable",
                "details": "No production model is registered",
                "request_id": "a1b2c3d4",
                "timestamp": "2026-09-01T07:30:00Z",
                "retry_after": 300,
                "support": "Contact support with request_id: a1b2c3d4"
            }
        }


class HealthResponse(BaseModel):
    """Service health status."""
    status: str = Field(
        ...,
        description="Service status",
        examples=["ok", "degraded"]
    )
    model: Optional[Dict[str, Any]] = Field(
        None,
        description="Production model info (name, version)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "ok",
                "model": {
                    "name": "aqi-lgbm-v3",
                    "version": 3
                }
            }
        }


class CityInfo(BaseModel):
    """Training city information."""
    name: str = Field(
        ...,
        description="City name",
        examples=["Karachi", "Lahore", "Islamabad"]
    )
    latitude: float = Field(
        ...,
        description="Geographic latitude",
        examples=[24.86, 31.54]
    )
    longitude: float = Field(
        ...,
        description="Geographic longitude",
        examples=[67.01, 74.32]
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Karachi",
                "latitude": 24.86,
                "longitude": 67.01
            }
        }


class CitiesResponse(BaseModel):
    """List of training cities."""
    cities: Dict[str, CityInfo] = Field(
        ...,
        description="Map of city names to their coordinates"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "cities": {
                    "Karachi": {
                        "name": "Karachi",
                        "latitude": 24.86,
                        "longitude": 67.01
                    },
                    "Lahore": {
                        "name": "Lahore",
                        "latitude": 31.54,
                        "longitude": 74.32
                    }
                }
            }
        }


class MigrationResponse(BaseModel):
    """Response from prediction migration endpoint."""
    migrated: int = Field(
        ...,
        description="Number of records migrated",
        examples=[150, 42]
    )
    total_local: int = Field(
        ...,
        description="Total records in local store",
        examples=[150, 500]
    )
    already_in_hopsworks: int = Field(
        ...,
        description="Records already in Hopsworks (skipped)",
        examples=[0, 50]
    )
    message: Optional[str] = Field(
        None,
        description="Status message",
        examples=["Migration complete", "No local predictions to migrate"]
    )

    class Config:
        json_schema_extra = {
            "example": {
                "migrated": 150,
                "total_local": 150,
                "already_in_hopsworks": 0,
                "message": "Migration complete"
            }
        }
