"""
Secret Scan Quality Gate
Scans source files in the repository for leaked API keys, tokens, hardcoded passwords, or database URIs.
Produces machine-readable JSON output: audit_outputs/secret_scan_report.json
Exits with code 0 if no unmasked real credentials found, code 1 otherwise.
"""

import os
import re
import json
import hashlib
from datetime import datetime, timezone

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_PATH = os.path.join(WORKSPACE, "audit_outputs", "secret_scan_report.json")

PATTERNS = {
    "MONGODB_AUTH": re.compile(r"mongodb(\+srv)?://([^:\s\'\"<>{}]+):([^@\s\'\"<>{}]+)@"),
    "GOOGLE_API_KEY": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "GROQ_API_KEY": re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    "OPENROUTER_API_KEY": re.compile(r"sk-or-v1-[0-9A-Za-z]{20,}"),
    "OPENAI_LIKE_KEY": re.compile(r"sk-[0-9A-Za-z]{20,}"),
    "GITHUB_TOKEN": re.compile(r"(?:ghp_|github_pat_)[0-9A-Za-z_]{20,}"),
    "VERCEL_TOKEN": re.compile(r"(?:vercel_token\s*=\s*[\'\"][0-9A-Za-z_]{16,}[\'\"])|(?:vercel_[0-9a-zA-Z]{24,})"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
}

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    ".testdeps",
    "__pycache__",
    "dist",
    "build",
    "coverage",
    ".pytest_cache",
    ".pytest_temp",
}
EXCLUDE_FILES = {".env", "secret_scan_report.json"}
PLACEHOLDER_SUBSTRINGS = ["<", ">", "your_", "example", "placeholder", "xxx", "change_this", "dummy_", "test_", "test_token", "secret_token_here"]

def hash_mask(val: str) -> str:
    h = hashlib.sha256(val.encode("utf-8")).hexdigest()[:8]
    return f"[LEN={len(val)}, SHA256={h}]"

def is_placeholder(val: str) -> bool:
    v_lower = val.lower()
    return any(p in v_lower for p in PLACEHOLDER_SUBSTRINGS)

def run_scan():
    findings = []
    scanned_files = 0
    scanned_extensions = set()

    for root, dirs, files in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".system_generated")]
        for file in files:
            if file in EXCLUDE_FILES or file.endswith(".pyc") or file.endswith(".log"):
                continue
            
            # Skip binary and heavy media files
            ext = os.path.splitext(file)[1].lower()
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".zip", ".tar", ".gz"}:
                continue

            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, WORKSPACE)

            # Skip audit_outputs existing historical reports if needed, but scan all source code
            if rel_path.startswith("audit_outputs") and (rel_path.endswith(".json") or rel_path.endswith(".xml")):
                continue

            scanned_files += 1
            scanned_extensions.add(ext)

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                    lines = fp.readlines()
            except Exception:
                continue

            for line_idx, line in enumerate(lines, start=1):
                for p_name, regex in PATTERNS.items():
                    for match in regex.finditer(line):
                        matched_val = match.group(0)
                        placeholder = is_placeholder(matched_val)
                        # We only fail on non-placeholder secrets
                        findings.append({
                            "file": rel_path.replace("\\", "/"),
                            "line": line_idx,
                            "type": p_name,
                            "masked": hash_mask(matched_val),
                            "is_placeholder": placeholder,
                            "severity": "LOW" if placeholder else "CRITICAL",
                        })

    real_leaks = [f for f in findings if not f["is_placeholder"]]
    passed = len(real_leaks) == 0

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workspace": WORKSPACE,
        "scanned_files_count": scanned_files,
        "scanned_extensions": sorted(list(scanned_extensions)),
        "total_matches": len(findings),
        "placeholders_count": len(findings) - len(real_leaks),
        "real_leaks_count": len(real_leaks),
        "status": "PASSED" if passed else "FAILED",
        "real_leaks": real_leaks,
        "placeholder_matches_sample": [f for f in findings if f["is_placeholder"]][:10]
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)

    print(f"Secret scan completed.")
    print(f"Scanned files: {scanned_files}")
    print(f"Total findings: {len(findings)} (Placeholders: {len(findings) - len(real_leaks)}, Real leaks: {len(real_leaks)})")
    print(f"Status: {'PASSED (GO)' if passed else 'FAILED (NO-GO)'}")
    print(f"Report saved to: {OUTPUT_PATH}")

    return 0 if passed else 1

if __name__ == "__main__":
    exit(run_scan())
