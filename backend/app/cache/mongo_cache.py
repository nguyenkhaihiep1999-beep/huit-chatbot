import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from backend.app.config import settings
from backend.app.cache.memory_cache import MemoryCache, compute_cache_key
from backend.app.data_access.operations import cache_operations
from backend.app.rag.intent import normalize_text

class CacheManager:
    @staticmethod
    def get_cached_response(question: str, chat_history: Optional[List[dict]] = None) -> Optional[Dict[str, Any]]:
        ckey = compute_cache_key(question, chat_history)
        
        # 1. Kiểm tra RAM Cache tức thì (0ms)
        ram_item = MemoryCache.get(ckey)
        if ram_item:
            ram_item["cached"] = True
            if "meta" not in ram_item or not isinstance(ram_item["meta"], dict):
                ram_item["meta"] = {}
            ram_item["meta"]["ram_cached"] = True
            return ram_item

        # 2. Fallback sang MongoDB Cache nếu RAM cache miss
        try:
            now = datetime.now(timezone.utc)
            cached = cache_operations.get_cached_query_response(ckey, current_time=now)
            if cached:
                vis = cached.get("visual") or (cached.get("meta", {}).get("visual") if isinstance(cached.get("meta"), dict) else None)
                meta_obj = cached.get("meta", {})
                if not isinstance(meta_obj, dict):
                    meta_obj = {}
                if vis:
                    meta_obj["visual"] = vis
                res = {
                    "answer": cached["answer"],
                    "sources": cached.get("sources", []),
                    "trace": cached.get("trace", []),
                    "visual": vis,
                    "cached": True,
                    "meta": meta_obj,
                }
                # Lưu ngược lại RAM Cache để các request sau đạt 0ms
                MemoryCache.set(ckey, res)
                return res
        except Exception:
            pass
        return None

    @staticmethod
    def save_response(question: str, response_data: Dict[str, Any], chat_history: Optional[List[dict]] = None) -> None:
        if not response_data or not response_data.get("answer"):
            return
        ckey = compute_cache_key(question, chat_history)
        
        # Đảm bảo response_data có meta an toàn
        if "meta" not in response_data or not isinstance(response_data["meta"], dict):
            response_data["meta"] = {}

        # 1. Lưu RAM Cache
        MemoryCache.set(ckey, response_data)

        # 2. Lưu MongoDB Persistent Cache (chỉ lưu hash & độ dài, bảo vệ quyền riêng tư)
        try:
            import hashlib
            q_hash = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()
            now = datetime.now(timezone.utc)
            cache_operations.upsert_cached_query_response(
                cache_key=ckey,
                question_clean=normalize_text(question),
                question_hash=q_hash,
                question_len=len(question),
                answer=response_data["answer"],
                sources=response_data.get("sources", []),
                trace=response_data.get("trace", []),
                meta=response_data.get("meta", {}),
                kb_version=settings.KB_VERSION,
                rag_version=settings.RAG_VERSION,
                model=settings.OPENROUTER_MODEL,
                updated_at=now,
                expires_at=now + timedelta(hours=settings.CACHE_TTL_HOURS),
            )
        except Exception:
            pass

    @staticmethod
    def clear_all_cache() -> Dict[str, int]:
        ram_cleared = MemoryCache.clear()
        mongo_cleared = 0
        try:
            mongo_cleared = cache_operations.clear_mongo_cache()
        except Exception:
            pass
        return {"ram_cleared": ram_cleared, "mongo_cleared": mongo_cleared}

