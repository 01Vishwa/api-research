import json
import asyncio
from pathlib import Path
from pipeline.runner import run_pipeline
from config import APPS_JSON_PATH

if __name__ == "__main__":
    with open(APPS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # keep only Salesforce and HubSpot
    test_data = [d for d in data if d["app"] in ("Salesforce", "HubSpot")]
    
    with open("data/test_apps.json", "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2)

    import pipeline.runner
    pipeline.runner.APPS_JSON_PATH = Path("data/test_apps.json")
    
    run_pipeline(force=True, auto=True, skip_insights=True)
