from unittest.mock import patch

from backend.app.config import settings
from backend.app.rag.embedding import EmbeddingManager


def test_disabled_local_embeddings_skip_fastembed_import(monkeypatch):
    """Container RAM thấp phải hạ cấp an toàn mà không tải model local."""
    monkeypatch.setenv("ENABLE_LOCAL_EMBEDDINGS", "false")
    previous = EmbeddingManager._embedder
    EmbeddingManager._embedder = None
    try:
        with patch("builtins.__import__", wraps=__import__) as import_spy:
            assert settings.ENABLE_LOCAL_EMBEDDINGS is False
            assert EmbeddingManager.get_embedder() is None
            imported_modules = [call.args[0] for call in import_spy.call_args_list if call.args]
            assert "fastembed" not in imported_modules
    finally:
        EmbeddingManager._embedder = previous


def test_local_embeddings_enabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_LOCAL_EMBEDDINGS", raising=False)
    assert settings.ENABLE_LOCAL_EMBEDDINGS is True
