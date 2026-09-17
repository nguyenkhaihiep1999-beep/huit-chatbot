"""
scripts/rollback_production.py
Quy trình và kịch bản Rollback khẩn cấp cho Production (Emergency Rollback Runbook):
1. Vercel Frontend: Khôi phục phiên bản trước qua Vercel Instant Rollback.
2. Docker Backend: Trỏ lại image/tag trước đó và khởi động lại.
3. Database: Xác minh tính toàn vẹn của snapshot sao lưu trước khi phục hồi (nếu xảy ra lỗi schema).
4. Xác minh sức khỏe hệ thống sau rollback qua /api/health/live và /api/health/ready.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx


def verify_system_after_rollback(api_base_url: str = "http://127.0.0.1:8000") -> bool:
    print(f"=== KIỂM THỬ XÁC NHẬN SỨC KHỎE HỆ THỐNG SAU ROLLBACK ({api_base_url}) ===")
    try:
        with httpx.Client(timeout=10.0) as client:
            r_live = client.get(f"{api_base_url}/api/health/live")
            if r_live.status_code != 200:
                print(f"❌ Liveness probe thất bại: HTTP {r_live.status_code}")
                return False
            print("  ✓ Liveness probe: OK (200)")

            r_ready = client.get(f"{api_base_url}/api/health/ready")
            if r_ready.status_code != 200:
                print(f"❌ Readiness probe thất bại: HTTP {r_ready.status_code} - {r_ready.text}")
                return False
            ready_data = r_ready.json()
            print(f"  ✓ Readiness probe: OK (200) - Status: {ready_data.get('status')}")

            # Kiểm tra cơ chế Chat cơ bản
            r_chat = client.post(
                f"{api_base_url}/api/chat",
                json={"question": "Kiểm tra sau rollback"},
                headers={"X-Request-ID": "rollback-verify"}
            )
            if r_chat.status_code != 200:
                print(f"❌ Chat probe thất bại: HTTP {r_chat.status_code}")
                return False
            print("  ✓ Chat probe: OK (200)")
            print("\n✅ ROLLBACK XÁC THỰC THÀNH CÔNG: Toàn bộ dịch vụ đã ổn định!")
            return True
    except Exception as e:
        print(f"❌ Lỗi kết nối khi xác thực sau rollback: {e}")
        return False


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    ok = verify_system_after_rollback(url)
    sys.exit(0 if ok else 1)
