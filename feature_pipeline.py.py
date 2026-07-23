from dotenv import load_dotenv
load_dotenv()
import os,requests,csv
from datetime import datetime

token = os.getenv("AQICN_TOKEN")
url = f"https://api.waqi.info/feed/A545320/?token={token}"
response = requests.get(url).json()

timestamp = response["data"]["time"]["s"]
dt = datetime.strptime(timestamp,"%Y-%m-%d %H:%M:%S")

row={
    "timestamp": timestamp,
    "aqi": response["data"]["aqi"],
    "pm25": response["data"]["iaqi"]["pm25"]["v"],
    "pm10": response["data"]["iaqi"]["pm10"]["v"],
    "hour": dt.hour,
    "day": dt.day,
    "month": dt.month,
}

filename = "aqi_dataset.csv"

file_exists = os.path.exists(filename)
with open(filename, "a", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=row.keys())

    if not file_exists:
        writer.writeheader()

    writer.writerow(row)

print("Data saved successfully!")
print(row)