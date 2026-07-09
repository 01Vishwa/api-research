import json

with open("output/pass2_verified.json", "r", encoding="utf-8") as f:
    pass2_data = json.load(f)

# Ensure it's a list
if isinstance(pass2_data, dict):
    pass2_data = list(pass2_data.values())

with open("salesforce_pass1.json", "r", encoding="utf-8") as f:
    sf = json.load(f)

with open("hubspot_pass2.json", "r", encoding="utf-8") as f:
    hs = json.load(f)

# Remove existing if present
pass2_data = [r for r in pass2_data if r["id"] not in (1, 2)]

pass2_data.append(sf)
pass2_data.append(hs)

with open("output/pass2_verified.json", "w", encoding="utf-8") as f:
    json.dump(pass2_data, f, indent=2, default=str)
    
print("Updated pass2_verified.json")
