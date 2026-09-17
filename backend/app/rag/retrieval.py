import re
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from backend.app.config import settings
from backend.app.data_access.operations import rag_operations
from backend.app.rag.intent import normalize_text, candidate_id
from backend.app.rag.embedding import EmbeddingManager

import logging

logger = logging.getLogger("huit_chatbot.rag.retrieval")

class HybridRetriever:
    @classmethod
    def get_top_cluster(cls, qv: List[float]) -> Optional[int]:
        centroids_data = EmbeddingManager.get_cluster_centroids()
        if not centroids_data or "clusters" not in centroids_data or not qv:
            return None
        try:
            qv_arr = np.array(qv, dtype=np.float32)
            qv_norm = np.linalg.norm(qv_arr)
            best_sim = -1.0
            top_cluster_id = None
            for cid_str, cinfo in centroids_data["clusters"].items():
                c_arr = np.array(cinfo["centroid"], dtype=np.float32)
                c_norm = np.linalg.norm(c_arr)
                if qv_norm > 0 and c_norm > 0:
                    sim = float(np.dot(qv_arr, c_arr) / (qv_norm * c_norm))
                    if sim > best_sim:
                        best_sim = sim
                        top_cluster_id = int(cid_str)
            return top_cluster_id
        except Exception as e:
            logger.warning("Cluster matching warning: %s", type(e).__name__)
            return None

    @classmethod
    def search_vector(cls, qv: List[float]) -> List[dict]:
        try:
            return rag_operations.execute_vector_search(query_vector=qv, limit=15, num_candidates=200)
        except Exception as e:
            logger.warning("Vector search retrieve warning: %s", type(e).__name__)
            return []

    @classmethod
    def search_keyword(cls, question: str) -> List[dict]:
        try:
            words = [w.strip() for w in re.split(r'[\s,\?\.\-\(\)]+', question) if len(w.strip()) >= 2]
            stop_words = {"cho", "các", "của", "với", "như", "nào", "bao", "nhiêu", "trường", "huit", "ngành", "được", "không"}
            keywords = [w for w in words if w.lower() not in stop_words or w.isdigit()]
            if not keywords:
                return []
            raw_kw = rag_operations.execute_keyword_search(keywords=keywords, limit=20)
            normalized_terms = {
                normalize_text(word)
                for word in keywords
                if len(normalize_text(word)) >= 3
            }
            raw_kw.sort(
                key=lambda item: sum(
                    1
                    for term in normalized_terms
                    if term in normalize_text(
                        f"{item.get('title', '')} {item.get('text', '')}"
                    )
                ),
                reverse=True,
            )
            raw_kw = raw_kw[:20]
            # Loại bỏ các nội dung spam hoặc rác nếu có
            return [d for d in raw_kw if "Di động Máy tính bảng" not in d.get("text", "") and "Pick the Right" not in d.get("text", "")]
        except Exception as e:
            logger.warning("Keyword search retrieve warning: %s", type(e).__name__)
            return []


