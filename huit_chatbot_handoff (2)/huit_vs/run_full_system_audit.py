#!/usr/bin/env python3
"""Comprehensive System Audit Script for HUIT AI Chatbot."""
import os
import sys
import json

# Force UTF-8 stdout on Windows
sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

print("=== STARTING FULL SYSTEM AUDIT ===")

# 1. Check .env file
env_file = os.path.join(HERE, ".env")
if os.path.exists(env_file):
    print("[OK] .env file exists")
    with open(env_file, encoding="utf-8") as f:
        content = f.read()
        if "MONGODB_PASSWORD" in content:
            print("  - MONGODB_PASSWORD configured")
        if "OPENROUTER_API_KEY" in content:
            print("  - OPENROUTER_API_KEY configured")
else:
    print("[FAIL] .env file MISSING!")

# 2. Test RAG Core & MongoDB Connection
try:
    import rag_core
    print("\n--- Testing MongoDB Connection & Vector Search ---")
    docs = rag_core.retrieve("Học phí K26 HUIT", top_k=3)
    print(f"[OK] Retrieved {len(docs)} docs from MongoDB huit_kb")
    for i, d in enumerate(docs, 1):
        print(f"  Doc #{i}: Title='{d.get('title')}', Score={round(d.get('score', 0), 4)}, URL='{d.get('url')}'")
except Exception as e:
    print("[FAIL] RAG Core retrieve error:", e)

# 3. Test Full RAG Answer Generation
try:
    print("\n--- Testing Full RAG Answer Pipeline ---")
    res = rag_core.answer("Học phí HUIT 2026 khoảng bao nhiêu?")
    print("[OK] Answer generated successfully:")
    print("  Answer snippet:", res.get("answer", "")[:150], "...")
    print("  Sources count:", len(res.get("sources", [])))
except Exception as e:
    print("[FAIL] RAG Core answer error:", e)

# 4. Check Frontend Static Assets
robot_img = os.path.join(HERE, "static", "robot_huit.png")
index_html = os.path.join(HERE, "static", "index.html")
if os.path.exists(robot_img):
    print(f"\n[OK] Mascot robot image exists ({os.path.getsize(robot_img)} bytes)")
else:
    print("\n[FAIL] Mascot robot image MISSING!")

if os.path.exists(index_html):
    print(f"[OK] static/index.html exists ({os.path.getsize(index_html)} bytes)")
else:
    print("[FAIL] static/index.html MISSING!")

# 5. Check MCP Server Script
mcp_script = os.path.join(HERE, "mcp_server.py")
if os.path.exists(mcp_script):
    print(f"[OK] mcp_server.py exists ({os.path.getsize(mcp_script)} bytes)")
else:
    print("[FAIL] mcp_server.py MISSING!")

print("\n=== SYSTEM AUDIT COMPLETED ===")
