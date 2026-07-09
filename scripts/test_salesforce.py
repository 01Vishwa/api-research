import asyncio
import json
import os
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.researcher import research_app
from agents.verifier import verify_app

async def main():
    # Simulate Salesforce (App ID 1)
    app_id = 1
    app_name = "Salesforce"
    category = "CRM and Sales"
    hint_url = "https://developer.salesforce.com/docs/apis"
    
    print(f"Researching {app_name}...")
    rec1 = research_app(app_id, app_name, category, hint_url)
    
    with open("salesforce_pass1.json", "w", encoding="utf-8") as f:
        json.dump(rec1.model_dump(), f, indent=2, default=str)
    
    print(f"Verifying {app_name}...")
    rec2, log = verify_app(rec1)
    
    with open("salesforce_pass2.json", "w", encoding="utf-8") as f:
        json.dump(rec2.model_dump(), f, indent=2, default=str)
        
    print("Done! Wrote to salesforce_pass1.json and salesforce_pass2.json")

if __name__ == "__main__":
    asyncio.run(main())
