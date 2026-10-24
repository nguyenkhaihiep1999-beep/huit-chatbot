import json
import time
import copy
import hashlib
from typing import Optional, Dict, Any
from backend.app.config import settings
from backend.app.rag.intent import normalize_text

def compute_cache_key(
    question: str,
    chat_history: Optional[list] = None,
    profile_id: Optional[str] = None,
) -> str:
    from backend.app.rag.profile import get_profile

    prof = get_profile(profile_id)
    relevant_history = []
    if isinstance(chat_history, list):
        for turn in chat_history[-4:]:
            if isinstance(turn, dict):
                relevant_history.append({
                    "role": turn.get("role"),
                    "content": str(turn.get("content", ""))[:500],
                })

    active_model = (
        getattr(settings, "QWEN_MODEL", "qwen-2.5-72b-instruct")
        if getattr(settings, "PRIMARY_LLM_PROVIDER", "gemini") == "qwen"
        else settings.GEMINI_MODEL
    )

    if prof.id == "huit":
        cache_identity = {
            "question": normalize_text(question),
            "history": relevant_history,
            "kb_version": prof.kb_version,
            "rag_version": prof.rag_version,
            "model": settings.OPENROUTER_MODEL,
        }
        # Assist can change routing and the LLM context. Keep its answers isolated
        # without deleting legacy cache entries; off/shadow retain their old keys.
        if prof.jev_intent_mode == "assist" or prof.jev_evidence_mode == "assist" or settings.JEV_MODE == "assist":
            cache_identity["jev_assist"] = {
                "policy_version": "1",
                "model": settings.JEV_MODEL,
                "confidence_threshold": settings.JEV_CONFIDENCE_THRESHOLD,
            }
    else:
        cache_identity = {
            "profile": prof.id,
            "question": normalize_text(question),
            "history": relevant_history,
            "kb_version": prof.kb_version,
            "rag_version": prof.rag_version,
            "model": active_model,
            "jev_intent_mode": prof.jev_intent_mode,
            "jev_evidence_mode": prof.jev_evidence_mode,
            "cluster_prefilter": prof.enable_cluster_prefilter,
        }
        if prof.jev_intent_mode == "assist" or prof.jev_evidence_mode == "assist":
            cache_identity["jev_assist"] = {
                "policy_version": "2",
                "model": settings.JEV_MODEL,
                "confidence_threshold": settings.JEV_CONFIDENCE_THRESHOLD,
            }

    payload = json.dumps(
        cache_identity,
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
