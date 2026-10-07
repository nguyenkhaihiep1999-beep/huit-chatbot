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
    "temp",
    "scratch",
    "test-results",
}
EXCLUDE_FILES = {".env", "secret_scan_report.json"}
PLACEHOLDER_SUBSTRINGS = [
    "<",
    ">",
    "your_",
    "example",
    "placeholder",
    "change_this",
    "dummy_",
    "test_",
    "test_token",
    "secret_token_here",
]
# Quy tắc thu hẹp cho placeholder chứa 'xxx':
# Chỉ coi là placeholder khi chuỗi chứa mặt nạ lặp tối thiểu 6 ký tự 'x' (ví dụ: xxxxxxxx, sk-xxxx...).
# Chuỗi khóa lạ chứa substring 'xxx' ngẫu nhiên (ví dụ: sk-live_key_xxx...)
# tuyệt đối không được coi là placeholder và bắt buộc phải bị phát hiện là rò rỉ thực (CRITICAL).
PLACEHOLDER_REGEXES = [
    re.compile(r"x{6,}", re.IGNORECASE),
]

# Quy tắc allowlist hẹp cho dữ liệu giả (synthetic fixtures) phục vụ kiểm thử và benchmark cơ chế khử khuẩn (redaction / PII).
# Ràng buộc nghiêm ngặt:
# 1. Tuyệt đối không wildcard toàn bộ thư mục hoặc toàn bộ file.
# 2. File được định tuyến chính xác theo đường dẫn tương đối (chuẩn hóa gạch chéo '/').
# 3. Loại secret pattern (type) phải khớp chính xác.
# 4. Giá trị chuỗi phải khớp chính xác (exact_value) hoặc tiền tố giả định hẹp (exact_prefix).
# 5. Mỗi quy tắc có mã ID và giải trình lý do rõ ràng.
NARROW_SYNTHETIC_ALLOWLIST = [
    {
        "id": "SYNTH-DECISION-OPENAI-KEY",
        "file": "backend/tests/test_decision_engine.py",
        "type": "OPENAI_LIKE_KEY",
        "exact_value": "sk-" + "1234567890abcdef123456",
        "reason": "Synthetic fixture for testing redact_text() OpenAI-like key sanitization in test_06_redaction",
    },
    {
        "id": "SYNTH-DECISION-MONGO-AUTH",
        "file": "backend/tests/test_decision_engine.py",
        "type": "MONGODB_AUTH",
        "exact_prefix": "mongodb+srv://" + "admin:pass123@",
        "reason": "Synthetic fixture for testing redact_text() MongoDB credentials sanitization in test_06_redaction",
    },
    {
        "id": "SYNTH-BENCH-JEV-OPENAI-KEY",
        "file": "scripts/benchmark_jev_shadow_staging.py",
        "type": "OPENAI_LIKE_KEY",
        "exact_value": "sk-" + "1234567890abcdef123456",
        "reason": "Synthetic fixture for testing shadow staging privacy redaction benchmark case pii_04",
    },
    {
        "id": "SYNTH-BENCH-JEV-MONGO-AUTH",
        "file": "scripts/benchmark_jev_shadow_staging.py",
        "type": "MONGODB_AUTH",
        "exact_prefix": "mongodb+srv://" + "staging_user:pass987@",
        "reason": "Synthetic fixture for testing shadow staging MongoDB credentials redaction benchmark case pii_04",
    },
]

def hash_mask(val: str) -> str:
    h = hashlib.sha256(val.encode("utf-8")).hexdigest()[:8]
    return f"[LEN={len(val)}, SHA256={h}]"

def is_placeholder(val: str) -> bool:
    v_lower = val.lower()
    if any(p in v_lower for p in PLACEHOLDER_SUBSTRINGS):
        return True
    if any(rx.search(v_lower) for rx in PLACEHOLDER_REGEXES):
        return True
    return False

def check_synthetic_allowlist(rel_path: str, p_name: str, matched_val: str):
    """Kiểm tra đối chiếu với danh sách quy tắc allowlist hẹp cho dữ liệu giả."""
    norm_path = rel_path.replace("\\", "/")
    for rule in NARROW_SYNTHETIC_ALLOWLIST:
        if rule["file"] == norm_path and rule["type"] == p_name:
            if "exact_value" in rule and matched_val == rule["exact_value"]:
                return True, rule["id"], rule["reason"]
            if "exact_prefix" in rule and matched_val.startswith(rule["exact_prefix"]):
                return True, rule["id"], rule["reason"]
    return False, None, None

def run_scan(workspace: str = WORKSPACE, output_path: str = OUTPUT_PATH):
    findings = []
    scanned_files = 0
    scanned_extensions = set()

    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".system_generated")]
        for file in files:
            if file in EXCLUDE_FILES or file.endswith(".pyc") or file.endswith(".log"):
                continue
            
            # Skip binary and heavy media files
            ext = os.path.splitext(file)[1].lower()
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".zip", ".tar", ".gz"}:
                continue

            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, workspace)

            # Skip audit_outputs existing historical reports if needed, but scan all source code
            norm_rel_path = rel_path.replace("\\", "/")
            if norm_rel_path.startswith("audit_outputs/") and (norm_rel_path.endswith(".json") or norm_rel_path.endswith(".xml")):
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
                        is_synth, rule_id, synth_reason = check_synthetic_allowlist(rel_path, p_name, matched_val)

                        severity = "LOW" if placeholder else ("INFO" if is_synth else "CRITICAL")
                        findings.append({
                            "file": norm_rel_path,
                            "line": line_idx,
                            "type": p_name,
                            "masked": hash_mask(matched_val),
                            "is_placeholder": placeholder,
                            "is_synthetic_fixture": is_synth,
                            "allowlist_rule_id": rule_id,
                            "severity": severity,
                        })

    real_leaks = [f for f in findings if not f["is_placeholder"] and not f.get("is_synthetic_fixture")]
    allowlisted_fixtures = [f for f in findings if f.get("is_synthetic_fixture")]
    passed = len(real_leaks) == 0

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workspace": workspace,
        "scanned_files_count": scanned_files,
        "scanned_extensions": sorted(list(scanned_extensions)),
        "total_matches": len(findings),
        "placeholders_count": len([f for f in findings if f["is_placeholder"]]),
        "allowlisted_fixtures_count": len(allowlisted_fixtures),
        "real_leaks_count": len(real_leaks),
        "status": "PASSED" if passed else "FAILED",
        "real_leaks": real_leaks,
        "allowlisted_fixtures_summary": [
            {
                "file": f["file"],
                "line": f["line"],
                "type": f["type"],
                "masked": f["masked"],
                "rule_id": f["allowlist_rule_id"],
            }
            for f in allowlisted_fixtures
        ],
        "placeholder_matches_sample": [f for f in findings if f["is_placeholder"]][:10]
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)

    print(f"Secret scan completed.")
    print(f"Scanned files: {scanned_files}")
    print(f"Total findings: {len(findings)} (Placeholders: {len([f for f in findings if f['is_placeholder']])}, Synthetic fixtures allowlisted: {len(allowlisted_fixtures)}, Real leaks: {len(real_leaks)})")
    print(f"Status: {'PASSED (GO)' if passed else 'FAILED (NO-GO)'}")
    print(f"Report saved to: {output_path}")

    return 0 if passed else 1

if __name__ == "__main__":
    exit(run_scan())
