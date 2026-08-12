"""
tracking/ — AQI prediction tracking + accuracy (Day 24 scope).

Records every generated prediction (per-browser user, any city) so the
dashboard can later compare predicted AQI against observed AQI from
Open-Meteo's archive, then show accuracy. All decisions from grill-me:
  - accuracy formula: Option C (MAPE headline + ±15 tolerance hit-rate
    + EPA category-match as supporting stats)
  - actuals: fetched RETROACTIVELY from Open-Meteo at view time (no
    background collection)
  - storage: Hopsworks aqi_predictions feature group when available,
    Parquet fallback otherwise (same adapter pattern as feature_store)
  - tracking: AUTOMATIC — every generated prediction is saved
  - identity: per-browser anonymous ID (cookie, fallback session)
"""
