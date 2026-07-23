from dotenv import load_dotenv
load_dotenv()
import os
import requests
import pandas as pd
from datetime import datetime

token = os.getenv("AQICN_TOKEN")

url = f"https://api.waqi.info/feed/A545320/?token={token}"
response = requests.get(url).json()

timestamp = response["data"]["time"]["s"]
dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")

row = {
    "Location": response["data"]["city"]["name"],
    "timestamp": timestamp,
    "hour": dt.hour,
    "day": dt.day,
    "month": dt.month,
    "aqi": response["data"]["aqi"]
}

# Add all pollutants automatically
for pollutant, value in response["data"]["iaqi"].items():
    row[pollutant] = value["v"]

filename = "aqi_dataset.csv"

# -------------------------
# Load Existing Dataset
# -------------------------
if os.path.exists(filename):
    df = pd.read_csv(filename)
else:
    df = pd.DataFrame()


new_row = pd.DataFrame([row])
df = pd.concat([df, new_row], ignore_index=True)

# -------------------------
# Feature Engineering
# -------------------------
df["prev_aqi"] = df["aqi"].shift(1)
df["aqi_change_rate"] = df["aqi"] - df["prev_aqi"]

# Optional: Make first row values 0 instead of NaN
df["prev_aqi"] = df["prev_aqi"].fillna(0)
df["aqi_change_rate"] = df["aqi_change_rate"].fillna(0)

# -------------------------
# Save Dataset
# -------------------------
df.to_csv(filename, index=False)

print("Data added successfully!\n")

print(df.tail())