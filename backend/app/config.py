import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Xác định các thư mục gốc của kiến trúc mới
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = ROOT_DIR / "data"

# Load file .env ưu tiên: backend/.env -> root .env (Hoàn toàn độc lập, không đọc từ legacy)
for env_candidate in [BACKEND_DIR / ".env", ROOT_DIR / ".env"]:
    if env_candidate.exists():
        load_dotenv(env_candidate)
        break

class Settings:
    PROJECT_NAME: str = "HUIT Chatbot RAG System"
    VERSION: str = "2.0.0"
    API_PREFIX: str = "/api"
    DATA_DIR: Path = DATA_DIR

    # Môi trường chạy ứng dụng: nhận diện từ APP_ENV hoặc VERCEL_ENV (production | preview | staging | development)
    @property
    def APP_ENV(self) -> str:
        env = os.getenv("APP_ENV") or os.getenv("VERCEL_ENV") or "development"
        return env.strip().lower()

    @property
    def IS_DEVELOPMENT(self) -> bool:
        return self.APP_ENV in ("development", "dev", "local")

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.APP_ENV in ("production", "prod")

    @property
    def TRUSTED_PROXIES(self) -> List[str]:
        raw = os.getenv("TRUSTED_PROXIES", "")
        if not raw:
            return ["127.0.0.1/32", "::1/128"]
        return [p.strip() for p in raw.split(",") if p.strip()]

    # CORS Allowed Origins (cấu hình qua biến môi trường CORS_ALLOWED_ORIGINS)
    @property
    def CORS_ALLOWED_ORIGINS(self) -> List[str]:
        raw = os.getenv("CORS_ALLOWED_ORIGINS")
        if not raw:
            if self.IS_DEVELOPMENT:
                return [
                    "http://localhost:3000",
                    "http://localhost:5173",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:5173",
                ]
            raise RuntimeError(
                "Lỗi cấu hình bảo mật: Trong môi trường ngoài development (staging/preview/production), "
                "bắt buộc phải cấu hình biến môi trường CORS_ALLOWED_ORIGINS."
            )
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    # MongoDB Atlas
    MONGODB_USER: str = os.getenv("MONGODB_USER", "nguyenkhaihiep1999_db_user")
    MONGODB_HOST: str = os.getenv("MONGODB_HOST", "cluster0.hyj8rab.mongodb.net")
    MONGODB_PASSWORD: str = os.getenv("MONGODB_PASSWORD", "")
    MONGODB_DB: str = os.getenv("MONGODB_DB", "huit_chatbot")
    MONGODB_COLL: str = os.getenv("MONGODB_COLL", "huit_kb")
    MONGODB_TIMEOUT_MS: int = 15000

    @property
    def MONGODB_URI(self) -> str:
        """URI MongoDB đầy đủ, dùng cho local Docker hoặc nhà cung cấp không phải Atlas SRV."""
        return os.getenv("MONGODB_URI", "").strip()

    # RAG & Embeddings (Bảo tồn 100% tính tương đương kiến trúc gốc)
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-large"
    EMBEDDING_DIMS: int = 1024
    KB_VERSION: str = "huit-kb-2026-07-v4-semantic"
    RAG_VERSION: str = "rag-v10-grounded-score-source"
    TOP_K: int = int(os.getenv("TOP_K", "3"))

    # LLM Models
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENROUTER_KEY: str = os.getenv("HUIT_OPENROUTER_KEY") or os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "750"))

    # Security & Auth:
    # - Không hardcode mật khẩu hay token production trong code.
    # - Development (APP_ENV=development) dùng giá trị cục bộ an toàn.
    # - Khi APP_ENV khác development và thiếu ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_TOKEN hoặc CORS_ALLOWED_ORIGINS, báo lỗi rõ ràng.
    @property
    def ADMIN_USERNAME(self) -> str:
        val = os.getenv("ADMIN_USERNAME")
        if not val:
            if self.IS_DEVELOPMENT:
                return "admin_dev"
            raise RuntimeError(
                "Lỗi cấu hình bảo mật: Trong môi trường ngoài development (staging/preview/production), "
                "bắt buộc phải cấu hình ADMIN_USERNAME qua biến môi trường."
            )
        return val

    @property
    def ADMIN_PASSWORD(self) -> str:
        val = os.getenv("ADMIN_PASSWORD")
        if not val:
            if self.IS_DEVELOPMENT:
                return "huit-dev-secret-change-in-production-2026!"
            raise RuntimeError(
                "Lỗi cấu hình bảo mật: Trong môi trường ngoài development (staging/preview/production), "
                "bắt buộc phải cấu hình ADMIN_PASSWORD qua biến môi trường."
            )
        return val

    @property
    def ADMIN_TOKEN(self) -> str:
        val = os.getenv("ADMIN_TOKEN")
        if not val:
            if self.IS_DEVELOPMENT:
                return "huit-dev-token-change-in-production-2026!"
            raise RuntimeError(
                "Lỗi cấu hình bảo mật: Trong môi trường ngoài development (staging/preview/production), "
                "bắt buộc phải cấu hình ADMIN_TOKEN qua biến môi trường."
            )
        return val

    def validate_security_config(self) -> None:
        """Kiểm tra cấu hình bảo mật khi khởi động ứng dụng."""
        if not self.IS_DEVELOPMENT:
            _ = self.ADMIN_USERNAME
            _ = self.ADMIN_PASSWORD
            _ = self.ADMIN_TOKEN
            _ = self.CORS_ALLOWED_ORIGINS
            if self.STORAGE_BACKEND in ("s3", "r2", "minio"):
                if not (self.STORAGE_ENDPOINT and self.STORAGE_ACCESS_KEY and self.STORAGE_SECRET_KEY):
                    raise RuntimeError(
                        "Lỗi cấu hình lưu trữ: STORAGE_BACKEND được cấu hình là object storage "
                        "nhưng thiếu STORAGE_ENDPOINT, STORAGE_ACCESS_KEY hoặc STORAGE_SECRET_KEY."
                    )

    # Distributed Infrastructure Configuration
    @property
    def STORAGE_BACKEND(self) -> str:
        return os.getenv("STORAGE_BACKEND", "local").strip().lower()

    @property
    def STORAGE_ROOT(self) -> Path:
        raw = os.getenv("STORAGE_ROOT", "").strip()
        return Path(raw).resolve() if raw else (self.DATA_DIR / "artifacts_store").resolve()

    @property
    def STORAGE_ENDPOINT(self) -> str:
        return os.getenv("STORAGE_ENDPOINT", "").strip()

    @property
    def STORAGE_ACCESS_KEY(self) -> str:
        return os.getenv("STORAGE_ACCESS_KEY", "").strip()

    @property
    def STORAGE_SECRET_KEY(self) -> str:
        return os.getenv("STORAGE_SECRET_KEY", "").strip()

    @property
    def STORAGE_BUCKET(self) -> str:
        return os.getenv("STORAGE_BUCKET", "huit-chatbot-artifacts").strip()

    @property
    def STORAGE_REGION(self) -> str:
        return os.getenv("STORAGE_REGION", "ap-southeast-1").strip()

    @property
    def STORAGE_USE_SSL(self) -> bool:
        return os.getenv("STORAGE_USE_SSL", "true").strip().lower() in ("true", "1", "yes")

    @property
    def RATE_LIMIT_REDIS_URL(self) -> str:
        return os.getenv("RATE_LIMIT_REDIS_URL", "").strip()

    @property
    def REDIS_URL(self) -> str:
        """URL Redis dùng chung khi không tách database cho rate-limit và stream resume."""
        return os.getenv("REDIS_URL", "").strip()

    @property
    def QUEUE_PROVIDER(self) -> str:
        return os.getenv("QUEUE_PROVIDER", "mongo").strip().lower()

    @property
    def QUEUE_LEASE_SECONDS(self) -> int:
        return int(os.getenv("QUEUE_LEASE_SECONDS", "120"))

    @property
    def STREAM_RESUME_REDIS_URL(self) -> str:
        return os.getenv("STREAM_RESUME_REDIS_URL", "").strip()

    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
    CACHE_TTL_HOURS: int = int(os.getenv("CACHE_TTL_HOURS", "24"))

    # Paths to JSON configs (Chỉ đọc từ data/ hoặc backend/app/resources/)
    def get_data_file(self, filename: str) -> Path:
        for candidate in [DATA_DIR / filename, APP_DIR / "resources" / filename, APP_DIR / filename]:
            if candidate.exists():
                return candidate
        return DATA_DIR / filename

    @property
    def RETRIEVAL_MODULE_PATH(self) -> Path:
        return self.get_data_file("huit_semantic_search.module.json")

    @property
    def RAG_MODULE_PATH(self) -> Path:
        return self.get_data_file("huit_rag_answer.module.json")

    @property
    def CLUSTERS_PATH(self) -> Path:
        return self.get_data_file("huit_cluster_centroids.json")

    @property
    def ADMISSION_VISUALS_PATH(self) -> Path:
        return self.get_data_file("admission_visuals_bundle.json")

settings = Settings()
