"""
redaction.py
Bảo vệ quyền riêng tư và khử thông tin nhạy cảm trước khi gửi dữ liệu tới Decision Engine.
Tuyệt đối không lưu raw state hoặc raw question vào MongoDB hoặc log.
"""
import hashlib
import json
import re
from typing import Any, Dict, List, Optional


# Các biểu thức chính quy nhận diện PII và thông tin nhạy cảm
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
PHONE_VN_PATTERN = re.compile(
    r"(?:\+84|84|0)(?:3[2-9]|5[689]|7[06-9]|8[1-9]|9[0-9])\d{7}\b"
)
PHONE_GENERIC_PATTERN = re.compile(
    r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)
# CCCD (12 chữ số) hoặc CMND (9 chữ số)
NATIONAL_ID_PATTERN = re.compile(r"\b(?:\d{12}|\d{9})\b")
# MongoDB URI
MONGO_URI_PATTERN = re.compile(r"mongodb(?:\+srv)?://[^\s\"']+")
# JWT / Bearer Access Tokens
BEARER_TOKEN_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
JWT_TOKEN_PATTERN = re.compile(r"\beyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\b")
# Known API Keys (OpenAI, Google, GitHub, TypeSafe, etc.)
KNOWN_API_KEY_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z-_]{35}|ghp_[A-Za-z0-9]{36}|apikey_[A-Za-z0-9_]{20,})\b"
)
# Password / Credentials / Secrets assignments
CREDENTIAL_ASSIGN_PATTERN = re.compile(
    r"(?i)\b(?:api[_\s-]?key|secret[_\s-]?key|admin[_\s-]?token|access[_\s-]?token|bearer[_\s-]?token|password|passwd|pwd|csrf[_\s-]?token|session[_\s-]?id)\s*[:=]\s*['\"]?[^\s,;'\"]{6,}['\"]?"
)


def redact_text(text: Optional[str]) -> str:
    """Loại bỏ triệt để các dữ liệu nhạy cảm (PII, credentials, tokens, URIs) khỏi chuỗi."""
    if not text:
        return ""
    result = str(text)
    result = MONGO_URI_PATTERN.sub("[REDACTED_MONGODB_URI]", result)
    result = BEARER_TOKEN_PATTERN.sub("[REDACTED_TOKEN]", result)
    result = JWT_TOKEN_PATTERN.sub("[REDACTED_TOKEN]", result)
    result = KNOWN_API_KEY_PATTERN.sub("[REDACTED_KEY]", result)
    result = CREDENTIAL_ASSIGN_PATTERN.sub("[REDACTED_SECRET]", result)
    result = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", result)
    result = NATIONAL_ID_PATTERN.sub("[REDACTED_ID]", result)
    result = PHONE_VN_PATTERN.sub("[REDACTED_PHONE]", result)
    result = PHONE_GENERIC_PATTERN.sub("[REDACTED_PHONE]", result)
    return result


def anonymize_request_hash(data: str) -> str:
    """Tạo hash ẩn danh 16 ký tự phục vụ metric / telemetry mà không lưu raw text."""
    return hashlib.sha256(data.encode("utf-8", errors="ignore")).hexdigest()[:16]


def build_intent_decision_state(
    question: str,
    current_intent: str,
    max_bytes: int = 8192
) -> str:
    """Xây dựng state tối thiểu cho tác vụ phân loại Intent:

    - Không chứa lịch sử chat
    - Câu hỏi đã được làm sạch và redacted
    - Giới hạn kích thước tối đa max_bytes
    """
    cleaned_q = redact_text(question.strip())
    state_payload = {
        "task": "intent_classification",
        "question": cleaned_q,
        "preliminary_intent": current_intent or "general",
    }
    encoded = json.dumps(state_payload, ensure_ascii=False)
    # Cắt ngắn nếu vượt quá max_bytes
    if len(encoded.encode("utf-8")) > max_bytes:
        excess = len(encoded.encode("utf-8")) - max_bytes
        truncated_q = cleaned_q[:-max(1, excess + 10)]
        state_payload["question"] = truncated_q
        encoded = json.dumps(state_payload, ensure_ascii=False)
    return encoded


def build_evidence_decision_state(
    question: str,
    docs: List[Dict[str, Any]],
    max_bytes: int = 8192
) -> str:
    """Xây dựng state tối thiểu cho tác vụ đánh giá Tính đầy đủ của minh chứng (Evidence Sufficiency):

    - Chỉ trích xuất metadata và đoạn trích ngắn (excerpt) đã redacted
    - Không gửi toàn bộ dữ liệu thô
    - Giới hạn kích thước tối đa max_bytes
    """
    cleaned_q = redact_text(question.strip())
    evidence_items = []

    for i, doc in enumerate(docs[:3], 1):
        if not isinstance(doc, dict):
            continue
        title = redact_text(str(doc.get("title", "")).strip())
        category = str(doc.get("category", "general"))
        year = doc.get("year")
        score = round(float(doc.get("score", 0.0)), 3)
        raw_text = str(doc.get("text", "")).strip()
        excerpt = redact_text(raw_text[:250])

        evidence_items.append({
            "idx": i,
            "title": title[:100],
            "category": category,
            "year": year,
            "score": score,
            "excerpt": excerpt,
        })

    state_payload = {
        "task": "evidence_sufficiency_evaluation",
        "question": cleaned_q,
        "evidence_count": len(evidence_items),
        "evidence": evidence_items,
    }

    encoded = json.dumps(state_payload, ensure_ascii=False)
    while len(encoded.encode("utf-8")) > max_bytes and evidence_items:
        # Cắt ngắn từng excerpt nếu vượt byte limit
        for item in evidence_items:
            item["excerpt"] = item["excerpt"][: len(item["excerpt"]) // 2]
        encoded = json.dumps(state_payload, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > max_bytes:
            evidence_items.pop()
            state_payload["evidence"] = evidence_items
            encoded = json.dumps(state_payload, ensure_ascii=False)

    return encoded
