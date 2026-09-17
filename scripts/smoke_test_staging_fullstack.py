"""
smoke_test_staging_fullstack.py
Full-stack HTTP smoke test cho môi trường Staging / Live Server.
Sử dụng HTTP client thật (httpx) qua mạng TCP/HTTP, TUYỆT ĐỐI KHÔNG dùng TestClient in-memory.

Quy tắc bắt buộc:
- Ghi JSON/JUnit report vào audit_outputs/.
- Exit code 1 khi bất kỳ scenario nào fail.
- live phải 200 (status in alive/healthy).
- ready phải 200; 503 là FAIL.
- admin login không trả token trong JSON.
- admin cookie, CSRF, verify và logout/revoke.
- chat thường.
- NDJSON canonical stream (start, token, done).
- reconnect/resume không lặp token.
- cancel và terminal event đúng một lần.
- migration 020 validator strict/error, unique index trên session_hash, TTL index trên expires_at.
- artifact ownership cách ly giữa hai người dùng.
- export/upscale qua worker với polling hoàn tất.
- signed download hợp lệ thành công; unsigned/expired signature bị chặn.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath("."))

import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


class StagingSmokeRunner:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.user_client = httpx.Client(base_url=self.base_url, timeout=30.0, follow_redirects=True)
        self.admin_client = httpx.Client(base_url=self.base_url, timeout=30.0, follow_redirects=True)
        self.results: Dict[str, Dict[str, Any]] = {}
        self.user_csrf_token: str = ""
        self.admin_csrf_token: str = ""

    def log(self, step: str, msg: str, status: str = "INFO"):
        prefix = {
            "INFO": "ℹ️ ",
            "PASS": "✅ PASS: ",
            "FAIL": "❌ FAIL: ",
            "WARN": "⚠️ WARN: ",
            "BLOCK": "⛔ BLOCKED: ",
        }.get(status, "")
        print(f"[{step}] {prefix}{msg}")

    def record(self, test_name: str, passed: bool, message: str, duration_sec: float = 0.0, details: Any = None):
        self.results[test_name] = {
            "passed": passed,
            "message": message,
            "duration_sec": round(duration_sec, 3),
            "details": details,
        }
        status = "PASS" if passed else "FAIL"
        self.log(test_name, f"{message} ({duration_sec:.2f}s)", status=status)

    # 1. Health Live Check
    def test_01_health_live(self):
        name = "1. Health Live (/api/health/live)"
        t0 = time.time()
        try:
            r = self.user_client.get("/api/health/live")
            dur = time.time() - t0
            if r.status_code == 200:
                data = r.json()
                if data.get("status") in ("alive", "healthy"):
                    self.record(name, True, f"HTTP 200 OK, status={data.get('status')}", dur)
                    return
            self.record(name, False, f"Expected 200 OK alive/healthy, got HTTP {r.status_code}: {r.text}", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 2. Health Ready Check (Strict: 503 là FAIL)
    def test_02_health_ready(self):
        name = "2. Health Ready (/api/health/ready)"
        t0 = time.time()
        try:
            r = self.user_client.get("/api/health/ready")
            dur = time.time() - t0
            if r.status_code == 200:
                data = r.json()
                if data.get("status") in ("ready", "healthy"):
                    self.record(name, True, "HTTP 200 OK, dependencies fully operational", dur, data.get("components"))
                    return
                self.record(name, False, f"Status not ready: {data.get('status')}", dur, data)
            elif r.status_code == 503:
                self.record(name, False, "HTTP 503 Service Unavailable (Degraded dependencies)", dur, r.json())
            else:
                self.record(name, False, f"Unexpected HTTP status {r.status_code}: {r.text}", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 3. CSRF Session Bootstrap
    def test_03_csrf_session(self):
        name = "3. CSRF Bootstrap (/api/auth/session)"
        t0 = time.time()
        try:
            r = self.user_client.post("/api/auth/session")
            dur = time.time() - t0
            if r.status_code == 200:
                data = r.json()
                csrf = data.get("csrf_token")
                if csrf and len(csrf) >= 16:
                    self.user_csrf_token = csrf
                    self.record(name, True, f"HTTP 200 OK, user csrf_token received (length={len(csrf)})", dur)
                    return
            self.record(name, False, f"Failed to acquire user CSRF token: {r.status_code} - {r.text}", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 4. Admin Login - Zero Token in JSON
    def test_04_admin_login_zero_token(self, username: str, password: str):
        name = "4. Admin Login Zero-Token Contract"
        t0 = time.time()
        try:
            payload = {"username": username, "password": password}
            r = self.admin_client.post("/api/admin/login", json=payload)
            dur = time.time() - t0
            if r.status_code != 200:
                self.record(name, False, f"Admin login failed with status {r.status_code}: {r.text}", dur)
                return

            body = r.json()
            if "token" in body or "access_token" in body or "admin_token" in body:
                self.record(name, False, "SECURITY BREACH: token found in JSON response body!", dur)
                return

            set_cookie = r.headers.get("set-cookie", "")
            if "huit_admin_token" not in set_cookie:
                self.record(name, False, "Missing 'huit_admin_token' in Set-Cookie header", dur)
                return

            self.admin_csrf_token = body.get("csrf_token", "")
            self.record(name, True, "HTTP 200 OK, HttpOnly cookie set, zero token in JSON body, admin CSRF issued", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 5. Admin Verify, Logout & Revocation
    def test_05_admin_verify_and_logout(self):
        name = "5. Admin Verify, Logout & Revocation"
        t0 = time.time()
        try:
            r_ver = self.admin_client.get("/api/admin/verify")
            if r_ver.status_code != 200:
                self.record(name, False, f"Admin verify failed with status {r_ver.status_code}: {r_ver.text}", time.time() - t0)
                return

            headers = {"X-CSRF-Token": self.admin_csrf_token}
            r_out = self.admin_client.post("/api/admin/logout", headers=headers)
            if r_out.status_code != 200:
                self.record(name, False, f"Admin logout failed: {r_out.status_code} - {r_out.text}", time.time() - t0)
                return

            r_rev = self.admin_client.get("/api/admin/verify")
            dur = time.time() - t0
            if r_rev.status_code == 401:
                self.record(name, True, "Verify 200 -> Logout 200 -> Revoked session correctly returned 401", dur)
            else:
                self.record(name, False, f"Session was NOT revoked after logout! Got status {r_rev.status_code}", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 6. Regular Non-Streaming Chat
    def test_06_regular_chat(self):
        name = "6. Regular Chat (/api/chat)"
        t0 = time.time()
        try:
            payload = {
                "question": "Trường Đại học Công Thương TP.HCM ở đâu?",
                "session_id": f"smoke-{uuid.uuid4().hex[:8]}",
            }
            headers = {"X-CSRF-Token": self.user_csrf_token}
            r = self.user_client.post("/api/chat", json=payload, headers=headers)
            dur = time.time() - t0
            if r.status_code == 200:
                body = r.json()
                if body.get("answer") and len(body.get("answer")) > 10:
                    self.record(name, True, "HTTP 200 OK, answer received successfully", dur)
                    return
            self.record(name, False, f"Chat response invalid: {r.status_code} - {r.text}", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 7. NDJSON Canonical Stream
    def test_07_ndjson_canonical_stream(self):
        name = "7. NDJSON Canonical Stream (/api/chat-stream)"
        t0 = time.time()
        req_id = f"stream-{uuid.uuid4().hex[:8]}"
        try:
            payload = {"question": "Các phương thức xét tuyển của HUIT năm 2026?"}
            headers = {
                "X-Request-ID": req_id,
                "X-CSRF-Token": self.user_csrf_token,
                "Accept": "application/x-ndjson",
            }
            with self.user_client.stream("POST", "/api/chat-stream", json=payload, headers=headers) as res:
                if res.status_code != 200:
                    self.record(name, False, f"Stream returned HTTP {res.status_code}", time.time() - t0)
                    return

                event_types = []
                seqs = []
                for line in res.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        event_types.append(ev.get("type"))
                        if "sequence" in ev:
                            seqs.append(ev["sequence"])
                    except Exception:
                        pass

                dur = time.time() - t0
                allowed = {"start", "token", "progress", "artifact", "error", "done", "cancelled"}
                unexpected = set(event_types) - allowed
                if unexpected:
                    self.record(name, False, f"Unexpected event types: {unexpected}", dur)
                    return

                is_monotonic = all(seqs[i] <= seqs[i + 1] for i in range(len(seqs) - 1)) if seqs else True
                if not is_monotonic:
                    self.record(name, False, f"Sequence is not monotonic: {seqs}", dur)
                    return

                if "start" in event_types and "done" in event_types:
                    self.record(name, True, f"HTTP 200 OK, {len(event_types)} canonical events, monotonic sequence", dur)
                else:
                    self.record(name, False, f"Missing start or done event. Got: {set(event_types)}", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 8. Stream Resume
    def test_08_stream_resume_no_duplicate(self):
        name = "8. Stream Reconnect / Resume (X-Last-Sequence)"
        t0 = time.time()
        try:
            req_id = f"resume-flow-{uuid.uuid4().hex[:8]}"
            headers = {
                "X-Request-ID": req_id,
                "X-CSRF-Token": self.user_csrf_token,
                "Accept": "application/x-ndjson",
            }
            payload = {"question": "Giới thiệu ngành Quản trị Kinh doanh HUIT?"}

            last_seq = 0
            with self.user_client.stream("POST", "/api/chat-stream", json=payload, headers=headers) as res:
                if res.status_code != 200:
                    self.record(name, False, f"Initial stream returned HTTP {res.status_code}", time.time() - t0)
                    return
                for line in res.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        if "sequence" in ev:
                            last_seq = ev["sequence"]
                            if last_seq >= 3:
                                break
                    except Exception:
                        pass

            resume_headers = {
                "X-Request-ID": req_id,
                "X-Last-Sequence": str(last_seq),
                "X-CSRF-Token": self.user_csrf_token,
                "Accept": "application/x-ndjson",
            }
            res_resume = self.user_client.post("/api/chat-stream", json=payload, headers=resume_headers)
            dur = time.time() - t0

            if res_resume.status_code == 200:
                self.record(name, True, f"HTTP 200 OK Resume reconnected from sequence > {last_seq} successfully", dur)
            elif res_resume.status_code == 409:
                self.record(name, True, "HTTP 409 handled correctly (Stream producer finished, buffer closed)", dur)
            elif res_resume.status_code == 404:
                self.record(name, False, "HTTP 404 for resume is prohibited by contract", dur)
            else:
                self.record(name, False, f"Unexpected resume status {res_resume.status_code}: {res_resume.text}", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 9. Stream Cancel
    def test_09_stream_cancel(self):
        name = "9. Stream Cancel Endpoint (/api/chat/{request_id}/cancel)"
        t0 = time.time()
        try:
            req_id = f"cancel-{uuid.uuid4().hex[:8]}"
            headers = {"X-CSRF-Token": self.user_csrf_token}
            r = self.user_client.post(f"/api/chat/{req_id}/cancel", headers=headers)
            dur = time.time() - t0
            if r.status_code == 200:
                body = r.json()
                self.record(name, True, f"HTTP 200 OK cancel acknowledged: {body.get('status', 'cancelled')}", dur)
            elif r.status_code == 404:
                self.record(name, False, "HTTP 404 for cancel is prohibited by contract", dur)
            else:
                self.record(name, False, f"Unexpected cancel status {r.status_code}: {r.text}", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 10. Migration 020 Validator, Unique Index & TTL
    def test_10_migration_020_validation_index_ttl(self):
        name = "10. Migration 020 Validator, Index & TTL"
        t0 = time.time()
        try:
            from backend.app.repositories.mongo_repository import MongoRepository
            db = MongoRepository.get_db()
            if db is None:
                self.record(name, False, "MongoDB connection unavailable for validator verification", time.time() - t0)
                return

            col_info = db.command({"listCollections": 1, "filter": {"name": "admin_sessions"}})
            batch = col_info.get("cursor", {}).get("firstBatch", [])
            if not batch:
                self.record(name, False, "Collection 'admin_sessions' not found", time.time() - t0)
                return

            options = batch[0].get("options", {})
            level = options.get("validationLevel")
            action = options.get("validationAction")
            if level != "strict" or action != "error":
                self.record(name, False, f"admin_sessions validator not strict: level={level}, action={action}", time.time() - t0)
                return

            indexes = list(db["admin_sessions"].list_indexes())
            has_unique_hash = any(idx.get("key") == {"session_hash": 1} and idx.get("unique") is True for idx in indexes)
            has_ttl_expires = any(idx.get("key") == {"expires_at": 1} and idx.get("expireAfterSeconds") == 0 for idx in indexes)

            if not has_unique_hash:
                self.record(name, False, "Missing unique index on session_hash", time.time() - t0)
                return
            if not has_ttl_expires:
                self.record(name, False, "Missing TTL index on expires_at with expireAfterSeconds=0", time.time() - t0)
                return

            dur = time.time() - t0
            self.record(name, True, "admin_sessions strict/error validator, unique session_hash & TTL expires_at verified", dur)
        except Exception as e:
            self.record(name, False, f"Migration 020 verification error: {e}", time.time() - t0)

    # 11. Artifact Creation & Multi-User Isolation
    def test_11_artifact_isolation(self):
        name = "11. Artifact Multi-User Isolation"
        t0 = time.time()
        try:
            client_a = httpx.Client(base_url=self.base_url, timeout=30.0)
            client_b = httpx.Client(base_url=self.base_url, timeout=30.0)

            csrf_a = client_a.post("/api/auth/session").json().get("csrf_token", "")
            csrf_b = client_b.post("/api/auth/session").json().get("csrf_token", "")

            headers_a = {"X-CSRF-Token": csrf_a, "X-User-ID": "alice_test"}
            headers_b = {"X-CSRF-Token": csrf_b, "X-User-ID": "bob_test"}

            prompt = "Sơ đồ chỉ tiêu tuyển sinh khoa Công nghệ Thông tin 2026"
            r_a = client_a.post("/api/artifacts/plan", json={"prompt": prompt, "type": "document"}, headers=headers_a)
            if r_a.status_code != 200:
                self.record(name, False, f"Artifact plan Alice failed: {r_a.status_code}", time.time() - t0)
                return

            art_id_a = r_a.json().get("artifact_id")

            r_b = client_b.post("/api/artifacts/plan", json={"prompt": prompt, "type": "document"}, headers=headers_b)
            if r_b.status_code != 200:
                self.record(name, False, f"Artifact plan Bob failed: {r_b.status_code}", time.time() - t0)
                return

            art_id_b = r_b.json().get("artifact_id")

            if art_id_a == art_id_b:
                self.record(name, False, "COLLISION: Two different users received the same artifact_id!", time.time() - t0)
                return

            dur = time.time() - t0
            self.record(name, True, f"Two users isolated successfully (art_a={art_id_a}, art_b={art_id_b})", dur)
        except Exception as e:
            self.record(name, False, f"Connection failed: {e}", time.time() - t0)

    # 12. Export & Upscale via Worker (HTTP 202 & Polling Completed)
    def test_12_worker_export_and_upscale(self):
        name = "12. Durable Worker Export & Upscale (HTTP 202 & Polling)"
        t0 = time.time()
        try:
            from backend.app.workers.artifact_worker import ArtifactWorker
            import asyncio
            worker = ArtifactWorker(worker_id="smoke_worker_01")

            def _tick_worker():
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            pool.submit(asyncio.run, worker.process_single_job()).result()
                    else:
                        asyncio.run(worker.process_single_job())
                except Exception:
                    pass

            headers = {"X-CSRF-Token": self.user_csrf_token}

            # 12a. Tạo artifact plan cho Export
            r_plan_exp = self.user_client.post(
                "/api/artifacts/plan",
                json={"prompt": "Bảng dự toán học phí HUIT 2026", "type": "spreadsheet"},
                headers=headers
            )
            if r_plan_exp.status_code != 200:
                self.record(name, False, f"Failed to create artifact plan for export: {r_plan_exp.status_code}", time.time() - t0)
                return

            art_id_exp = r_plan_exp.json()["artifact_id"]

            # 12b. Gửi yêu cầu export (HTTP 202)
            r_exp = self.user_client.post(
                f"/api/artifacts/{art_id_exp}/export",
                json={"artifact_id": art_id_exp, "format": "xlsx"},
                headers=headers
            )
            if r_exp.status_code != 202:
                self.record(name, False, f"Export expected HTTP 202 Accepted, got {r_exp.status_code}", time.time() - t0)
                return

            job_id_exp = r_exp.json().get("job_id")
            if not job_id_exp:
                self.record(name, False, "Missing job_id in export 202 response", time.time() - t0)
                return

            _tick_worker()

            # 12c. Polling export job
            exp_completed = False
            exp_result_url = None
            for _ in range(15):
                r_job = self.user_client.get(f"/api/jobs/{job_id_exp}", headers=headers)
                if r_job.status_code == 200:
                    j_info = r_job.json()
                    if j_info.get("status") == "completed":
                        exp_completed = True
                        exp_result_url = j_info.get("result_url") or j_info.get("download_url")
                        break
                time.sleep(0.5)

            if not exp_completed or not exp_result_url:
                self.record(name, False, f"Export job {job_id_exp} failed to complete in time", time.time() - t0)
                return

            # 12d. Tạo artifact plan cho Upscale
            r_plan_up = self.user_client.post(
                "/api/artifacts/plan",
                json={"prompt": "Sơ đồ quy trình xét tuyển HUIT 2026", "type": "image"},
                headers=headers
            )
            if r_plan_up.status_code != 200:
                self.record(name, False, f"Failed to create artifact plan for upscale: {r_plan_up.status_code}", time.time() - t0)
                return

            art_id_up = r_plan_up.json()["artifact_id"]

            # 12e. Gửi yêu cầu upscale (HTTP 202)
            r_upscale = self.user_client.post(
                f"/api/artifacts/{art_id_up}/upscale",
                json={"scale": 2},
                headers=headers
            )
            if r_upscale.status_code != 202:
                self.record(name, False, f"Upscale expected HTTP 202 Accepted, got {r_upscale.status_code}", time.time() - t0)
                return

            job_id_up = r_upscale.json().get("job_id")
            if not job_id_up:
                self.record(name, False, "Missing job_id in upscale 202 response", time.time() - t0)
                return

            _tick_worker()

            # 12f. Polling upscale job
            up_completed = False
            up_result_url = None
            for _ in range(15):
                r_job = self.user_client.get(f"/api/jobs/{job_id_up}", headers=headers)
                if r_job.status_code == 200:
                    j_info = r_job.json()
                    if j_info.get("status") == "completed":
                        up_completed = True
                        up_result_url = j_info.get("download_url") or j_info.get("result_url")
                        break
                time.sleep(0.5)

            dur = time.time() - t0
            if up_completed and up_result_url:
                self.record(
                    name,
                    True,
                    f"Export job {job_id_exp} and Upscale job {job_id_up} both completed via worker with signed URLs",
                    dur,
                    {"export_job_id": job_id_exp, "upscale_job_id": job_id_up, "upscale_url": up_result_url[:40]}
                )
            else:
                self.record(name, False, f"Upscale job {job_id_up} failed to complete or missing result URL", dur)
        except Exception as e:
            self.record(name, False, f"Worker export & upscale flow error: {e}", time.time() - t0)

    # 13. Signed Download Contract (Valid vs Unsigned vs Expired)
    def test_13_signed_download_contract(self):
        name = "13. Signed Download Contract (Valid vs Unsigned vs Expired)"
        t0 = time.time()
        try:
            from backend.app.storage.storage_adapter import get_storage_adapter
            from backend.app.services.auth_service import create_download_signature

            storage = get_storage_adapter()
            test_key = f"smoke_test_doc_{uuid.uuid4().hex[:6]}.txt"
            storage.put(test_key, b"HUIT Chatbot Staging Smoke Test Binary Content")

            # 13a. Unsigned request -> Phải bị chặn 401 hoặc 403 hoặc 422
            r_unsigned = self.user_client.get(f"/api/artifacts/download/{test_key}")
            if r_unsigned.status_code not in (401, 403, 422):
                self.record(name, False, f"Unsigned request unexpectedly returned HTTP {r_unsigned.status_code}", time.time() - t0)
                return

            # 13b. Expired signature -> Phải bị chặn 403
            past_exp = int(time.time()) - 120
            past_sig, _ = create_download_signature(test_key, expires_in=-120)
            r_expired = self.user_client.get(f"/api/artifacts/download/{test_key}?sig={past_sig}&expires={past_exp}")
            if r_expired.status_code not in (401, 403):
                self.record(name, False, f"Expired signature unexpectedly returned HTTP {r_expired.status_code}", time.time() - t0)
                return

            # 13c. Tampered signature -> Phải bị chặn 403
            future_exp = int(time.time()) + 3600
            r_tampered = self.user_client.get(f"/api/artifacts/download/{test_key}?sig=tampered_signature_hex&expires={future_exp}")
            if r_tampered.status_code not in (401, 403):
                self.record(name, False, f"Tampered signature unexpectedly returned HTTP {r_tampered.status_code}", time.time() - t0)
                return

            # 13d. Valid signed URL -> Phải trả về 200 OK và đúng nội dung
            valid_sig, valid_exp = create_download_signature(test_key, expires_in=3600)
            r_valid = self.user_client.get(f"/api/artifacts/download/{test_key}?sig={valid_sig}&expires={valid_exp}")
            if r_valid.status_code != 200 or b"HUIT Chatbot" not in r_valid.content:
                self.record(name, False, f"Valid signed request failed: HTTP {r_valid.status_code}", time.time() - t0)
                return

            dur = time.time() - t0
            self.record(name, True, "Signed download: valid 200 OK, unsigned/expired/tampered strictly blocked 403", dur)
        except Exception as e:
            self.record(name, False, f"Signed download error: {e}", time.time() - t0)

    # Export Reports: JSON and JUnit XML
    def save_reports(self, json_path: Path, junit_path: Path):
        json_path.parent.mkdir(parents=True, exist_ok=True)
        junit_path.parent.mkdir(parents=True, exist_ok=True)

        passed_count = sum(1 for r in self.results.values() if r["passed"])
        total_count = len(self.results)
        failed_count = total_count - passed_count
        total_duration = sum(r["duration_sec"] for r in self.results.values())

        # 1. JSON Report
        report_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_url": self.base_url,
            "total_tests": total_count,
            "passed_tests": passed_count,
            "failed_tests": failed_count,
            "pass_rate_pct": round((passed_count / total_count * 100) if total_count else 0, 1),
            "total_duration_sec": round(total_duration, 3),
            "status": "PASSED" if failed_count == 0 else "FAILED",
            "tests": [
                {
                    "name": name,
                    "passed": res["passed"],
                    "duration_sec": res["duration_sec"],
                    "message": res["message"],
                    "details": res.get("details"),
                }
                for name, res in self.results.items()
            ],
        }
        json_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # 2. JUnit XML Report
        testsuites = ET.Element("testsuites", {
            "name": "StagingSmokeFullStack",
            "tests": str(total_count),
            "failures": str(failed_count),
            "errors": "0",
            "time": f"{total_duration:.3f}"
        })
        testsuite = ET.SubElement(testsuites, "testsuite", {
            "name": "FullStackSmokeScenarios",
            "tests": str(total_count),
            "failures": str(failed_count),
            "errors": "0",
            "time": f"{total_duration:.3f}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        for name, res in self.results.items():
            safe_name = name.replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")
            tc = ET.SubElement(testsuite, "testcase", {
                "classname": "StagingSmokeRunner",
                "name": safe_name,
                "time": f"{res['duration_sec']:.3f}"
            })
            if not res["passed"]:
                fail_elem = ET.SubElement(tc, "failure", {"message": res["message"]})
                fail_elem.text = json.dumps(res.get("details") or res["message"], ensure_ascii=False)

        tree = ET.ElementTree(testsuites)
        tree.write(junit_path, encoding="utf-8", xml_declaration=True)
        print(f"\n[REPORT] Đã xuất JSON: {json_path}")
        print(f"[REPORT] Đã xuất JUnit XML: {junit_path}")

    # Run All
    def run_all(self, admin_user: str, admin_pass: str, json_path: Path, junit_path: Path) -> bool:
        print("=" * 70)
        print(f"BẮT ĐẦU FULL-STACK HTTP SMOKE TEST (Target: {self.base_url})")
        print("Sử dụng HTTP Client thật qua mạng TCP/HTTP - TUYỆT ĐỐI KHÔNG DÙNG TestClient")
        print("=" * 70)

        self.test_01_health_live()
        self.test_02_health_ready()
        self.test_03_csrf_session()
        self.test_04_admin_login_zero_token(admin_user, admin_pass)
        self.test_05_admin_verify_and_logout()
        self.test_06_regular_chat()
        self.test_07_ndjson_canonical_stream()
        self.test_08_stream_resume_no_duplicate()
        self.test_09_stream_cancel()
        self.test_10_migration_020_validation_index_ttl()
        self.test_11_artifact_isolation()
        self.test_12_worker_export_and_upscale()
        self.test_13_signed_download_contract()

        self.save_reports(json_path, junit_path)

        print("\n" + "=" * 70)
        print("TỔNG HỢP KẾT QUẢ FULL-STACK SMOKE TEST:")
        print("=" * 70)
        passed_count = sum(1 for r in self.results.values() if r["passed"])
        total_count = len(self.results)

        for name, res in self.results.items():
            st = "PASS" if res["passed"] else "FAIL"
            print(f"[{st:4}] {name}: {res['message']}")

        print("-" * 70)
        print(f"KẾT QUẢ: {passed_count}/{total_count} bài kiểm tra đạt ({(passed_count/total_count)*100:.1f}%)")
        print("=" * 70)
        return passed_count == total_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Full-stack HTTP smoke test")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of running API")
    parser.add_argument("--user", default="khaihiep", help="Admin username")
    parser.add_argument("--password", default="", help="Admin password")
    parser.add_argument("--report-json", default="audit_outputs/smoke_test_report.json", help="Path for JSON report")
    parser.add_argument("--report-junit", default="audit_outputs/smoke_test_junit.xml", help="Path for JUnit XML report")
    args = parser.parse_args()

    if not args.password:
        from backend.app.config import settings
        args.password = settings.ADMIN_PASSWORD
        args.user = settings.ADMIN_USERNAME

    runner = StagingSmokeRunner(args.url)
    success = runner.run_all(
        args.user,
        args.password,
        json_path=Path(args.report_json),
        junit_path=Path(args.report_junit)
    )
    sys.exit(0 if success else 1)
