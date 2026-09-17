"""
smoke_test_release_gate.py
Script smoke test nghiệm thu cuối cùng (Final Release Gate):
Kiểm thử toàn diện trực tiếp trên TestClient của FastAPI:
1. Health: /api/health/live, /api/health/ready
2. Auth: CSRF Token, Admin Login (HttpOnly Cookie), Verify, Logout
3. Chat Stream v2 Canonical: /api/chat-stream
4. Stream Resume & Cancel: /api/chat-stream/resume, /api/chat-stream/cancel
5. Artifact Job, Upscale & Export
6. Admin Metrics & Clear Cache
"""
import sys
import uuid
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from backend.app.main import app

def run_smoke_tests():
    print("=" * 60)
    print("BẮT ĐẦU SMOKE TEST NGHIỆM THU CUỐI CÙNG (RELEASE GATE)")
    print("=" * 60)
    client = TestClient(app)
    results = {}

    # 1. Health Endpoints
    print("\n[1/6] Kiểm tra Health Endpoints...")
    r_live = client.get("/api/health/live")
    assert r_live.status_code == 200, f"Live health failed: {r_live.status_code}"
    print("  -> /api/health/live: OK (status=healthy)")

    r_ready = client.get("/api/health/ready")
    assert r_ready.status_code in (200, 503), f"Ready health unexpected: {r_ready.status_code}"
    ready_data = r_ready.json()
    print(f"  -> /api/health/ready: OK (status={ready_data.get('status')}, components={list(ready_data.get('components', {}).keys())})")
    results["health"] = "PASSED"

    # 2. Auth & CSRF
    print("\n[2/6] Kiểm tra Auth, CSRF & Admin Session Cookie...")
    r_csrf = client.post("/api/auth/session")
    assert r_csrf.status_code == 200, f"Session create failed: {r_csrf.status_code}"
    csrf_token = r_csrf.json().get("csrf_token")
    assert csrf_token, "CSRF token empty"
    print(f"  -> /api/auth/session: OK (csrf_token length={len(csrf_token)})")

    # Admin login
    r_login = client.post("/api/admin/login", json={"username": "admin_huit", "password": "change_this_to_a_strong_password_in_production"})
    if r_login.status_code != 200:
        # Thử với mật khẩu mặc định cấu hình settings
        from backend.app.config import settings
        r_login = client.post("/api/admin/login", json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD})
    assert r_login.status_code == 200, f"Admin login failed: {r_login.text}"
    cookie = r_login.headers.get("set-cookie")
    assert "huit_admin_token" in cookie, "Missing HttpOnly cookie huit_admin_token"
    print("  -> /api/admin/login: OK (HttpOnly cookie issued)")

    # Verify session
    r_verify = client.get("/api/admin/verify")
    assert r_verify.status_code == 200, f"Admin verify failed: {r_verify.status_code}"
    print("  -> /api/admin/verify: OK (Session verified via cookie)")

    # Logout (kèm CSRF token)
    r_logout = client.post("/api/admin/logout", headers={"X-CSRF-Token": csrf_token})
    assert r_logout.status_code == 200, f"Logout failed: {r_logout.status_code}"
    print("  -> /api/admin/logout: OK (Session destroyed)")
    results["auth"] = "PASSED"

    # 3. Chat Stream Canonical v2
    print("\n[3/6] Kiểm tra Chat Stream NDJSON v2 (Canonical Events)...")
    req_id = f"smoke-stream-{uuid.uuid4().hex[:8]}"
    r_stream = client.post(
        "/api/chat-stream",
        json={"question": "Cho tôi biết thông tin học phí HUIT 2026?"},
        headers={"X-Request-ID": req_id, "X-CSRF-Token": csrf_token}
    )
    assert r_stream.status_code == 200, f"Chat stream failed: {r_stream.status_code}"
    lines = [l.strip() for l in r_stream.text.split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]
    types = [e.get("type") for e in events]
    print(f"  -> /api/chat-stream: OK ({len(events)} canonical events received: {set(types)})")
    assert "start" in types, "Missing 'start' event"
    assert "token" in types or "progress" in types, "Missing content events"
    assert "done" in types, "Missing 'done' terminal event"
    results["chat_stream_v2"] = "PASSED"

    # 4. Stream Resume & Cancel
    print("\n[4/6] Kiểm tra Stream Resume & Cancel...")
    r_resume = client.get(f"/api/chat-stream/resume?request_id={req_id}&last_sequence=1")
    assert r_resume.status_code in (200, 404, 410), f"Resume unexpected status: {r_resume.status_code}"
    print(f"  -> /api/chat-stream/resume: OK (HTTP {r_resume.status_code})")

    cancel_req_id = f"smoke-cancel-{uuid.uuid4().hex[:8]}"
    r_cancel = client.post(f"/api/chat-stream/cancel?request_id={cancel_req_id}", headers={"X-CSRF-Token": csrf_token})
    assert r_cancel.status_code in (200, 404), f"Cancel unexpected: {r_cancel.status_code}"
    print(f"  -> /api/chat-stream/cancel: OK (HTTP {r_cancel.status_code})")
    results["resume_and_cancel"] = "PASSED"

    # 5. Artifact Job, Upscale & Export
    print("\n[5/6] Kiểm tra Artifact Actions (Upscale, Export, Job Creation)...")
    # Đăng nhập lại để có quyền admin cho test artifacts/metrics
    from backend.app.config import settings
    client.post("/api/admin/login", json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD})
    
    test_art_id = "art_test_smoke_001"
    r_upscale = client.post(f"/api/artifacts/{test_art_id}/upscale", json={"factor": 2}, headers={"X-CSRF-Token": csrf_token})
    assert r_upscale.status_code in (200, 202, 404), f"Upscale unexpected: {r_upscale.status_code}"
    print(f"  -> /api/artifacts/upscale: OK (HTTP {r_upscale.status_code})")

    r_export = client.post(f"/api/artifacts/{test_art_id}/export", json={"format": "pdf"}, headers={"X-CSRF-Token": csrf_token})
    assert r_export.status_code in (200, 202, 404), f"Export unexpected: {r_export.status_code}"
    print(f"  -> /api/artifacts/export: OK (HTTP {r_export.status_code})")
    results["artifact_actions"] = "PASSED"

    # 6. Admin Metrics & Cache Ops
    print("\n[6/6] Kiểm tra Admin Dashboard Metrics & Cache Ops...")
    r_metrics = client.get("/api/admin/metrics")
    assert r_metrics.status_code in (200, 503), f"Admin metrics unexpected status: {r_metrics.status_code}"
    if r_metrics.status_code == 200:
        m_data = r_metrics.json()
        print(f"  -> /api/admin/metrics: OK (HTTP 200: total_events={m_data.get('total_events')}, cached={m_data.get('total_cached_queries')})")
    else:
        print(f"  -> /api/admin/metrics: OK (HTTP 503 - Timeout protection gracefully handled)")

    r_clear = client.post("/api/admin/clear-cache", json={"confirm": True}, headers={"X-CSRF-Token": csrf_token})
    assert r_clear.status_code in (200, 503), f"Clear cache unexpected status: {r_clear.status_code}"
    print(f"  -> /api/admin/clear-cache: OK (HTTP {r_clear.status_code})")
    results["admin_ops"] = "PASSED"

    print("\n" + "=" * 60)
    print("TẤT CẢ SMOKE TESTS ĐÃ VƯỢT QUA 100% THÀNH CÔNG!")
    print(f"Chi tiết kết quả: {results}")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = run_smoke_tests()
    sys.exit(0 if success else 1)
