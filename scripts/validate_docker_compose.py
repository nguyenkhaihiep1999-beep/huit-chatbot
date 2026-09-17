"""
Docker Compose Configuration Validation Gate
Validates both standard and production Docker Compose specifications.
Outputs machine-readable evidence: audit_outputs/docker_compose_validation.json
Exits with code 0 if all configurations validate successfully, code 1 otherwise.
"""

import os
import json
import subprocess
from datetime import datetime, timezone

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_PATH = os.path.join(WORKSPACE, "audit_outputs", "docker_compose_validation.json")

def run_compose_validation():
    results = {}
    all_passed = True

    # Dummy env for production compose validation
    env_vars = os.environ.copy()
    env_vars.update({
        "MONGODB_URI": "mongodb+srv://placeholder_user:placeholder_pass@cluster0.example.net/huit_chatbot?retryWrites=true&w=majority",
        "REDIS_PASSWORD": "test_redis_password_secure_123",
        "ADMIN_USERNAME": "admin_test",
        "ADMIN_PASSWORD": "test_admin_password_secure_123",
        "ADMIN_TOKEN": "test_admin_token_abcdef1234567890",
        "CORS_ALLOWED_ORIGINS": "https://chatbot.huit.edu.vn",
    })

    targets = [
        {"name": "dev_compose", "file": "docker-compose.yml", "env_file": ".env.example"},
        {"name": "prod_compose", "file": "docker-compose.prod.yml", "custom_env": True},
    ]

    for target in targets:
        cmd = ["docker", "compose", "-f", target["file"]]
        if "env_file" in target:
            cmd.extend(["--env-file", target["env_file"]])
        cmd.append("config")

        try:
            res = subprocess.run(
                cmd,
                cwd=WORKSPACE,
                capture_output=True,
                text=True,
                env=env_vars if target.get("custom_env") else os.environ,
                check=False
            )
            passed = (res.returncode == 0)
            if not passed:
                all_passed = False

            results[target["name"]] = {
                "file": target["file"],
                "exit_code": res.returncode,
                "passed": passed,
                "stdout_sample": res.stdout[:500] if passed else "",
                "stderr": res.stderr if not passed else "",
            }
        except Exception as e:
            all_passed = False
            results[target["name"]] = {
                "file": target["file"],
                "exit_code": -1,
                "passed": False,
                "error": str(e),
            }

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workspace": WORKSPACE,
        "status": "PASSED" if all_passed else "FAILED",
        "targets": results,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)

    print(f"Docker compose validation completed: {'PASSED (GO)' if all_passed else 'FAILED (NO-GO)'}")
    print(f"Report saved to: {OUTPUT_PATH}")

    return 0 if all_passed else 1

if __name__ == "__main__":
    exit(run_compose_validation())
