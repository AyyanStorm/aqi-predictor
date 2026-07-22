# import requests                 #For api calling
# from dotenv import load_dotenv  #For fetching token from .env
# import os
# load_dotenv()
#
# token = os.getenv("AQICN_TOKEN")
#
# url = f"https://api.waqi.info/feed/A545320/?token={token}"
#
# response=requests.get(url).json() # json for dictionary type output
# print(response.keys())

import requests
from dotenv import load_dotenv
import os

load_dotenv()

token = os.getenv("AQICN_TOKEN")

url = f"https://api.waqi.info/feed/A545320/?token={token}"

response = requests.get(url).json()

# Step 1
all_data = response["data"]["aqi"]

aqi_data = response["data"]["city"]["location"]
time =  response["data"]["time"]["s"]


print(f"AQI: {all_data}")

# Step 2
#print(response["data"].keys())

# Step 3
print(f"Location: {response["data"]["city"]["location"]}")

# Step 4
# print(response["data"]["iaqi"])

# Step 5
# print(response["data"]["time"])



