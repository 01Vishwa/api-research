import asyncio
import json
import os
import sys
import time

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.verifier import verify_app
from models.schema import AppRecord

async def main():
    app_id = 2
    app_name = "HubSpot"
    
    with open("output/raw_pass1.json", "r", encoding="utf-8") as f:
        pass1_data = json.load(f)
        
    hubspot_data = next(r for r in pass1_data if r["id"] == app_id)
    rec1 = AppRecord(**hubspot_data)
    
    print(f"Verifying {app_name}...")
    start_time = time.time()
    rec2, log = verify_app(rec1)
    end_time = time.time()
    
    with open("hubspot_pass2.json", "w", encoding="utf-8") as f:
        json.dump(rec2.model_dump(), f, indent=2, default=str)
        
    print(f"Verification completed in {end_time - start_time:.2f} seconds.")
    print("Done! Wrote to hubspot_pass2.json")

if __name__ == "__main__":
    asyncio.run(main())
