"""Synchronize and verify frontend runtime contracts from backend/json_schemas."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.contracts.schema_registry import SCHEMA_ROOT, iter_schema_entries, schema_sha256


TARGET = ROOT / "frontend" / "src" / "shared" / "contracts" / "schemas"
GENERATED_BANNER = "Generated file — do not edit manually"


def _compute_semantic_sha256(data: Dict[str, Any]) -> str:
    canonical = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def sync() -> Dict[str, Any]:
    """Update mode: copy frontend contracts from backend and generate manifest."""
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

    # Clean up obsolete schema files
    for old in TARGET.glob("*.schema.json"):
        if old.name not in expected_files:
            old.unlink()

    output = {
        "warning": GENERATED_BANNER,
        "generated_from": "backend/json_schemas/registry.json",
        "contracts": generated,
    }
    (TARGET / "manifest.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    readme_content = f"""<!-- {GENERATED_BANNER} -->
# Frontend Runtime Contracts (Generated)

> **WARNING**: {GENERATED_BANNER}.
> Source of truth: `backend/json_schemas/registry.json`.
> Run `python scripts/sync_json_schemas.py` to synchronize contracts.
"""
    (TARGET / "README.md").write_text(readme_content, encoding="utf-8")

    return output


def check_sync() -> int:
    """Check-only mode: detect contract drift without modifying any files.

    Returns 0 if perfectly synchronized, 1 if any drift is detected.
    """
    drift_issues: List[str] = []

    if not TARGET.is_dir():
        print(f"[DRIFT] Target directory does not exist: {TARGET}", file=sys.stderr)
        return 1

    expected_entries = list(iter_schema_entries(frontend_only=True))
    expected_filenames = {Path(e["file"]).name: e for e in expected_entries}

    # 1. Detect missing schemas
    for entry in expected_entries:
        filename = Path(entry["file"]).name
        target_file = TARGET / filename
        if not target_file.is_file():
            drift_issues.append(f"Missing schema: {filename} ({entry['schema_id']}@{entry['version']})")

    # 2. Detect surplus schemas
    for existing in TARGET.glob("*.schema.json"):
        if existing.name not in expected_filenames:
            drift_issues.append(f"Surplus schema found: {existing.name}")

    # 3. Detect checksum drift on existing files
    for filename, entry in expected_filenames.items():
        target_file = TARGET / filename
        if not target_file.is_file():
            continue
        try:
            raw = json.loads(target_file.read_text(encoding="utf-8"))
            actual_sha256 = _compute_semantic_sha256(raw)
            expected_sha256 = schema_sha256(entry["schema_id"], entry["version"])
            if actual_sha256 != expected_sha256:
                drift_issues.append(
                    f"Checksum drift for {filename}: expected {expected_sha256}, got {actual_sha256}"
                )
        except Exception as exc:
            drift_issues.append(f"Cannot parse target schema {filename}: {exc}")

    # 4. Detect manifest drift
    manifest_path = TARGET / "manifest.json"
    if not manifest_path.is_file():
        drift_issues.append("Missing manifest.json")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("generated_from") != "backend/json_schemas/registry.json":
                drift_issues.append(
                    f"Manifest generated_from mismatch: {manifest.get('generated_from')}"
                )

            manifest_contracts = manifest.get("contracts")
            if not isinstance(manifest_contracts, list):
                drift_issues.append("Manifest contracts field is not a list")
            else:
                contract_map = {c.get("schema_id"): c for c in manifest_contracts if isinstance(c, dict)}
                if len(contract_map) != len(expected_entries):
                    drift_issues.append(
                        f"Manifest contract count mismatch: expected {len(expected_entries)}, got {len(contract_map)}"
                    )

                for entry in expected_entries:
                    sid = entry["schema_id"]
                    if sid not in contract_map:
                        drift_issues.append(f"Manifest missing contract: {sid}")
                        continue
                    m_item = contract_map[sid]
                    if m_item.get("version") != entry["version"]:
                        drift_issues.append(f"Manifest version mismatch for {sid}: {m_item.get('version')} != {entry['version']}")
                    expected_fname = Path(entry["file"]).name
                    if m_item.get("file") != expected_fname:
                        drift_issues.append(f"Manifest filename mismatch for {sid}: {m_item.get('file')} != {expected_fname}")
                    expected_hash = schema_sha256(entry["schema_id"], entry["version"])
                    if m_item.get("sha256") != expected_hash:
                        drift_issues.append(f"Manifest sha256 mismatch for {sid}: {m_item.get('sha256')} != {expected_hash}")
        except Exception as exc:
            drift_issues.append(f"Cannot read or parse manifest.json: {exc}")

    if drift_issues:
        print(f"[CONTRACT DRIFT DETECTED] Found {len(drift_issues)} issue(s):", file=sys.stderr)
        for issue in drift_issues:
            print(f"  - {issue}", file=sys.stderr)
        print("\nRun 'python scripts/sync_json_schemas.py' to synchronize frontend contracts.", file=sys.stderr)
        return 1

    print(f"[CONTRACT SYNC OK] All {len(expected_entries)} frontend contracts and manifest are in sync.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize or check frontend JSON Schema contracts.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check for contract drift without creating, modifying, or deleting any files. Returns non-zero on drift.",
    )
    args = parser.parse_args()

    if args.check:
        return check_sync()

    result = sync()
    print(f"Synchronized {len(result['contracts'])} frontend JSON Schemas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
