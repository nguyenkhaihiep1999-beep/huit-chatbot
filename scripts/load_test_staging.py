"""
load_test_staging.py
Kiểm thử tải đồng thời (Concurrency Load Test) qua HTTP thật:
1. Nhiều chat stream đồng thời (concurrency cấu hình được).
   - Tuyệt đối KHÔNG tính STREAM_ENDED thiếu terminal event "done" là thành công.
   - Đo lường chính xác P50 / P95 / P99, TTFT (Time To First Token), tỷ lệ lỗi (Error Rate).
2. Nhiều artifact jobs đồng thời (concurrent plan & export).
3. Rate Limiting Assertions: Gửi burst requests dồn dập vượt ngưỡng và khẳng định mã HTTP 429 được kích hoạt.
4. Giám sát tài nguyên RAM hệ thống.
5. Xuất báo cáo máy đọc được audit_outputs/load_test_report.json.
6. Thoát với mã exit code 1 nếu bất kỳ tiêu chí chất lượng nào không đạt.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def percentile(data: List[float], p: float) -> float:
    """Tính phân vị thứ p (0-100) theo phương pháp nội suy tuyến tính."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c < len(sorted_data):
        return round(sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f]), 3)
    return round(sorted_data[f], 3)


async def run_single_stream(client: httpx.AsyncClient, base_url: str, idx: int, csrf_token: str) -> dict:
    req_id = f"load-stream-{idx}-{uuid.uuid4().hex[:6]}"
    start_t = time.time()
    token_count = 0
    first_token_time = None
    has_done_event = False
    status = "FAILED"
    error_msg = None

    try:
        payload = {"question": f"Cho tôi biết thông tin ngành Công nghệ Thông tin HUIT mẫu {idx}?"}
        headers = {
            "X-Request-ID": req_id,
            "X-CSRF-Token": csrf_token,
            "Accept": "application/x-ndjson",
        }
        async with client.stream("POST", f"{base_url}/api/chat-stream", json=payload, headers=headers) as resp:
            if resp.status_code == 200:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        ev_type = ev.get("type")
                        if ev_type == "token":
                            token_count += 1
                            if first_token_time is None:
                                first_token_time = time.time() - start_t
                        elif ev_type == "done":
                            has_done_event = True
                    except Exception:
                        pass

                # BẮT BUỘC: Không tính STREAM_ENDED thiếu terminal event là thành công!
                if has_done_event:
                    status = "COMPLETED"
                else:
                    status = "STREAM_INCOMPLETE_MISSING_DONE"
                    error_msg = "Stream terminated prematurely without terminal 'done' event"
            else:
                status = f"HTTP_{resp.status_code}"
                error_msg = f"Unexpected status code: {resp.status_code}"
    except Exception as e:
        status = f"ERROR_{type(e).__name__}"
        error_msg = str(e)

    total_time = time.time() - start_t
    return {
        "idx": idx,
        "status": status,
        "duration_sec": round(total_time, 3),
        "ttft_sec": round(first_token_time or total_time, 3),
        "token_count": token_count,
        "has_done_event": has_done_event,
        "error": error_msg,
    }


async def test_concurrent_chat_streams(base_url: str, concurrency: int, csrf_token: str) -> dict:
    print(f"\n[1/4] Kiểm thử {concurrency} luồng Chat Stream đồng thời (yêu cầu terminal 'done')...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        tasks = [run_single_stream(client, base_url, i, csrf_token) for i in range(concurrency)]
        start = time.time()
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start

    durations = [r["duration_sec"] for r in results]
    ttfts = [r["ttft_sec"] for r in results]

    # Chỉ tính thành công khi trạng thái là COMPLETED (có done event)
    successes = sum(1 for r in results if r["status"] == "COMPLETED")
    error_rate = 1.0 - (successes / concurrency) if concurrency else 0.0

    p50_dur = percentile(durations, 50)
    p95_dur = percentile(durations, 95)
    p99_dur = percentile(durations, 99)

    p50_ttft = percentile(ttfts, 50)
    p95_ttft = percentile(ttfts, 95)
    p99_ttft = percentile(ttfts, 99)
    mean_ttft = round(sum(ttfts) / len(ttfts), 3) if ttfts else 0.0

    print(f"  -> Hoàn tất {concurrency} requests trong {elapsed:.2f}s")
    print(f"  -> Thành công: {successes}/{concurrency} ({(successes/concurrency)*100:.1f}%) | Tỷ lệ lỗi (Error Rate): {error_rate*100:.1f}%")
    print(f"  -> Độ trễ tổng thể (Duration): P50={p50_dur:.2f}s, P95={p95_dur:.2f}s, P99={p99_dur:.2f}s")
    print(f"  -> TTFT (Time To First Token): Mean={mean_ttft:.2f}s, P50={p50_ttft:.2f}s, P95={p95_ttft:.2f}s, P99={p99_ttft:.2f}s")

    passed = (error_rate == 0.0)
    return {
        "passed": passed,
        "concurrency": concurrency,
        "successes": successes,
        "total": concurrency,
        "error_rate": round(error_rate, 4),
        "duration_metrics": {"p50": p50_dur, "p95": p95_dur, "p99": p99_dur, "elapsed_total": round(elapsed, 3)},
        "ttft_metrics": {"mean": mean_ttft, "p50": p50_ttft, "p95": p95_ttft, "p99": p99_ttft},
        "results": results,
    }


async def run_single_artifact_job(client: httpx.AsyncClient, base_url: str, idx: int, csrf_token: str) -> dict:
    start_t = time.time()
    status = "FAILED"
    art_id = None
    try:
        headers = {"X-CSRF-Token": csrf_token, "X-User-ID": f"load_user_{idx}"}
        prompt = f"Biểu đồ phân bổ điểm chuẩn HUIT mẫu {idx}"
        r = await client.post(f"{base_url}/api/artifacts/plan", json={"prompt": prompt, "type": "document"}, headers=headers)
        if r.status_code == 200:
            art_id = r.json().get("artifact_id")
            status = "PLAN_CREATED"
        else:
            status = f"HTTP_{r.status_code}"
    except Exception as e:
        status = f"ERROR_{type(e).__name__}"

    return {
        "idx": idx,
        "status": status,
        "artifact_id": art_id,
        "duration_sec": round(time.time() - start_t, 3),
    }


async def test_concurrent_artifact_jobs(base_url: str, concurrency: int, csrf_token: str) -> dict:
    print(f"\n[2/4] Kiểm thử {concurrency} tác vụ Artifact đồng thời (tạo Artifact Plan)...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [run_single_artifact_job(client, base_url, i, csrf_token) for i in range(concurrency)]
        start = time.time()
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start

    durations = [r["duration_sec"] for r in results]
    successes = sum(1 for r in results if r["status"] == "PLAN_CREATED")
    error_rate = 1.0 - (successes / concurrency) if concurrency else 0.0

    p50_dur = percentile(durations, 50)
    p95_dur = percentile(durations, 95)

    print(f"  -> Hoàn tất {concurrency} requests tạo artifact trong {elapsed:.2f}s")
    print(f"  -> Thành công: {successes}/{concurrency} | P50={p50_dur:.2f}s, P95={p95_dur:.2f}s")

    passed = (error_rate == 0.0)
    return {
        "passed": passed,
        "concurrency": concurrency,
        "successes": successes,
        "error_rate": round(error_rate, 4),
        "duration_metrics": {"p50": p50_dur, "p95": p95_dur, "elapsed_total": round(elapsed, 3)},
        "results": results,
    }


async def test_rate_limiting_assertion(base_url: str) -> dict:
    print("\n[3/4] Kiểm thử Rate Limiting (gửi 12 request burst dồn dập vào /api/admin/login)...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [
            client.post(f"{base_url}/api/admin/login", json={"username": "probe", "password": "wrong_password"})
            for _ in range(12)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        statuses = [r.status_code if isinstance(r, httpx.Response) else 999 for r in responses]

    count_429 = statuses.count(429)
    count_401 = statuses.count(401)
    print(f"  -> Kết quả 12 requests: 401 Unauthorized={count_401}, 429 Too Many Requests={count_429}")

    rate_limit_active = count_429 > 0
    if rate_limit_active:
        print("  -> ✅ PASS: Rate Limiter kích hoạt chính xác (chặn request vượt ngưỡng với mã 429)")
    else:
        print("  -> ❌ FAIL: Rate Limiter không kích hoạt (không có mã 429 khi gửi request vượt ngưỡng)")

    return {
        "passed": rate_limit_active,
        "rate_limit_active": rate_limit_active,
        "count_401": count_401,
        "count_429": count_429,
        "total_requests": len(statuses),
    }


def get_system_ram_usage():
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent_used": mem.percent,
        }
    except ImportError:
        return None


async def main():
    parser = argparse.ArgumentParser(description="Load test staging with strict quality metrics")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of running API")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent streams")
    parser.add_argument("--artifact-concurrency", type=int, default=None, help="Number of concurrent artifact jobs (defaults to concurrency)")
    parser.add_argument("--report-json", default="audit_outputs/load_test_report.json", help="Path for JSON report")
    args = parser.parse_args()
    art_concurrency = args.artifact_concurrency or args.concurrency

    print("=" * 70)
    print("BẮT ĐẦU KIỂM THỬ TẢI ĐỒNG THỜI CHO STAGING (STRICT QUALITY GATE)")
    print(f"Target URL: {args.url} | Stream Concurrency: {args.concurrency} | Artifact Concurrency: {art_concurrency}")
    print("=" * 70)

    # 1. Lấy CSRF token ban đầu
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r_csrf = await client.post(f"{args.url}/api/auth/session")
            csrf_token = r_csrf.json().get("csrf_token", "") if r_csrf.status_code == 200 else ""
        except Exception:
            csrf_token = ""

    ram_before = get_system_ram_usage()
    if ram_before:
        print(f"RAM ban đầu: {ram_before['used_gb']} GB / {ram_before['total_gb']} GB ({ram_before['percent_used']}%)")

    # 2. Chạy Concurrent Chat Streams
    stream_res = await test_concurrent_chat_streams(args.url, args.concurrency, csrf_token)

    # 3. Chạy Concurrent Artifact Jobs
    artifact_res = await test_concurrent_artifact_jobs(args.url, art_concurrency, csrf_token)

    # 4. Chạy Rate Limiting Assertion
    rate_res = await test_rate_limiting_assertion(args.url)

    # 5. Đo lường RAM sau test
    ram_after = get_system_ram_usage()
    ram_delta_gb = round(ram_after['used_gb'] - ram_before['used_gb'], 3) if (ram_before and ram_after) else 0.0
    if ram_after:
        print(f"\n[4/4] Giám sát tài nguyên RAM:")
        print(f"  -> RAM sau test: {ram_after['used_gb']} GB ({ram_after['percent_used']}%)")
        print(f"  -> Chênh lệch RAM: {ram_delta_gb:+.3f} GB")

    overall_passed = stream_res["passed"] and artifact_res["passed"] and rate_res["passed"]

    # 6. Xuất JSON Report
    report_path = Path(args.report_json)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target_url": args.url,
        "concurrency": args.concurrency,
        "overall_status": "PASSED" if overall_passed else "FAILED",
        "chat_stream_suite": stream_res,
        "artifact_suite": artifact_res,
        "rate_limiting_suite": rate_res,
        "memory_metrics": {
            "ram_before": ram_before,
            "ram_after": ram_after,
            "ram_delta_gb": ram_delta_gb,
        },
    }
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[REPORT] Đã xuất báo cáo tải JSON: {report_path}")

    print("=" * 70)
    print(f"KẾT QUẢ TẢI: {'✅ PASSED (Tất cả tiêu chuẩn đạt)' if overall_passed else '❌ FAILED (Có lỗi phát sinh)'}")
    print("=" * 70)

    sys.exit(0 if overall_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
