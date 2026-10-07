"""Offline guards for the repository-root Vercel frontend deployment."""

import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]


def test_vercel_build_is_repository_root_and_lockfile_based():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["installCommand"] == "cd frontend && npm ci"
    assert config["buildCommand"] == "cd frontend && npm run build"
    assert config["outputDirectory"] == "frontend/dist"
    assert (ROOT / "frontend/package-lock.json").is_file()


def test_vercel_api_proxy_precedes_spa_fallback_and_preserves_prefix():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    api_index = next(i for i, route in enumerate(config["rewrites"]) if route["source"] == "/api/:path*")
    fallback_index = next(i for i, route in enumerate(config["rewrites"]) if route["destination"] == "/index.html")
    destination = urlparse(config["rewrites"][api_index]["destination"])
    assert api_index < fallback_index
    assert destination.scheme == "https" and destination.netloc
    assert not destination.netloc.endswith(".railway.internal")
    assert destination.path == "/api/:path*"


def test_vercel_upload_excludes_private_runtime_and_large_artifacts():
    rules = set((ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines())
    assert {"backend/", "scripts/", "audit_outputs/", "backups/", ".env", "**/.env*", ".testdeps/", "data/", "*.zip"} <= rules


def test_vercel_upload_preserves_frontend_hook_and_contract_sources():
    rules = (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
    assert not any(rule in {"frontend/", "frontend/hooks/", "frontend/src/", "frontend/src/shared/contracts/"} for rule in rules)
    assert (ROOT / "frontend/hooks/index.ts").is_file()
    assert (ROOT / "frontend/src/shared/contracts/schemas/manifest.json").is_file()
