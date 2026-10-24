import json
from pathlib import Path

content = open("data/ilt/search_config.js", encoding="utf-8").read().strip()
prefix = "var textForPages ="
if content.startswith(prefix):
    js_str = content[len(prefix):].rstrip(";")
    pages_text = json.loads(js_str)
    
    out_dir = Path("data/ilt/pages_raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    for i, t in enumerate(pages_text, 1):
        clean_t = t.replace("\r\n", "\n").replace("\r", "\n")
        (out_dir / f"page_{i:03d}.txt").write_text(clean_t, encoding="utf-8")
        
    print(f"Exported {len(pages_text)} pages to data/ilt/pages_raw/")
