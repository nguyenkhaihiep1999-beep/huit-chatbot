import json
import re

content = open("data/ilt/catalog_config.js", encoding="utf-8").read().strip()
prefix = "var htmlConfig ="
if content.startswith(prefix):
    js_str = content[len(prefix):].rstrip(";")
    data = json.loads(js_str)
    # Search for image paths in aliasConfig or elsewhere
    print("aliasConfig:", data.get("aliasConfig"))
    print("slider:", data.get("slider"))
    print("pageEditor sample:", json.dumps(data.get("pageEditor", [])[:3], indent=2))
