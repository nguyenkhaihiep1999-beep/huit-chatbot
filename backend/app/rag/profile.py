"""Knowledge profile definitions and server-side resolution for RAG system.

Supports multiple knowledge profiles with strict server-side whitelist isolation:
- 'huit': Trường Đại học Công Thương TP.HCM (HUIT Admissions)
- 'ilt': Innovative Lighting Technologies (ILT Dong Nai Factory & Catalog)

Profiles define collection namespaces, vector indexes, prompts, contact info,
and independent Jev task configurations (intent vs evidence).
"""
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.config import settings

logger = logging.getLogger("huit_chatbot.rag.profile")

WHITELISTED_PROFILES = ("huit", "ilt")


@dataclass(frozen=True)
class KnowledgeProfile:
    id: str  # "huit" | "ilt"
    name: str
    kb_collection: str
    vector_index_name: str
    embedding_model: str
    embedding_dims: int
    clusters_filename: str
    default_source_url: str
    official_contact: str
    system_prompt: str
    answer_template: str
    empty_kb_message: str
    kb_version: str
    rag_version: str
    primary_domain: str

    @property
    def jev_intent_mode(self) -> str:
        if self.id == "ilt":
            return settings.ILT_JEV_INTENT_MODE
        return settings.HUIT_JEV_INTENT_MODE

    @property
    def jev_evidence_mode(self) -> str:
        if self.id == "ilt":
            return settings.ILT_JEV_EVIDENCE_MODE
        return settings.HUIT_JEV_EVIDENCE_MODE

    @property
    def enable_cluster_prefilter(self) -> bool:
        return settings.ENABLE_CLUSTER_PREFILTER

    @property
    def mongodb_collection(self) -> str:
        return self.kb_collection

    @property
    def vector_index(self) -> str:
        return self.vector_index_name

    @property
    def clusters_path(self) -> Path:
        return settings.get_data_file(self.clusters_filename)


HUIT_SYSTEM_PROMPT = (
    "Bạn là AI Tư vấn Tuyển sinh thông minh và thân thiện của Trường Đại học Công Thương TP.HCM (HUIT). "
    "Bạn có khả năng trò chuyện tự nhiên, thấu hiểu ngữ cảnh và suy luận thông minh dựa trên nguyện vọng của thí sinh/phụ huynh. "
    "LƯU Ý ĐẶC BIỆT: Nhà trường đã CHÍNH THỨC CÔNG BỐ Điểm chuẩn trúng tuyển năm 2026 vào ngày 09/08/2026 "
    "(điểm thi THPT dao động 16.00 - 23.00 điểm, ngành cao nhất là Công nghệ kỹ thuật điều khiển và tự động hóa 23.00 điểm, "
    "Logistics 22.50đ, Công nghệ thực phẩm 22.00đ, Điện - Điện tử 22.00đ, Marketing 21.75đ, Thương mại điện tử 21.75đ, "
    "Luật kinh tế 21.75đ, CNTT 20.00đ, Trí tuệ nhân tạo 20.50đ). "
    "Thủ tục nhập học Tân sinh viên K2026 diễn ra từ 12/08/2026 đến hết 17h00 ngày 21/08/2026 tại nhaphoc.huit.edu.vn "
    "và xác nhận trên cổng Bộ GD&ĐT. Khi được hỏi về điểm chuẩn hay tuyển sinh, bạn hãy ưu tiên dùng dữ kiện trong "
    "NGỮ CẢNH HUIT và trích dẫn nguồn [n] chính xác, tuyệt đối không trả lời nhầm sang điểm sàn hay nói rằng trường chưa công bố điểm chuẩn."
)

HUIT_ANSWER_TEMPLATE = (
    "NGỮ CẢNH TRÍ THỨC HUIT:\n{context}\n\n"
    "CÂU HỎI / YÊU CẦU: {question}\n\n"
    "Hãy trả lời bằng tiếng Việt tự nhiên, ấm áp và thông minh. Trích dẫn [n] ngay sau các dữ kiện chính xác từ ngữ cảnh. "
    "Nếu câu hỏi mang tính trò chuyện hoặc tư vấn cá nhân, hãy trả lời tự nhiên đúng tư cách là AI Tư vấn Tuyển sinh HUIT."
)

ILT_SYSTEM_PROMPT = (
    "Bạn là Trợ lý AI chuyên nghiệp của Công ty TNHH Innovative Lighting Technologies (ILT) tại Đồng Nai, Việt Nam "
    "(website: https://innovativelightingco.com/).\n\n"
    "GIỚI THIỆU CÔNG TY:\n"
    "ILT là nhà sản xuất và xuất khẩu hàng đầu các giải pháp chiếu sáng công nghiệp, thương mại và trang trí cao cấp: "
    "đèn bàn (table lamps), đèn sàn (floor lamps), đèn thả (pendants), đèn chùm (chandeliers), đèn gắn tường (sconces), "
    "đèn rọi (spotlights/downlights) và sản phẩm gia công theo yêu cầu (customized/OEM/ODM) cho thị trường Bắc Mỹ, Châu Âu và toàn cầu.\n\n"
    "NGUYÊN TẮC TƯ VẤN & BẢO ĐẢM MINH CHỨNG:\n"
    "1. Tư vấn chi tiết, chính xác về các dòng sản phẩm, chất liệu (kim loại, thủy tinh, gốm, gỗ), kiểu dáng, kích thước "
    "và thông số kỹ thuật dựa trên dữ liệu catalogue chính thức của công ty.\n"
    "2. Giải đáp về năng lực sản xuất, quy trình gia công kim loại, sơn tĩnh điện, tiêu chuẩn kiểm định an toàn (UL, ETL, CE), "
    "đóng gói xuất khẩu và dịch vụ OEM/ODM.\n"
    "3. Cung cấp thông tin liên hệ nhà máy tại Đồng Nai và quy trình gửi yêu cầu báo giá dự án (RFQ).\n"
    "4. QUY TẮC BẮT BUỘC:\n"
    "- Trả lời bằng tiếng Việt tự nhiên, chuẩn mực, chuyên nghiệp. Giữ nguyên mã model/SKU, tên dòng sản phẩm tiếng Anh và đơn vị đo lường (inch, cm, W, V, lm, K, CRI, IP).\n"
    "- Chỉ khẳng định thông số kỹ thuật (công suất, đui đèn, kích thước, vật liệu, chứng chỉ) khi có trong ngữ cảnh và trích dẫn nguồn [n] kèm trang catalogue.\n"
    "- TUYỆT ĐỐI KHÔNG tự bịa hoặc suy đoán giá cả, số lượng đặt hàng tối thiểu (MOQ), thời gian giao hàng, bảo hành hay tồn kho khi tài liệu không nêu. "
    "Nêu rõ rằng khách hàng cần liên hệ trực tiếp phòng kinh doanh ILT (info@innovativelightingco.com hoặc (+84) 251 3514 366) để nhận báo giá dự án chính xác.\n"
    "- Không nhầm lẫn với Innovative Lighting tại Iowa, Mỹ. ILT là công ty độc lập tại Đồng Nai, Việt Nam."
)

ILT_ANSWER_TEMPLATE = (
    "NGỮ CẢNH TRI THỨC INNOVATIVE LIGHTING TECHNOLOGIES:\n{context}\n\n"
    "CÂU HỎI / YÊU CẦU: {question}\n\n"
    "Hãy trả lời bằng tiếng Việt chuyên nghiệp, chuẩn xác và đầy đủ căn cứ. Trích dẫn [n] ngay sau các thông số kỹ thuật, "
    "mã SKU hoặc thông tin xuất xứ. Nếu câu hỏi yêu cầu thông tin về giá, số lượng đặt hàng tối thiểu (MOQ) hoặc tiến độ giao hàng mà "
    "ngữ cảnh không có, hãy thông báo lịch sự rằng quý khách vui lòng liên hệ trực tiếp bộ phận kinh doanh ILT "
    "(info@innovativelightingco.com hoặc (+84) 251 3514 366) để nhận bảng giá dự án chính xác."
)


HUIT_PROFILE = KnowledgeProfile(
    id="huit",
    name="HUIT Tuyển sinh",
    kb_collection="huit_kb",
    vector_index_name="huit_vector_index",
    embedding_model="intfloat/multilingual-e5-large",
    embedding_dims=1024,
    clusters_filename="huit_cluster_centroids.json",
    default_source_url="https://ts.huit.edu.vn",
    official_contact="Cổng tuyển sinh HUIT: 096 205 1080 - 140 Lê Trọng Tấn, P. Tây Thạnh, Q. Tân Phú, TP.HCM",
    system_prompt=HUIT_SYSTEM_PROMPT,
    answer_template=HUIT_ANSWER_TEMPLATE,
    empty_kb_message="Không tìm thấy dữ liệu liên quan trong kho tri thức tuyển sinh HUIT.",
    kb_version=settings.KB_VERSION,
    rag_version=settings.RAG_VERSION,
    primary_domain="huit.edu.vn",
)

ILT_PROFILE = KnowledgeProfile(
    id="ilt",
    name="Innovative Lighting Technologies",
    kb_collection="ilt_kb",
    vector_index_name="ilt_vector_index",
    embedding_model="intfloat/multilingual-e5-large",
    embedding_dims=1024,
    clusters_filename="ilt_cluster_centroids.json",
    default_source_url="https://innovativelightingco.com/",
    official_contact=(
        "Innovative Lighting Technologies: Đường 1, KCN Long Thành, Huyện Long Thành, Đồng Nai, Việt Nam "
        "- Hotline: (+84) 251 3514 366 - Email: info@innovativelightingco.com - Website: https://innovativelightingco.com/"
    ),
    system_prompt=ILT_SYSTEM_PROMPT,
    answer_template=ILT_ANSWER_TEMPLATE,
    empty_kb_message=(
        "Hiện tại kho tri thức chính thức của Innovative Lighting Technologies chưa có thông tin chi tiết cho câu hỏi này. "
        "Quý khách vui lòng liên hệ bộ phận kinh doanh ILT qua email info@innovativelightingco.com "
        "hoặc hotline (+84) 251 3514 366 để được hỗ trợ trực tiếp."
    ),
    kb_version="ilt-kb-2026-10-v1",
    rag_version="rag-v11-profile-grounded",
    primary_domain="innovativelightingco.com",
)

_PROFILES: Dict[str, KnowledgeProfile] = {
    "huit": HUIT_PROFILE,
    "ilt": ILT_PROFILE,
}


def is_valid_profile(profile_id: Optional[str]) -> bool:
    return bool(profile_id and profile_id.strip().lower() in WHITELISTED_PROFILES)


def get_available_profiles() -> List[str]:
    return list(WHITELISTED_PROFILES)


def get_profile(profile_id: Optional[str] = None) -> KnowledgeProfile:
    """Resolve knowledge profile from server whitelist.
    
    Security: Client or external callers CANNOT specify arbitrary MongoDB collections
    or bypass gateway authorization. Only strictly whitelisted profiles are resolved.
    """
    if profile_id:
        norm_id = profile_id.strip().lower()
        if norm_id in _PROFILES:
            return _PROFILES[norm_id]
        logger.warning(
            "Requested profile '%s' not in server whitelist %s; falling back to active profile",
            profile_id,
            WHITELISTED_PROFILES,
        )

    active_id = settings.ACTIVE_PROFILE
    if active_id in _PROFILES:
        return _PROFILES[active_id]

    return HUIT_PROFILE
