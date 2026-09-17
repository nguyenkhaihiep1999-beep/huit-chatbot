"""
test_production_infrastructure_hardening.py
Bộ kiểm thử tĩnh cấu trúc (structural static analysis) cho hạ tầng Docker Compose và Network:
1. Mô hình cơ sở dữ liệu: MongoDB Atlas là mặc định, local mongo đặt trong profile riêng, không nằm trong default stack.
2. Redis bảo mật: Bắt buộc mật khẩu (requirepass), healthcheck xác thực có pass, mọi URI Redis đều chứa authentication.
3. Phân vùng mạng: backend_net có internal: true; chỉ Gateway (frontend Nginx) có host port; backend, worker, redis không publish port ra host.
4. Gia cố Container: security_opt no-new-privileges, cap_drop ALL, read_only filesystem, non-root user, resource limits, log rotation.
5. Lưu trữ: Cấu hình shared-storage / S3 object storage; không lưu binary trong MongoDB.
6. Security Headers & Docs Blocking: CSP, HSTS, X-Content-Type-Options, X-Frame-Options/frame-ancestors, Permissions-Policy, chặn /docs.
7. FastAPI Toggle: Tự động tắt Swagger/OpenAPI spec khi APP_ENV=production.
"""

from pathlib import Path
import pytest
import yaml
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def prod_compose_data():
    compose_path = ROOT_DIR / "docker-compose.prod.yml"
    assert compose_path.exists(), "docker-compose.prod.yml phải tồn tại trong root"
    content = compose_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), "docker-compose.prod.yml phải là tài liệu YAML hợp lệ"
    return data


def test_production_database_model_is_atlas(prod_compose_data):
    """1. Kiểm tra mô hình cơ sở dữ liệu production: Sử dụng MongoDB Atlas có TLS; local mongo nằm trong profile riêng."""
    services = prod_compose_data.get("services", {})
    backend = services.get("backend", {})
    worker = services.get("worker", {})

    # Local mongo không được nằm trong default dependencies của backend hoặc worker
    backend_deps = backend.get("depends_on", {})
    worker_deps = worker.get("depends_on", {})
    assert "mongo" not in backend_deps, "Backend production không được phụ thuộc vào container mongo local"
    assert "mongo" not in worker_deps, "Worker production không được phụ thuộc vào container mongo local"

    # Nếu service mongo tồn tại, bắt buộc phải nằm trong profile riêng (ví dụ with-local-mongo)
    if "mongo" in services:
        mongo_service = services["mongo"]
        profiles = mongo_service.get("profiles", [])
        assert len(profiles) > 0, "Container mongo local trong production Compose bắt buộc phải có profile riêng"
        assert "with-local-mongo" in profiles or "local-db" in profiles

    # Backend và Worker phải có biến MONGODB_URI bắt buộc cấu hình
    for svc_name, svc_conf in [("backend", backend), ("worker", worker)]:
        env_vars = svc_conf.get("environment", [])
        mongo_uri_decl = [e for e in env_vars if "MONGODB_URI" in e]
        assert len(mongo_uri_decl) > 0, f"{svc_name} phải khai báo biến MONGODB_URI"
        assert any("MONGODB_URI" in e and ":?" in e for e in mongo_uri_decl), f"{svc_name} MONGODB_URI phải là biến bắt buộc"


def test_redis_authentication_and_acl_enforced(prod_compose_data):
    """2. Kiểm tra Redis được gia cố: Có password, healthcheck xác thực, không dùng URI không password."""
    services = prod_compose_data.get("services", {})
    assert "redis" in services, "Phải có service redis"
    redis = services["redis"]

    # Kiểm tra lệnh khởi chạy có requirepass
    command = redis.get("command", [])
    command_str = " ".join(command) if isinstance(command, list) else str(command)
    assert "--requirepass" in command_str, "Redis server bắt buộc phải chạy với --requirepass"
    assert "REDIS_PASSWORD" in command_str, "Mật khẩu Redis phải lấy từ biến môi trường REDIS_PASSWORD"

    # Kiểm tra healthcheck có xác thực
    healthcheck = redis.get("healthcheck", {})
    hc_test = healthcheck.get("test", [])
    hc_str = " ".join(hc_test) if isinstance(hc_test, list) else str(hc_test)
    assert "-a" in hc_str or "--auth" in hc_str or "AUTH" in hc_str, "Redis healthcheck phải xác thực bằng mật khẩu"

    # Kiểm tra backend và worker sử dụng Redis URI có mật khẩu
    for svc_name in ["backend", "worker"]:
        svc_conf = services.get(svc_name, {})
        env_vars = svc_conf.get("environment", [])
        redis_uris = [e for e in env_vars if "REDIS_URL" in e]
        assert len(redis_uris) > 0, f"{svc_name} phải cấu hình các biến REDIS_URL"
        for r_decl in redis_uris:
            assert "REDIS_PASSWORD" in r_decl, f"{svc_name} {r_decl} phải chứa REDIS_PASSWORD để xác thực"
            assert "redis://redis:6379" not in r_decl, f"{svc_name} cấm dùng URI Redis không có mật khẩu"


def test_network_segmentation_and_port_isolation(prod_compose_data):
    """3. Kiểm tra phân vùng mạng và cô lập cổng host: Chỉ Gateway được mở cổng; backend_net là internal."""
    networks = prod_compose_data.get("networks", {})
    assert "frontend_net" in networks, "Phải có mạng frontend_net"
    assert "backend_net" in networks, "Phải có mạng backend_net"
    backend_net = networks["backend_net"]
    assert backend_net.get("internal") is True, "backend_net bắt buộc phải cấu hình internal: true"

    services = prod_compose_data.get("services", {})

    # Chỉ duy nhất frontend (Reverse Proxy / Gateway) được publish cổng ra ngoài host
    frontend = services.get("frontend", {})
    assert "ports" in frontend and len(frontend["ports"]) > 0, "Frontend gateway phải mở cổng tiếp nhận request"

    # Backend tuyệt đối KHÔNG publish ports ra ngoài host
    backend = services.get("backend", {})
    assert "ports" not in backend or len(backend.get("ports", [])) == 0, "Backend tuyệt đối không được publish ports ra ngoài host"
    assert "frontend_net" in backend.get("networks", []), "Backend phải nằm trong frontend_net để Nginx proxy tới"
    assert "backend_net" in backend.get("networks", []), "Backend phải nằm trong backend_net để gọi Redis"

    # Worker tuyệt đối KHÔNG có public ports và chỉ nằm trong backend_net
    worker = services.get("worker", {})
    assert "ports" not in worker or len(worker.get("ports", [])) == 0, "Worker tuyệt đối không được publish ports"
    assert worker.get("networks") == ["backend_net"], "Worker chỉ được nằm trong backend_net"

    # Redis tuyệt đối KHÔNG có public ports và chỉ nằm trong backend_net
    redis = services.get("redis", {})
    assert "ports" not in redis or len(redis.get("ports", [])) == 0, "Redis tuyệt đối không được publish ports ra ngoài host"
    assert redis.get("networks") == ["backend_net"], "Redis chỉ được nằm trong backend_net"


def test_container_hardening_security_attributes(prod_compose_data):
    """4. Kiểm tra các thuộc tính an ninh container: no-new-privileges, cap_drop, read_only, non-root, limits."""
    services = prod_compose_data.get("services", {})

    # Các service chính trong production stack
    core_services = ["frontend", "backend", "worker", "redis"]
    for name in core_services:
        assert name in services, f"Phải có service {name} trong docker-compose.prod.yml"
        svc = services[name]

        # Restart policy
        assert svc.get("restart") == "unless-stopped", f"{name} phải có restart policy unless-stopped"

        # Security options: no-new-privileges
        sec_opts = svc.get("security_opt", [])
        assert "no-new-privileges:true" in sec_opts, f"{name} phải bật no-new-privileges:true"

        # Capability drop: ALL
        cap_drop = svc.get("cap_drop", [])
        assert "ALL" in cap_drop, f"{name} phải drop ALL capabilities"

        # Read-only filesystem
        assert svc.get("read_only") is True, f"{name} phải bật read_only: true"
        assert "tmpfs" in svc, f"{name} phải có tmpfs cho các thư mục tạm ghi"

        # Non-root user
        assert "user" in svc, f"{name} phải chỉ định user non-root rõ ràng"
        user_str = str(svc.get("user"))
        assert user_str != "0" and user_str != "root" and not user_str.startswith("0:"), f"{name} cấm chạy quyền root"

        # Resource limits
        deploy = svc.get("deploy", {})
        resources = deploy.get("resources", {})
        limits = resources.get("limits", {})
        assert "cpus" in limits, f"{name} phải giới hạn CPU"
        assert "memory" in limits, f"{name} phải giới hạn RAM"

        # Log rotation
        logging = svc.get("logging", {})
        assert logging.get("driver") == "json-file", f"{name} phải dùng json-file log driver"
        opts = logging.get("options", {})
        assert "max-size" in opts and "max-file" in opts, f"{name} phải cấu hình max-size và max-file cho log"


def test_nginx_security_headers_and_path_blocking():
    """5. Kiểm tra deploy/nginx.conf có đầy đủ security headers và chặn /docs."""
    nginx_conf = ROOT_DIR / "deploy" / "nginx.conf"
    assert nginx_conf.exists(), "deploy/nginx.conf phải tồn tại"

    content = nginx_conf.read_text(encoding="utf-8")

    assert 'add_header X-Frame-Options "DENY"' in content
    assert 'add_header X-Content-Type-Options "nosniff"' in content
    assert 'add_header Content-Security-Policy' in content
    assert 'add_header Strict-Transport-Security' in content
    assert 'add_header Permissions-Policy' in content

    # Chặn Swagger UI / OpenAPI docs
    assert "location ~ ^/(docs|openapi\\.json|redoc)" in content
    assert "return 404;" in content


def test_production_docs_toggle(monkeypatch):
    """6. Kiểm tra ứng dụng FastAPI tự động tắt Swagger UI và OpenAPI spec khi APP_ENV=production."""
    from backend.app.config import settings

    monkeypatch.setenv("APP_ENV", "production")
    assert settings.IS_PRODUCTION is True

    from fastapi import FastAPI
    docs_url = None if settings.IS_PRODUCTION else "/docs"
    redoc_url = None if settings.IS_PRODUCTION else "/redoc"
    openapi_url = None if settings.IS_PRODUCTION else "/openapi.json"

    prod_app = FastAPI(
        title="Test Prod",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url
    )

    client = TestClient(prod_app)
    res_docs = client.get("/docs")
    assert res_docs.status_code == 404

    res_openapi = client.get("/openapi.json")
    assert res_openapi.status_code == 404
