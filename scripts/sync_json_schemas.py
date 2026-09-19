"""Synchronize frontend runtime contracts from backend/json_schemas."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.contracts.schema_registry import SCHEMA_ROOT, iter_schema_entries, schema_sha256


TARGET = ROOT / "frontend" / "src" / "shared" / "contracts" / "schemas"


def sync() -> dict:
    TARGET.mkdir(parents=True, exist_ok=True)
    expected_files = set()
    generated = []
    for entry in iter_schema_entries(frontend_only=True):
        source = SCHEMA_ROOT / entry["file"]
        target_name = Path(entry["file"]).name
        target = TARGET / target_name
        shutil.copyfile(source, target)
        expected_files.add(target_name)
        generated.append(
            {
                "schema_id": entry["schema_id"],
                "version": entry["version"],
                "file": target_name,
                "sha256": schema_sha256(entry["schema_id"], entry["version"]),
            }
        )

    for old in TARGET.glob("*.schema.json"):
        if old.name not in expected_files:
            old.unlink()

    output = {"generated_from": "backend/json_schemas/registry.json", "contracts": generated}
    (TARGET / "manifest.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    result = sync()
    print(f"Synchronized {len(result['contracts'])} frontend JSON Schemas.")
