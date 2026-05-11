import asyncio
# pyrefly: ignore [missing-import]
from motor.motor_asyncio import AsyncIOMotorClient
import json

async def main():
    client = AsyncIOMotorClient("mongodb+srv://smtnayem:smtnayemproject@cluster0.p87lrd6.mongodb.net/jimgreen?appName=Cluster0")
    db = client.get_database("jimgreen")
    col = db.get_collection("saturation_runs")
    doc = await col.find_one({}, sort=[("_id", -1)])
    if doc and "grid_results" in doc and doc["grid_results"]:
        # Print just the first element of grid_results
        print(json.dumps(doc["grid_results"][0], default=str, indent=2))
    else:
        print("No document found or grid_results is empty")

asyncio.run(main())
