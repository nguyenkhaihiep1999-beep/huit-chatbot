"""
evidence_policy.py
Chính sách đánh giá minh chứng (Evidence Evaluation Policy) cho Chatbot Tuyển sinh HUIT.

Quy định hành động:
- Sufficient: Đầy đủ căn cứ -> sinh câu trả lời bám sát nguồn, trích dẫn [n].
- Partial: Đủ một phần -> trả lời phần có căn cứ và chỉ rõ phần còn thiếu trong kho tri thức.
- Clarification: Thiếu thông tin từ người hỏi (ví dụ hỏi "ngành này" nhưng không nêu tên ngành) -> hỏi lại 1 câu cụ thể.
- Insufficient / Conflicting do nguồn: kích hoạt truy xuất bổ sung tối đa 1 lượt trong ngân sách.
  Nếu sau bổ sung vẫn thiếu/mâu thuẫn -> nói rõ chưa xác minh được, không suy đoán số liệu.
- Theo dõi minh chứng riêng cho từng ý đối với câu hỏi nhiều ý.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
import re
from backend.app.rag.intent import (
    normalize_text,
    extract_admission_entities,
    decompose_sub_intents,
    MAJOR_KEYWORDS_MAP,
)



@dataclass
class SubClaimEvidence:
    intent: str
    topic: str
    year: Optional[int]
    major: Optional[str]
    status: str  # "sufficient", "partial", "missing"
    matching_doc_indices: List[int] = field(default_factory=list)
    reason: str = ""


@dataclass
class PolicyVerdict:
    verdict: str  # "sufficient", "partial", "clarification", "insufficient", "conflicting"
    can_answer: bool
    needs_supplementary: bool
    supplementary_query: Optional[str]
    clarification_prompt: Optional[str]
    evidence_guidance: str
    sub_claims: List[SubClaimEvidence] = field(default_factory=list)
    missing_aspects: List[str] = field(default_factory=list)
    supported_aspects: List[str] = field(default_factory=list)
    conflict_details: Optional[str] = None


class EvidencePolicyEvaluator:
    @classmethod
    def evaluate(
        cls,
        question: str,
        docs: List[Dict[str, Any]],
        intent: str,
        entities: Optional[Dict[str, Any]] = None,
        jev_sufficiency: Optional[str] = None,
        jev_confidence: Optional[float] = None,
        current_retrieval_round: int = 1,
        max_retrieval_rounds: int = 2,
        profile: Optional[Any] = None,
        jev_mode: Optional[str] = None,
    ) -> PolicyVerdict:
        """Đánh giá toàn diện minh chứng và đưa ra phán quyết hành động.
        
        Quy tắc bất biến (Shadow Mode Invariance):
        Khi jev_mode là 'shadow' (hoặc 'off'), Jev kết quả tuyệt đối KHÔNG được tác động
        đến policy_verdict, guidance, prompts hoặc retrieval.
        """
        from backend.app.rag.profile import get_profile

        active_profile = profile if profile is not None else get_profile()
        prof_name = active_profile.name
        prof_contact = active_profile.official_contact

        # Shadow mode invariance: Tuyệt đối không thay đổi verdict khi shadow
        effective_jev_sufficiency = jev_sufficiency if jev_mode == "assist" else None

        if entities is None:
            entities = extract_admission_entities(question)

        # 1. Kiểm tra thiếu thông tin từ phía người hỏi (Clarification)
        if entities.get("missing_user_info") and entities.get("clarification_prompt"):
            return PolicyVerdict(
                verdict="clarification",
                can_answer=False,
                needs_supplementary=False,
                supplementary_query=None,
                clarification_prompt=entities["clarification_prompt"],
                evidence_guidance="Người dùng chưa cung cấp đủ thông tin cụ thể (ví dụ ngành học, mã SKU hoặc thông số). Cần hỏi lại làm rõ.",
            )

        # 2. Trường hợp không có tài liệu nào được tìm thấy
        if not docs:
            can_retry = current_retrieval_round < max_retrieval_rounds
            return PolicyVerdict(
                verdict="insufficient",
                can_answer=False,
                needs_supplementary=can_retry,
                supplementary_query=cls._build_fallback_query(question, entities, profile=active_profile),
                clarification_prompt=None,
                evidence_guidance=f"Không tìm thấy tài liệu phù hợp trong kho tri thức chính thức của {prof_name}.",
                missing_aspects=["toàn bộ thông tin câu hỏi"],
            )

        # 3. Phân tách và đánh giá minh chứng theo từng ý con (Multi-part claim tracking)
        sub_tasks = decompose_sub_intents(question, entities)
        sub_claims: List[SubClaimEvidence] = []
        supported_aspects = []
        missing_aspects = []

        for task in sub_tasks:
            t_intent = task["intent"]
            t_topic = task["topic"]
            t_year = task["year"]
            t_major = task["major"]
            t_major_code = task.get("major_code")

            major_aliases = [normalize_text(t_major)] if t_major else []
            if t_major_code:
                for code, c_name, aliases in MAJOR_KEYWORDS_MAP:
                    if code == t_major_code:
                        major_aliases.extend([normalize_text(a) for a in aliases])
                        break

            matching_indices = []
            for i, doc in enumerate(docs, 1):
                doc_text = (str(doc.get("title", "")) + " " + str(doc.get("text", ""))).lower()
                doc_cat = doc.get("category", "")
                doc_year = doc.get("year")
                norm_doc_text = normalize_text(doc_text)

                # Kiểm tra độ khớp intent/chủ đề
                intent_match = (doc_cat == t_intent) or (t_intent in norm_doc_text)
                
                # Kiểm tra năm nếu câu hỏi yêu cầu năm cụ thể
                year_match = True
                if t_year and doc_year:
                    year_match = (doc_year == t_year)
                elif t_year and not doc_year:
                    year_match = (str(t_year) in doc_text)

                # Kiểm tra ngành nếu có
                major_match = True
                if t_major:
                    major_match = any(alias in norm_doc_text for alias in major_aliases) or (bool(t_major_code) and t_major_code in norm_doc_text)

                if intent_match and major_match and year_match:
                    matching_indices.append(i)


            if matching_indices:
                status = "sufficient"
                reason = f"Có {len(matching_indices)} tài liệu khớp chủ đề, ngành và năm."
                supported_aspects.append(t_topic)
            else:
                # Kiểm tra xem có tài liệu partial không (ví dụ khớp intent nhưng chưa khớp năm/ngành)
                partial_indices = []
                for i, doc in enumerate(docs, 1):
                    doc_cat = doc.get("category", "")
                    norm_doc_text = normalize_text(str(doc.get("text", "")))
                    if doc_cat == t_intent or t_intent in norm_doc_text:
                        partial_indices.append(i)

                if partial_indices:
                    status = "partial"
                    reason = f"Có tài liệu chung về {t_intent} nhưng chưa có chi tiết cho {t_topic}."
                    supported_aspects.append(f"{t_intent} (chung)")
                    missing_aspects.append(f"chi tiết cụ thể cho {t_topic}")
                else:
                    status = "missing"
                    reason = f"Chưa tìm thấy dữ liệu về {t_topic} trong kết quả truy xuất."
                    missing_aspects.append(t_topic)

            sub_claims.append(SubClaimEvidence(
                intent=t_intent,
                topic=t_topic,
                year=t_year,
                major=t_major,
                status=status,
                matching_doc_indices=matching_indices,
                reason=reason,
            ))

        # 4. Kiểm tra mâu thuẫn (Conflict Detection)
        has_conflict = False
        conflict_msg = None
        if effective_jev_sufficiency == "conflicting" and (jev_confidence is None or jev_confidence >= 0.70):
            has_conflict = True
            conflict_msg = "JEV Decision Engine xác định có mâu thuẫn giữa các tài liệu minh chứng."

        # Kiểm tra mâu thuẫn năm đối với cùng một ngành (ví dụ doc năm 2024 nói điểm A, doc 2026 nói điểm B)
        doc_years = {d.get("year") for d in docs if d.get("year")}
        if len(doc_years) > 1 and intent in ("cutoff", "tuition", "floor_score"):
            requested_years = entities.get("years", [])
            if 2026 in requested_years and any(y < 2026 for y in doc_years):
                pass

        # 5. Quyết định phán quyết (Verdict)
        can_retry = (current_retrieval_round < max_retrieval_rounds)

        if has_conflict:
            verdict = "conflicting"
            needs_supp = can_retry
            guidance = (
                "[CẢNH BÁO MINH CHỨNG]: Tài liệu nguồn có dấu hiệu mâu thuẫn hoặc chưa thống nhất thông số/dữ liệu. "
                "Hãy nêu rõ sự khác biệt giữa các nguồn hoặc phiên bản, tuyệt đối không tự chọn một con số thiếu căn cứ."
            )
        elif not supported_aspects and missing_aspects:
            verdict = "insufficient"
            needs_supp = can_retry
            guidance = (
                f"[THÔNG BÁO MINH CHỨNG]: Kho tri thức chính thức của {prof_name} hiện chưa có thông tin xác thực cho câu hỏi này. "
                f"Hãy thông báo rõ ràng rằng chưa xác minh được dữ liệu chính thức, và cung cấp kênh liên hệ chính thức: {prof_contact}."
            )
        elif missing_aspects and supported_aspects:
            verdict = "partial"
            needs_supp = can_retry
            supp_str = ", ".join(supported_aspects)
            miss_str = ", ".join(missing_aspects)
            guidance = (
                f"[CHỈ DẪN MINH CHỨNG PARTIAL]: Tài liệu nguồn chỉ đủ căn cứ cho phần: {supp_str}. "
                f"Hãy trả lời chi tiết và trích dẫn [n] cho phần có căn cứ. "
                f"Đồng thời nêu rõ phần '{miss_str}' hiện chưa có thông tin xác minh trong kho tri thức của {prof_name}, không tự suy đoán."
            )
        else:
            verdict = "sufficient"
            needs_supp = False
            guidance = (
                "[MINH CHỨNG ĐẦY ĐỦ]: Dữ liệu nguồn đã đủ căn cứ cho các ý của câu hỏi. "
                "Hãy trả lời rõ ràng, chính xác và trích dẫn nguồn [n] theo tài liệu tham khảo."
            )

        # Xây dựng truy vấn bổ sung nếu cần
        supp_query = None
        if needs_supp:
            supp_query = cls._build_supplementary_query(question, entities, missing_aspects, profile=active_profile)

        return PolicyVerdict(
            verdict=verdict,
            can_answer=(verdict in ("sufficient", "partial")),
            needs_supplementary=needs_supp,
            supplementary_query=supp_query,
            clarification_prompt=None,
            evidence_guidance=guidance,
            sub_claims=sub_claims,
            missing_aspects=missing_aspects,
            supported_aspects=supported_aspects,
            conflict_details=conflict_msg,
        )

    @classmethod
    def _build_supplementary_query(
        cls,
        question: str,
        entities: Dict[str, Any],
        missing_aspects: List[str],
        profile: Optional[Any] = None,
    ) -> str:
        """Tạo truy vấn tập trung cho vòng truy xuất bổ sung."""
        from backend.app.rag.profile import get_profile
        prof = profile if profile is not None else get_profile()
        prof_name = prof.name

        parts = [question]
        major_name = entities.get("major_name")
        major_code = entities.get("major_code")
        years = entities.get("years", [])

        if major_name and major_name not in question.lower():
            parts.append(major_name)
        if major_code and major_code not in question:
            parts.append(major_code)
        if years and not any(str(y) in question for y in years):
            parts.append(str(years[0]))

        if missing_aspects:
            for asp in missing_aspects[:2]:
                parts.append(asp)

        parts.append(f"{prof_name} chính thức")
        return " ".join(parts).strip()

    @classmethod
    def _build_fallback_query(
        cls,
        question: str,
        entities: Dict[str, Any],
        profile: Optional[Any] = None,
    ) -> str:
        from backend.app.rag.profile import get_profile
        prof = profile if profile is not None else get_profile()
        major = entities.get("major_name") or entities.get("major_code") or ""
        return f"{question} {major} {prof.name}".strip()
