import os
import json
import logging
import tempfile
from typing import Optional, List, Dict, Any, Union
import numpy as np
from backend.app.config import settings

# Thiết lập thư mục cache FastEmbed & Torch
_tmp_dir = tempfile.gettempdir()
os.environ.setdefault("HF_HOME", os.path.join(_tmp_dir, "huggingface"))
os.environ.setdefault("HF_HUB_CACHE", os.path.join(_tmp_dir, "huggingface", "hub"))
os.environ.setdefault("FASTEMBED_CACHE_DIR", os.path.join(_tmp_dir, "fastembed_cache"))
os.environ.setdefault("XDG_CACHE_HOME", os.path.join(_tmp_dir, "cache"))
os.environ.setdefault("TORCH_HOME", os.path.join(_tmp_dir, "torch"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

logger = logging.getLogger("huit_chatbot.embedding")

class EmbeddingManager:
    _embedder = None
    _cluster_centroids = None
    _cluster_centroids_by_profile = {}

    @classmethod
    def get_embedder(cls):
        if not settings.ENABLE_LOCAL_EMBEDDINGS:
            if cls._embedder is not False:
                logger.info(
                    "Local embeddings disabled; using MongoDB keyword-search fallback"
                )
                cls._embedder = False
            return None

        if cls._embedder is None:
            try:
                from fastembed import TextEmbedding
                cache_path = os.environ.get("FASTEMBED_CACHE_DIR", os.path.join(_tmp_dir, "fastembed_cache"))
                os.makedirs(cache_path, exist_ok=True)
                cls._embedder = TextEmbedding(settings.EMBEDDING_MODEL, cache_dir=cache_path)
            except Exception as e:
                logger.warning(
                    "FastEmbed init failed; using MongoDB keyword-search fallback (%s)",
                    type(e).__name__,
                )
                cls._embedder = False
        return cls._embedder if cls._embedder is not False else None

    @classmethod
    def embed_query(cls, text: str) -> Optional[List[float]]:
        embedder = cls.get_embedder()
        if embedder is None:
            return None
        try:
            # Chuẩn e5 cần prefix "query: "
            qv_list = list(embedder.embed([f"query: {text}"]))[0].tolist()
            return qv_list
        except Exception as e:
            logger.warning("Embedding generation failed (%s)", type(e).__name__)
    @classmethod
    def embed_documents(cls, texts: List[str], batch_size: int = 1) -> List[List[float]]:
        embedder = cls.get_embedder()
        if embedder is None:
            raise RuntimeError("Embedder is not available")
        results = []
        for i in range(0, len(texts), 16):
            chunk_slice = texts[i : i + 16]
            passages = [f"passage: {t}" for t in chunk_slice]
            for v in embedder.embed(passages, batch_size=batch_size):
                results.append(v.tolist())
        return results

    @classmethod
    def get_cluster_centroids(
        cls,
        profile_id: Optional[str] = None,
        clusters_path: Optional[Any] = None,
    ) -> Optional[dict]:
        """Lấy cluster centroids theo profile độc lập, tránh dùng nhầm centroids khi đổi profile."""
        from backend.app.rag.profile import get_profile

        target_profile = get_profile(profile_id)
        prof_id = target_profile.id

        if prof_id in cls._cluster_centroids_by_profile:
            return cls._cluster_centroids_by_profile[prof_id]

        path = clusters_path or target_profile.clusters_path
        centroids = None
        if path and hasattr(path, "exists") and path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    centroids = json.load(f)
            except Exception as e:
                logger.warning("Centroids load warning for profile %s: %s", prof_id, e)

        cls._cluster_centroids_by_profile[prof_id] = centroids
        if prof_id == "huit":
            cls._cluster_centroids = centroids
        return centroids

    @classmethod
    def invalidate_centroids_cache(cls, profile_id: Optional[str] = None) -> None:
        """Xóa cache centroids khi chuyển profile hoặc cập nhật cluster mới."""
        if profile_id:
            cls._cluster_centroids_by_profile.pop(profile_id, None)
            if profile_id == "huit":
                cls._cluster_centroids = None
        else:
            cls._cluster_centroids_by_profile.clear()
            cls._cluster_centroids = None
