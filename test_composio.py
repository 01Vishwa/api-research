import os
from dotenv import load_dotenv
load_dotenv(".env")
from composio import Composio
c = Composio(api_key=os.getenv("COMPOSIO_API_KEY"))
try:
    tools = c.tools.get(user_id=os.getenv("COMPOSIO_USER_ID", "default"), apps=['composio'])
    print("apps=['composio']", type(tools), tools)
except Exception as e:
    print(e)
    
try:
    tools = c.tools.get(toolkits=['composio_search'])
    print("toolkits=['composio_search']", type(tools), tools)
except Exception as e:
    print(e)
