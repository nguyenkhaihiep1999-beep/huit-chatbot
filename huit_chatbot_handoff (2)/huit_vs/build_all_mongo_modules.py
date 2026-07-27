#!/usr/bin/env python3
"""Validate, export, and optionally register HUIT aggregation modules.

This command never executes an aggregation pipeline. Registration only upserts
JSON module definitions into ``code_modules``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

from mongo_module_library import MODULES, export_module_files
from mongo_safe_runner import validate_module


HERE = Path(__file__).resolve().parent
USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DATABASE = "huit_chatbot"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def load_password() -> str:
    password = os.environ.get("MONGODB_PASSWORD", "").strip()
    env_file = HERE / ".env"
    if not password and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("MONGODB_PASSWORD="):
                password = line.split("=", 1)[1].strip().strip("\"'")
                break
    if not password:
        raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")
    return password


def register_modules() -> tuple[int, int, int]:
    from pymongo import MongoClient

    uri = (
        f"mongodb+srv://{USER}:{quote_plus(load_password())}@{HOST}/"
        "?retryWrites=true&w=majority&appName=Cluster0"
    )
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    collection = client[DATABASE]["code_modules"]
    for item in MODULES:
        collection.replace_one({"_id": item["_id"]}, item, upsert=True)
    ids = [item["_id"] for item in MODULES]
    stored = collection.count_documents({"_id": {"$in": ids}})
    writes = collection.count_documents({
        "_id": {"$in": ids},
        "risk_level": "write",
    })
    return len(MODULES), stored, writes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--register",
        action="store_true",
        help="Upsert module definitions into MongoDB; does not execute them.",
    )
    parser.add_argument(
        "--output",
        default=str(HERE / "mongo_modules"),
        help="Directory receiving one JSON file per module.",
    )
    args = parser.parse_args()

    ids: set[str] = set()
    for item in MODULES:
        validate_module(item)
        if item["_id"] in ids:
            raise RuntimeError(f"Trùng module ID: {item['_id']}")
        ids.add(item["_id"])

    exported = export_module_files(args.output)
    reads = sum(item["risk_level"] == "read" for item in MODULES)
    writes = exported - reads
    print(f"[OK] validated={exported} read={reads} write={writes}")
    print(f"[OK] exported={Path(args.output).resolve()}")

    if args.register:
        requested, stored, writes = register_modules()
        print(
            f"[OK] requested={requested} verified_stored={stored} "
            f"write_modules={writes} collection=code_modules"
        )
    else:
        print("[SAFE] Chưa ghi MongoDB. Dùng --register để đăng ký module.")


if __name__ == "__main__":
    main()
