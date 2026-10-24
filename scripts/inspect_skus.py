import re
import json
from pathlib import Path

pages_dir = Path("data/ilt/pages_raw")
pages = sorted(list(pages_dir.glob("page_*.txt")))

sku_pattern = re.compile(r'\b([A-Z0-9]{3,4}-[A-Z0-9]{3,7}-[A-Z0-9\-]+)\b')
all_skus = []
sku_by_page = {}

for p in pages:
    page_num = int(p.stem.split("_")[1])
    text = p.read_text(encoding="utf-8")
    matches = sku_pattern.findall(text)
    # Deduplicate while preserving order
    unique_skus = []
    for m in matches:
        # Clean up any trailing dashes or whitespace
        clean_m = m.strip("- ")
        if clean_m not in unique_skus:
            unique_skus.append(clean_m)
    if unique_skus:
        sku_by_page[page_num] = unique_skus
        all_skus.extend(unique_skus)

print(f"Total unique SKUs found: {len(set(all_skus))}")
print(f"Total pages with SKUs: {len(sku_by_page)}/135")
print("\nSample SKU mapping (first 10 pages with SKUs):")
for p_num in sorted(sku_by_page.keys())[:10]:
    print(f"  Page {p_num}: {sku_by_page[p_num]}")
