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


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Cắt chuỗi an toàn theo byte UTF-8 mà không làm gãy ký tự đa byte."""
    if not text:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def create_canonical_evidence_bundle(
    docs: List[Dict[str, Any]],
    max_docs: int = 3,
    max_excerpt_chars: int = 500
) -> List[Dict[str, Any]]:
    """Tạo Evidence Bundle chuẩn hóa dùng chung cho cả JEV Decision Engine và ngữ cảnh LLM.
    
    Bảo đảm:
    - Che dữ liệu nhạy cảm (PII/secrets) trên toàn bộ văn bản TRƯỚC KHI cắt đoạn trích (excerpt).
    - Giữ trọn vẹn metadata: url, source_url, year, category, effective_date, major_code nếu có trong nguồn.
    - Không tự bịa đặt URL, năm hay số liệu tuyển sinh khi dữ liệu gốc không có.
    """
    items = []
    if not docs:
        return items

    for i, doc in enumerate(docs[:max_docs], 1):
        if not isinstance(doc, dict):
            continue
        raw_text = str(doc.get("text", "")).strip()
        redacted_full_text = redact_text(raw_text)
        excerpt = redacted_full_text[:max_excerpt_chars] if redacted_full_text else ""
        
        raw_title = str(doc.get("title", "")).strip()
        title = redact_text(raw_title)[:120] if raw_title else "Tài liệu chính thức"
        
        item = {
            "idx": i,
            "doc_id": str(doc.get("chunk_id") or doc.get("_id") or doc.get("id") or f"doc_{i}"),
            "chunk_id": doc.get("chunk_id"),
            "title": title,
            "category": str(doc.get("category", "general")),
            "year": doc.get("year"),
            "url": doc.get("source_url") or doc.get("url") or "",
            "page_number": doc.get("page_number") or doc.get("page"),
            "sku": doc.get("sku") or doc.get("model") or doc.get("major_code"),
            "score": round(float(doc.get("score", 0.0)), 3),
            "major_code": doc.get("major_code"),
            "product_type": doc.get("product_type"),
            "verification_status": doc.get("verification_status"),
            "effective_date": doc.get("effective_date") or doc.get("valid_from") or None,
            "excerpt": excerpt,
        }
        items.append(item)

    return items


def build_intent_decision_state(
    question: str,
    current_intent: str,
    max_bytes: int = 8192
) -> str:
    """Xây dựng state tối thiểu cho tác vụ phân loại Intent:

    - Không chứa lịch sử chat
    - Câu hỏi đã được làm sạch và redacted
    - Giới hạn kích thước tối đa max_bytes và bảo toàn UTF-8
    """
    cleaned_q = redact_text(question.strip())
    state_payload = {
        "task": "intent_classification",
        "question": cleaned_q,
        "preliminary_intent": current_intent or "general",
    }
    encoded = json.dumps(state_payload, ensure_ascii=False)
    # Cắt ngắn nếu vượt quá max_bytes
    while len(encoded.encode("utf-8")) > max_bytes:
        excess = len(encoded.encode("utf-8")) - max_bytes
        q_bytes = len(state_payload["question"].encode("utf-8"))
        target_bytes = max(30, q_bytes - excess - 20)
        state_payload["question"] = _truncate_utf8(state_payload["question"], target_bytes)
        encoded = json.dumps(state_payload, ensure_ascii=False)
        if target_bytes <= 30:
            break
    return encoded


def build_evidence_decision_state(
    question: str,
    docs: List[Dict[str, Any]],
    max_bytes: int = 8192
) -> str:
    """Xây dựng state tối thiểu cho tác vụ đánh giá Tính đầy đủ của minh chứng (Evidence Sufficiency):

    - Sử dụng evidence bundle chuẩn hóa đã redacted toàn diện trước khi trích xuất
    - Luôn đồng bộ evidence_count với số phần tử thực tế trong mảng evidence
    - Tuyệt đối không vượt quá max_bytes kể cả khi question dài bất thường (>10.000 ký tự)
    """
    cleaned_q = redact_text(question.strip())
    # Nếu câu hỏi quá dài, giới hạn trước một nửa ngân sách để dành chỗ cho evidence
    q_budget = max(256, max_bytes // 3)
    if len(cleaned_q.encode("utf-8")) > q_budget:
        cleaned_q = _truncate_utf8(cleaned_q, q_budget)

    evidence_items = create_canonical_evidence_bundle(docs, max_docs=3, max_excerpt_chars=300)

    state_payload = {
        "task": "evidence_sufficiency_evaluation",
        "question": cleaned_q,
        "evidence_count": len(evidence_items),
        "evidence": evidence_items,
    }

    encoded = json.dumps(state_payload, ensure_ascii=False)

    while len(encoded.encode("utf-8")) > max_bytes:
        if evidence_items:
            # Ưu tiên rút ngắn excerpt của các tài liệu
            shortened = False
            for item in evidence_items:
                if len(item["excerpt"]) > 60:
                    item["excerpt"] = item["excerpt"][: len(item["excerpt"]) // 2]
                    shortened = True
            if not shortened:
                # Nếu không thể rút ngắn thêm, pop tài liệu cuối cùng
                evidence_items.pop()
            state_payload["evidence"] = evidence_items
            state_payload["evidence_count"] = len(evidence_items)
            encoded = json.dumps(state_payload, ensure_ascii=False)
        else:
            # Đã xóa hết evidence nhưng vẫn vượt max_bytes do question, cắt bớt question
            excess = len(encoded.encode("utf-8")) - max_bytes
            current_q = state_payload["question"]
            q_bytes = len(current_q.encode("utf-8"))
            target_bytes = max(30, q_bytes - excess - 20)
            state_payload["question"] = _truncate_utf8(current_q, target_bytes)
            state_payload["evidence_count"] = 0
            state_payload["evidence"] = []
            encoded = json.dumps(state_payload, ensure_ascii=False)
            if target_bytes <= 30:
                break

    return encoded

