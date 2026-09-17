import json
import time
import copy
import hashlib
from typing import Optional, Dict, Any
from backend.app.config import settings
from backend.app.rag.intent import normalize_text

def compute_cache_key(question: str, chat_history: Optional[list] = None) -> str:
    relevant_history = []
    if isinstance(chat_history, list):
        for turn in chat_history[-4:]:
            if isinstance(turn, dict):
                relevant_history.append({
                    "role": turn.get("role"),
                    "content": str(turn.get("content", ""))[:500],
                })
    payload = json.dumps(
        {
            "question": normalize_text(question),
            "history": relevant_history,
            "kb_version": settings.KB_VERSION,
            "rag_version": settings.RAG_VERSION,
            "model": settings.OPENROUTER_MODEL,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

class MemoryCache:
    _ram_cache: Dict[str, Any] = {}
    _ram_cache_expiry: Dict[str, float] = {}

    @classmethod
    def get(cls, key: str) -> Optional[Dict[str, Any]]:
        now_ts = time.time()
        if key in cls._ram_cache and cls._ram_cache_expiry.get(key, 0) > now_ts:
            return copy.deepcopy(cls._ram_cache[key])
        return None

    @classmethod
    def set(cls, key: str, value: Dict[str, Any], ttl_hours: Optional[int] = None) -> None:
        ttl = ttl_hours if ttl_hours is not None else settings.CACHE_TTL_HOURS
        now_ts = time.time()
        cls._ram_cache[key] = copy.deepcopy(value)
        cls._ram_cache_expiry[key] = now_ts + (ttl * 3600)

    @classmethod
    def clear(cls) -> int:
        count = len(cls._ram_cache)
        cls._ram_cache.clear()
        cls._ram_cache_expiry.clear()
        return count

    @classmethod
    def count(cls) -> int:
        now_ts = time.time()
        return sum(1 for k, exp in cls._ram_cache_expiry.items() if exp > now_ts)
