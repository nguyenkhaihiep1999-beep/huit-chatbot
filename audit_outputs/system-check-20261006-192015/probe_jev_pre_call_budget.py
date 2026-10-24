"""Read-only application-source diagnostic using existing offline test fixtures.

No real HTTP or Mongo transports are allowed by the fixture. The provider runs
against MockTransport, and all user content is synthetic. This script does not
modify application source, test source, database records or the running server.
"""

import json
import time

import pytest

from backend.tests import test_jev_assist_mode_chat as fixture
from backend.app.decision_engine import service as service_module


def main():
    with pytest.MonkeyPatch.context() as monkeypatch:
        setup = fixture.assist_chat.__wrapped__(monkeypatch)
        install, _, _ = next(setup)
        try:
            _, provider_requests = install()
            monkeypatch.setenv("JEV_TOTAL_BUDGET_MS", "100")
            original_run = service_module.run_coro_sync

            def simulate_queue_delay(coro, *args, **kwargs):
                # Inject bounded scheduling delay after the absolute deadline
                # is created, before the existing sync worker starts.
                time.sleep(0.065)
                return original_run(coro, *args, **kwargs)

            monkeypatch.setattr(service_module, "run_coro_sync", simulate_queue_delay)
            telemetry = []
            original_log = fixture.pipeline.log_decision_application

            def capture_application(*args, **kwargs):
                payload = original_log(*args, **kwargs)
                telemetry.append(payload)
                return payload

            monkeypatch.setattr(fixture.pipeline, "log_decision_application", capture_application)
            fixture.run_chat(use_cache=False)
            intent = next(item for item in telemetry if item["decision_type"] == "intent")
            print(json.dumps({
                "probe": "budget_exhausted_before_provider",
                "mode": "offline_mock_no_http_or_database",
                "configured_total_budget_ms": 100,
                "injected_queue_delay_ms": 65,
                "provider_requests_observed": len(provider_requests),
                "pipeline_api_called": intent["api_called"],
                "apply_reason": intent["apply_reason"],
                "decision_applied": intent["decision_applied"],
                "chat_completed": True,
                "flag_matches_observed_provider_calls": intent["api_called"] == bool(provider_requests),
            }, ensure_ascii=False))
        finally:
            try:
                next(setup)
            except StopIteration:
                pass


if __name__ == "__main__":
    main()
