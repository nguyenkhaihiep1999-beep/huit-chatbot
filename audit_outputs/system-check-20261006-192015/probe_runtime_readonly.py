"""Bounded, read-only runtime probes; never print credentials or raw errors."""

import json
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus
from urllib.request import urlopen

import pymongo

from backend.app.config import settings


def main():
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_http_liveness_and_direct_mongo_ping_no_application_audit",
        "configuration_from_current_files_not_running_process": {
            "environment": settings.APP_ENV,
            "jev_mode": settings.JEV_MODE,
            "jev_model": settings.JEV_MODEL,
            "jev_key_present": bool(settings.TYPESAFE_API_KEY),
            "redis_configured": bool(settings.REDIS_URL or settings.RATE_LIMIT_REDIS_URL or settings.STREAM_RESUME_REDIS_URL),
            "local_embeddings_enabled": settings.ENABLE_LOCAL_EMBEDDINGS,
        },
    }
    for label, url in (
        ("backend_liveness", "http://127.0.0.1:8000/health/live"),
        ("frontend_dev_port_3000", "http://127.0.0.1:3000/"),
    ):
        try:
            with urlopen(url, timeout=3) as response:
                result[label] = {"status": "reachable", "http_status": response.status}
        except Exception as exc:
            result[label] = {"status": "not_confirmed", "error_type": type(exc).__name__}

    uri = settings.MONGODB_URI
    if not uri and settings.MONGODB_PASSWORD:
        uri = (
            f"mongodb+srv://{settings.MONGODB_USER}:"
            f"{quote_plus(settings.MONGODB_PASSWORD)}@{settings.MONGODB_HOST}/?appName=Cluster0"
        )
    client = None
    start = time.perf_counter()
    try:
        if not uri:
            result["mongodb_ping"] = {"status": "not_configured"}
        else:
            with pymongo.timeout(5):
                client = pymongo.MongoClient(
                    uri,
                    serverSelectionTimeoutMS=4000,
                    connectTimeoutMS=3000,
                    socketTimeoutMS=3000,
                )
                client.admin.command("ping")
            result["mongodb_ping"] = {
                "status": "reachable",
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                "database_queries_or_writes_performed": False,
            }
    except Exception as exc:
        result["mongodb_ping"] = {"status": "not_confirmed", "error_type": type(exc).__name__}
    finally:
        if client is not None:
            client.close()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
