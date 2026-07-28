# AQI Predictor

Predicts Air Quality Index (AQI) for any city in Pakistan up to 3 days ahead, using historical pollutant and weather data, an automated ML pipeline, and a location-aware dashboard.

🚧 In development — 10Pearls Data Science Internship Project

## Why not just predict AQI from same-hour pollutant readings?

Open-Meteo's `us_aqi` value isn't independently measured — it's calculated directly from the same-hour pollutant concentrations (PM2.5, PM10, CO, NO2, SO2, O3) using a fixed public EPA formula. Training a model to predict `us_aqi` from those same pollutants at the same timestamp isn't learning a pattern — it's just re-deriving a known formula, and it would score close to 100% accuracy while being useless in practice. This project instead predicts AQI 24-72 hours *ahead*, using only data that would genuinely be available at prediction time: past pollutant history and forecasted weather, never the target hour's own pollutant readings.