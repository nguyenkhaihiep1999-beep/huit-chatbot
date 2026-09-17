import os
import sys
from pathlib import Path

# Thêm root directory vào sys.path để Vercel Python Runtime tìm thấy package 'backend'
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Đảm bảo môi trường Vercel nhận diện APP_ENV
os.environ.setdefault("APP_ENV", os.getenv("VERCEL_ENV", "development"))

from backend.app.main import app

# Export app instance cho Vercel Serverless ASGI Handler
app = app
