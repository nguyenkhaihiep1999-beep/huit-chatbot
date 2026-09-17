"""
artifact_intent.py
Phân tích ý định sinh file và cấu trúc dữ liệu minh họa từ câu hỏi của người dùng:
1. Phát hiện yêu cầu tạo file cụ thể: Excel (.xlsx), Word (.docx), PDF (.pdf), Ảnh/Infographic.
2. Phát hiện câu hỏi tra cứu cần kèm infographic minh họa (học phí, điểm chuẩn, phương thức, học bổng).
3. Đảm bảo dữ liệu số liệu (học phí, điểm chuẩn) hoàn toàn đồng nhất giữa câu trả lời chữ và infographic.
"""
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from backend.app.rag.intent import normalize_text

# Dữ liệu chuẩn hóa học phí HUIT 2026 (dùng chung cho cả câu trả lời và infographic)
TUITION_DATA_2026 = {
    "title": "BẢNG TRA CỨU ĐỊNH MỨC HỌC PHÍ HUIT NĂM HỌC 2026 - 2027",
    "subtitle": "Trường Đại học Công Thương TP.HCM (HUIT)",
    "headers": ["Mã ngành", "Tên ngành đào tạo", "Khối ngành", "Thời gian", "Học phí dự kiến / HK"],
    "rows": [
        ["7480201", "Công nghệ thông tin", "Công nghệ - Kỹ thuật", "3.5 - 4 năm (150 TC)", "14.5 - 16.5 triệu đồng"],
        ["7480107", "Trí tuệ nhân tạo", "Công nghệ - Kỹ thuật", "3.5 - 4 năm (150 TC)", "15.0 - 17.0 triệu đồng"],
        ["7460108", "Khoa học dữ liệu", "Công nghệ - Kỹ thuật", "3.5 - 4 năm (150 TC)", "14.5 - 16.5 triệu đồng"],
        ["7540101", "Công nghệ thực phẩm", "Thực phẩm - Hóa học", "3.5 - 4 năm (150 TC)", "14.0 - 16.0 triệu đồng"],
        ["7340115", "Marketing", "Kinh tế - Quản trị", "3.5 - 4 năm (150 TC)", "13.5 - 15.5 triệu đồng"],
        ["7510605", "Logistics & Chuỗi cung ứng", "Kinh tế - Kỹ thuật", "3.5 - 4 năm (150 TC)", "14.0 - 16.0 triệu đồng"],
        ["7380107", "Luật kinh tế", "Luật - Xã hội", "3.5 - 4 năm (150 TC)", "13.0 - 15.0 triệu đồng"],
        ["7220201", "Ngôn ngữ Anh", "Ngoại ngữ", "3.5 - 4 năm (150 TC)", "13.5 - 15.5 triệu đồng"],
    ]
}

# Dữ liệu chuẩn hóa điểm chuẩn chính thức 2026
CUTOFF_DATA_2026 = {
    "title": "BẢNG ĐIỂM CHUẨN TRÚNG TUYỂN CHÍNH THỨC HUIT 2026",
    "subtitle": "Công bố ngày 09/08/2026 - Trường Đại học Công Thương TP.HCM",
    "headers": ["Mã ngành", "Tên ngành đào tạo", "Tổ hợp xét", "Điểm sàn 2026", "Điểm chuẩn 2026 (Chính thức)"],
    "rows": [
        ["7520216", "CNKT Điều khiển & Tự động hóa", "A00, A01, B00, D07", "18.00 điểm", "23.00 điểm"],
        ["7510605", "Logistics & Chuỗi cung ứng", "A00, A01, D01, D07", "18.00 điểm", "22.50 điểm"],
        ["7540101", "Công nghệ thực phẩm", "A00, B00, D07, D08", "17.00 điểm", "22.00 điểm"],
        ["7520201", "Kỹ thuật Điện - Điện tử", "A00, A01, B00, D07", "17.00 điểm", "22.00 điểm"],
        ["7340115", "Marketing", "A00, A01, D01, D07", "17.00 điểm", "21.75 điểm"],
        ["7340122", "Thương mại điện tử", "A00, A01, D01, D07", "17.00 điểm", "21.75 điểm"],
        ["7380107", "Luật kinh tế", "A00, A01, C00, D01", "17.00 điểm", "21.75 điểm"],
        ["7480107", "Trí tuệ nhân tạo", "A00, A01, B00, D07", "17.00 điểm", "20.50 điểm"],
        ["7480201", "Công nghệ thông tin", "A00, A01, B00, D07", "17.00 điểm", "20.00 điểm"],
    ]
}


def detect_file_generation_intent(query_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Phát hiện ý định sinh file cụ thể từ câu nói của người dùng:
    Returns (file_format, topic):
    - file_format: "xlsx", "docx", "pdf", "image", "svg", hoặc None
    - topic: "tuition", "cutoff", "admission", "major", hoặc "general"
    """
    q_norm = normalize_text(query_text)

    # 1. Phát hiện định dạng mong muốn
    fmt = None
    if any(k in q_norm for k in ["excel", "xlsx", "bang tinh", "bang excel", "file excel"]):
        fmt = "xlsx"
    elif any(k in q_norm for k in ["word", "docx", "van ban word", "tai lieu word", "file word"]):
        fmt = "docx"
    elif any(k in q_norm for k in ["pdf", "file pdf", "tai pdf", "xuat pdf"]):
        fmt = "pdf"
    elif any(k in q_norm for k in ["infographic", "so do", "bieu do", "the nganh", "hinh anh", "anh minh hoa"]):
        fmt = "svg"

    # 2. Phát hiện chủ đề
    topic = "general"
    if any(k in q_norm for k in ["hoc phi", "tin chi", "tien hoc", "chi phi", "gia tien"]):
        topic = "tuition"
    elif any(k in q_norm for k in ["diem chuan", "diem san", "diem trung tuyen"]):
        topic = "cutoff"
    elif any(k in q_norm for k in ["phuong thuc", "xet tuyen", "nhap hoc", "ho so"]):
        topic = "admission"
    elif any(k in q_norm for k in ["nganh hoc", "cac nganh", "danh muc nganh"]):
        topic = "major"

    # Nếu có từ khóa yêu cầu sinh rõ ràng (tạo, xuất, sinh, tải, cho tôi file...)
    has_generation_trigger = any(
        re.search(r"\b" + re.escape(trigger) + r"\b", q_norm)
        for trigger in ["tao", "xuat", "sinh", "tai", "lap", "cho toi file", "gui file", "in", "ve"]
    )

    if fmt or has_generation_trigger:
        return fmt or "svg", topic

    return None, None


def should_attach_illustrative_infographic(intent: str, query_text: str) -> Optional[str]:
    """
    Xác định xem câu hỏi có nên tự động đính kèm infographic minh họa không.
    Ví dụ: hỏi học phí -> đính kèm infographic bảng học phí.
    """
    q_norm = normalize_text(query_text)

    if intent == "tuition" or any(k in q_norm for k in ["hoc phi", "tien hoc", "bao nhieu tien"]):
        return "tuition"

    if intent in ("cutoff", "floor_score") or any(k in q_norm for k in ["diem chuan", "diem san", "diem trung tuyen"]):
        return "cutoff"

    if any(k in q_norm for k in ["nhap hoc", "thu tuc nhap hoc", "lich nhap hoc"]):
        return "roadmap_nhaphoc"

    if any(k in q_norm for k in ["phuong thuc", "phuong thuc xet tuyen", "5 phuong thuc"]):
        return "roadmap_admissions"

    return None
