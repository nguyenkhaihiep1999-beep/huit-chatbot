# HUIT Chatbot Data Mining & MongoDB Aggregation Suite
# Auto-generated Kaggle Pipeline for HUIT Admission Data

import os
import json
import pandas as pd

print("=== HUIT ADMISSION DATA PIPELINE & MONGODB AGGREGATIONS ===")

# 1. Load HUIT Dataset
df = pd.read_csv('/kaggle/input/huit-admissions-kb/huit_admissions_kb.csv')
print(f"Loaded {len(df)} admission documents from Kaggle Dataset.")
print("Sample Titles:")
print(df[['id', 'title']].head())

# 2. Categorize HUIT Data
print("\nCategorizing HUIT Data...")
categories = {
    'Hoc phi': df[df['content_markdown'].str.contains('hoc phi|tien hoc|le phi', case=False, na=False)],
    'Diem chuan': df[df['content_markdown'].str.contains('diem chuan|diem san', case=False, na=False)],
    'Hoc bong': df[df['content_markdown'].str.contains('hoc bong|khuyen hoc', case=False, na=False)],
    'Nganh dao tao': df[df['content_markdown'].str.contains('nganh|ky thuat', case=False, na=False)]
}

for cat, sub_df in categories.items():
    print(f"  - [{cat}]: {len(sub_df)} documents")

print("\n[SUCCESS] Kaggle HUIT Admission Pipeline Execution Completed!")
