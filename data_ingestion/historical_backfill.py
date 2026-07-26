import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry
from datetime import date

cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

LATITUDE = 24.8608
LONGITUDE = 67.0104
START_DATE = "2022-08-06"
END_DATE = date.today().isoformat()  #fetches up to "today" when you run it, Dynamic END_DATE

# AQI + pollutant data
aqi_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
aqi_params = {
    "latitude": LATITUDE,
    "longitude": LONGITUDE,
    "hourly": ["us_aqi", "pm10", "pm2_5", "carbon_monoxide",
               "nitrogen_dioxide", "sulphur_dioxide", "ozone"],
    "start_date": START_DATE,
    "end_date": END_DATE,
}
aqi_response = openmeteo.weather_api(aqi_url, params=aqi_params)[0]
aqi_hourly = aqi_response.Hourly()

aqi_data = {
    "date": pd.date_range(
        start=pd.to_datetime(aqi_hourly.Time(), unit="s", utc=True),
        end=pd.to_datetime(aqi_hourly.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=aqi_hourly.Interval()),
        inclusive="left",
    ),
    "us_aqi": aqi_hourly.Variables(0).ValuesAsNumpy(),
    "pm_10": aqi_hourly.Variables(1).ValuesAsNumpy(),
    "pm_25": aqi_hourly.Variables(2).ValuesAsNumpy(),
    "co": aqi_hourly.Variables(3).ValuesAsNumpy(),
    "no2": aqi_hourly.Variables(4).ValuesAsNumpy(),
    "so2": aqi_hourly.Variables(5).ValuesAsNumpy(),
    "o3": aqi_hourly.Variables(6).ValuesAsNumpy(),
}
aqi_df = pd.DataFrame(data=aqi_data)


# temperature data
temp_url = "https://archive-api.open-meteo.com/v1/archive"
temp_params = {
    "latitude": LATITUDE,
    "longitude": LONGITUDE,
    "start_date": START_DATE,
    "end_date": END_DATE,
    "hourly": "temperature_2m",
}
temp_response = openmeteo.weather_api(temp_url, params=temp_params)[0]
temp_hourly = temp_response.Hourly()

temp_data = {
    "date": pd.date_range(
        start=pd.to_datetime(temp_hourly.Time(), unit="s", utc=True),
        end=pd.to_datetime(temp_hourly.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=temp_hourly.Interval()),
        inclusive="left",
    ),
    "temp": temp_hourly.Variables(0).ValuesAsNumpy(),
}
temp_df = pd.DataFrame(data=temp_data)


merged_df = pd.merge(aqi_df, temp_df, on="date", how="inner")
merged_df = merged_df[["date", "us_aqi", "temp", "pm_10", "pm_25", "co", "no2", "so2", "o3"]]

print(merged_df.head())
print(f"\nTotal rows: {len(merged_df)}")
print(f"Date range: {merged_df['date'].min()} to {merged_df['date'].max()}")

merged_df.to_csv("historical_data.csv", index=False, header=True)
print("\nSaved to historical_data.csv")