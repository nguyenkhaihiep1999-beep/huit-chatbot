import os
import json
import tempfile
from typing import Optional, List
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

class EmbeddingManager:
    _embedder = None
    _cluster_centroids = None

    @classmethod
    def get_embedder(cls):
        if cls._embedder is None:
            try:
                from fastembed import TextEmbedding
                cache_path = os.environ.get("FASTEMBED_CACHE_DIR", os.path.join(_tmp_dir, "fastembed_cache"))
                os.makedirs(cache_path, exist_ok=True)
                cls._embedder = TextEmbedding(settings.EMBEDDING_MODEL, cache_dir=cache_path)
            except Exception as e:
                print("FastEmbed init warning (falling back to MongoDB keyword search):", e)
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
            print("Embedding generation error:", e)
            return None

    @classmethod
    def get_cluster_centroids(cls) -> Optional[dict]:
        if cls._cluster_centroids is None:
            path = settings.CLUSTERS_PATH
            if path.exists():
                try:
                    with open(path, encoding="utf-8") as f:
                        cls._cluster_centroids = json.load(f)
                except Exception as e:
                    print("Centroids load warning:", e)
        return cls._cluster_centroids
