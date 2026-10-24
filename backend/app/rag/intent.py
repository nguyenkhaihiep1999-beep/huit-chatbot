import re
import hashlib
import unicodedata
from typing import Optional, List, Dict, Any, Set, Tuple

def normalize_text(text: str) -> str:
    text = str(text or "").lower()
    telex_map = [
        (r"\bngnah\b", "nganh"),
        (r"\bnganhj\b", "nganh"),
        (r"\bhocj\b", "hoc"),
        (r"\bphij\b", "phi"),
        (r"\bxetj\b", "xet"),
        (r"\bdiemj\b", "diem"),
        (r"\bdiems\b", "diem"),
        (r"\bdiemd\b", "diem"),
        (r"\bchuanj\b", "chuan"),
        (r"\bsanj\b", "san"),
        (r"\bhocjba\b", "hoc ba"),
        (r"\bhocj ba\b", "hoc ba"),
    ]
    for pattern, repl in telex_map:
        text = re.sub(pattern, repl, text)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text).strip()

# Giữ alias _normalize cho tương thích
_normalize = normalize_text

QUERY_ALIASES = {
    "attt": "an toàn thông tin",
    "cntt": "công nghệ thông tin",
    "data science": "khoa học dữ liệu",
    "data": "khoa học dữ liệu",
    "tiếp thị": "marketing",
    "chuỗi cung ứng": "logistics quản lý chuỗi cung ứng",
    "hỗ trợ học phí": "học bổng hỗ trợ học phí",
    "xử lý nước thải": "công nghệ kỹ thuật môi trường xử lý nước thải kiểm soát ô nhiễm",
    "kiểm soát ô nhiễm": "công nghệ kỹ thuật môi trường kiểm soát ô nhiễm",
    "máy tự động": "công nghệ kỹ thuật điều khiển và tự động hóa robot công nghiệp",
    "dây chuyền tự động": "công nghệ kỹ thuật điều khiển và tự động hóa",
    "phân tích dữ liệu": "khoa học dữ liệu phân tích khai phá dữ liệu thống kê",
    "dữ liệu lớn": "khoa học dữ liệu big data khai phá dữ liệu",
    "thiết kế váy": "công nghệ dệt may kinh doanh thời trang và dệt may thiết kế rập trang phục",
    "thiết kế áo": "công nghệ dệt may kinh doanh thời trang và dệt may trang phục",
    "thiết kế đầm": "công nghệ dệt may kinh doanh thời trang và dệt may trang phục",
    "thiết kế trang phục": "công nghệ dệt may kinh doanh thời trang và dệt may",
    "thiết kế thời trang": "công nghệ dệt may kinh doanh thời trang và dệt may",
    "may mặc": "công nghệ dệt may thiết kế rập may công nghiệp",
    "may rập": "công nghệ dệt may kỹ sư thiết kế rập",
    "bán hàng thời trang": "kinh doanh thời trang và dệt may marketing thời trang",
    "thời trang": "công nghệ dệt may kinh doanh thời trang và dệt may",
    "lập trình game": "công nghệ thông tin kỹ thuật phần mềm trí tuệ nhân tạo",
    "lập trình app": "công nghệ thông tin kỹ thuật phần mềm",
    "viết app": "công nghệ thông tin kỹ thuật phần mềm",
    "viết code": "công nghệ thông tin kỹ thuật phần mềm",
    "lập trình viên": "công nghệ thông tin kỹ thuật phần mềm",
    "nấu ăn": "quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn",
    "làm bánh": "quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn công nghệ thực phẩm",
    "ẩm thực": "quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn",
    "đầu bếp": "quản trị dịch vụ ăn uống và kỹ thuật chế biến món ăn",
    "mỹ phẩm": "công nghệ kỹ thuật hóa học hóa mỹ phẩm",
    "son môi": "công nghệ kỹ thuật hóa học hóa mỹ phẩm",
    "hóa chất": "công nghệ kỹ thuật hóa học",
    "thiết kế đồ họa": "truyền thông đa phương tiện đồ họa",
    "truyền thông": "truyền thông đa phương tiện marketing",
    "sếp": "quản trị kinh doanh",
    "quản lý": "quản trị kinh doanh",
    "khởi nghiệp": "quản trị kinh doanh kinh doanh thương mại",
    "xuất nhập khẩu": "logistics và quản lý chuỗi cung ứng thương mại quốc tế",
    "con gái nên học": "công nghệ dệt may kinh doanh thời trang quản trị kinh doanh kế toán ngôn ngữ anh ngôn ngữ trung công nghệ thực phẩm công nghệ kỹ thuật hóa học",
    "nữ nên học": "công nghệ dệt may kinh doanh thời trang quản trị kinh doanh kế toán ngôn ngữ anh ngôn ngữ trung công nghệ thực phẩm công nghệ kỹ thuật hóa học",
    "dễ xin việc": "công nghệ thông tin công nghệ thực phẩm logistics và quản lý chuỗi cung ứng marketing kế toán công nghệ dệt may",
}

INTENT_TERMS = {
    "admission_procedure": (
        "nhap hoc", "ho so nhap hoc", "thu tuc nhap hoc", "xac nhan nhap hoc",
        "thoi gian nhap hoc", "lich nhap hoc", "sinh hoat dau khoa",
        "rut hoc phi", "hoan hoc phi", "rut ho so",
    ),
    "cutoff": (
        "diem chuan", "diem trung tuyen", "trung tuyen", "chuan 2026",
        "diem chuan 2026", "diem nganh", "diem cntt", "diem it",
        "diem nay", "diem xet tuyen",
    ),
    "floor_score": (
        "diem san", "nguong dam bao", "nguong xet tuyen", "nhan ho so",
    ),
    "tuition": (
        "hoc phi", "tin chi", "tien hoc", "muc phi", "chi phi hoc",
        "tien de hoc", "bao nhieu tien de hoc",
    ),
    "scholarship": ("hoc bong", "giam hoc phi", "mien hoc phi"),
    "admission": (
        "phuong thuc xet tuyen", "xet tuyen", "xet hoc ba",
        "danh gia nang luc", "bo sung", "chi tieu bo sung",
    ),
    "career": (
        "chon nganh", "hoc nganh", "hoc ngnah", "hoc gi", "phu hop",
        "huong nghiep", "nghe nghiep", "thich", "muon hoc", "muon lam",
        "dam me", "con gai nen hoc", "nu nen hoc", "de xin viec",
        "thiet ke", "vay", "dam", "may mac", "lap trinh", "nau an",
        "my pham", "game", "truyen thong", "logistics", "xuat nhap khau",
    ),
    "major": ("ma nganh", "to hop", "nganh hoc", "co hoi viec lam", "nganh"),
    "contact": ("dia chi", "co so", "hotline", "lien he"),
}

TITLE_STOP_WORDS = {
    "thong", "tin", "tuyen", "sinh", "nganh", "huit", "truong",
    "dai", "hoc", "cong", "thuong", "thanh", "pho",
}

def expand_query(question: str) -> str:
    """Add canonical admissions terms without removing the user's wording."""
    normalized = normalize_text(question)
    expansions = [
        canonical
        for alias, canonical in QUERY_ALIASES.items()
        if re.search(rf"\b{re.escape(normalize_text(alias))}\b", normalized)
    ]
    return f"{question} {' '.join(expansions)}".strip()

def classify_intent(question: str) -> str:
    normalized = normalize_text(question)
    for intent in ("admission_procedure", "scholarship", "cutoff", "floor_score", "tuition", "admission", "contact", "career"):
        if any(term in normalized for term in INTENT_TERMS[intent]):
            return intent
    scores = {
        intent: sum(1 for term in terms if term in normalized)
        for intent, terms in INTENT_TERMS.items()
    }
    intent, score = max(scores.items(), key=lambda item: item[1])
    return intent if score else "general"

def infer_metadata(doc: dict) -> dict:
    title = str(doc.get("title", ""))
    text = str(doc.get("text", ""))
    combined = f"{title} {text}"
    normalized = normalize_text(combined)
    category = doc.get("category")
    if not category:
        normalized_title = normalize_text(title)
        if "hoc bong" in normalized_title:
            category = "scholarship"
        elif "hoc phi" in normalized_title:
            category = "tuition"
        elif "diem san" in normalized_title or "diem chuan" in normalized_title:
            category = "cutoff"
        elif "nganh" in normalized_title or re.search(r"\b7\d{6}\b", title):
            category = "major"
    if not category:
        category_scores = {
            intent: sum(1 for term in terms if term in normalized)
            for intent, terms in INTENT_TERMS.items()
        }
        category, score = max(category_scores.items(), key=lambda item: item[1])
        category = category if score else "general"
    years = [int(value) for value in re.findall(r"\b20(?:2[4-9]|3\d)\b", combined)]
    major_match = re.search(r"\b7\d{6}\b", combined)
    return {
        "category": category,
        "year": doc.get("year") or (max(years) if years else None),
        "major_code": doc.get("major_code") or (major_match.group(0) if major_match else None),
    }

def candidate_id(doc: dict, rank: int, prefix: str) -> str:
    if doc.get("_id") is not None:
        return str(doc["_id"])
    fingerprint = f"{doc.get('title', '')}|{doc.get('text', '')[:180]}"
    return f"{prefix}:{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()}:{rank}"


ADMISSION_METHOD_MAP = {
    "hoc_ba": ["hoc ba", "xet hoc ba", "hoc ba thpt"],
    "thpt": ["thpt", "thi tot nghiep", "diem thi thpt", "tot nghiep thpt", "diem thi"],
    "dgnl": ["dgnl", "danh gia nang luc", "nang luc dhqg", "dhqg hcm", "dhqg"],
    "tuyen_thang": ["tuyen thang", "xet tuyen thang"],
    "nang_luc_chuyen_biet": ["nang luc chuyen biet", "chuyen biet dhsp"],
}

MAJOR_KEYWORDS_MAP = [
    ("7480201", "cong nghe thong tin", ["cntt", "cn thong tin", "cong nghe thong tin", "it", "lap trinh"]),
    ("7480107", "tri tue nhan tao", ["tri tue nhan tao", "ai", "artificial intelligence"]),
    ("7480108", "khoa hoc du lieu", ["khoa hoc du lieu", "data science", "data"]),
    ("7480202", "an toan thong tin", ["an toan thong tin", "attt", "cyber security", "bao mat"]),
    ("7480103", "ky thuat phan mem", ["ky thuat phan mem", "software engineering"]),
    ("7510605", "logistics va quan ly chuoi cung ung", ["logistics", "chuoi cung ung"]),
    ("7540101", "cong nghe thuc pham", ["cong nghe thuc pham", "thuc pham"]),
    ("7520216", "cong nghe ky thuat dieu khien va tu dong hoa", ["tu dong hoa", "dieu khien va tu dong hoa", "robot"]),
    ("7510301", "cong nghe ky thuat dien, dien tu", ["dien - dien tu", "dien dien tu", "dien tu"]),
    ("7340115", "marketing", ["marketing", "tiep thi"]),
    ("7340122", "thuong mai dien tu", ["thuong mai dien tu", "tmdt", "e-commerce"]),
    ("7340101", "quan tri kinh doanh", ["quan tri kinh doanh", "qtkd", "kinh doanh"]),
    ("7380107", "luat kinh te", ["luat kinh te"]),
    ("7380101", "luat", ["nganh luat", "luat hoc"]),
    ("7340201", "tai chinh - ngan hang", ["tai chinh ngan hang", "ngan hang", "tai chinh"]),
    ("7340301", "ke toan", ["ke toan", "kiem toan"]),
    ("7340120", "kinh doanh quoc te", ["kinh doanh quoc te", "xuat nhap khau"]),
    ("7220201", "ngon ngu anh", ["ngon ngu anh", "tieng anh"]),
    ("7220204", "ngon ngu trung quoc", ["ngon ngu trung quoc", "tieng trung", "ngon ngu trung"]),
    ("7540204", "cong nghe det, may", ["det may", "thoi trang", "may mac", "thiet ke thoi trang"]),
    ("7510401", "cong nghe ky thuat hoa hoc", ["hoa hoc", "hoa my pham", "my pham"]),
    ("7510406", "cong nghe ky thuat moi truong", ["moi truong", "xu ly nuoc thai"]),
    ("7810103", "quan tri dich vu du lich va lu hanh", ["du lich", "lu hanh"]),
    ("7810201", "quan tri khach san", ["khach san", "nha hang"]),
]


def extract_admission_entities(
    question: str,
    chat_history: Optional[List[dict]] = None
) -> dict:
    """Trích xuất có căn cứ ngành, năm, phương thức tuyển sinh và ý định từ câu hỏi và ngữ cảnh.
    
    Chỉ trích xuất khi có cơ sở rõ ràng trong văn bản hoặc lịch sử gần nhất; không suy đoán số liệu.
    """
    q_norm = normalize_text(question)
    code_match = re.search(r"\b7\d{6}\b", question)
    major_code = code_match.group(0) if code_match else None
    
    # 1. Trích xuất năm
    years = {int(val) for val in re.findall(r"\b20(?:2[0-9]|3[0-9])\b", question)}
    
    # 2. Trích xuất phương thức tuyển sinh
    methods = []
    for method_key, patterns in ADMISSION_METHOD_MAP.items():
        if any(p in q_norm for p in patterns):
            methods.append(method_key)

    # 3. Trích xuất ngành đào tạo
    matched_major_name = None
    if not major_code:
        for code, canonical_name, aliases in MAJOR_KEYWORDS_MAP:
            if any(alias in q_norm for alias in aliases):
                major_code = code
                matched_major_name = canonical_name
                break
    else:
        for code, canonical_name, _ in MAJOR_KEYWORDS_MAP:
            if code == major_code:
                matched_major_name = canonical_name
                break

    # Nếu câu hỏi ngắn và chưa có ngành/năm, xét tìm trong lịch sử gần nhất (grounded context)
    if chat_history and isinstance(chat_history, list) and (not major_code or not years):
        for turn in reversed(chat_history[-3:]):
            content = turn.get("content", "")
            norm_content = normalize_text(content)
            if not years:
                hist_years = {int(val) for val in re.findall(r"\b20(?:2[0-9]|3[0-9])\b", content)}
                if hist_years:
                    years = hist_years
            if not major_code:
                h_code = re.search(r"\b7\d{6}\b", content)
                if h_code:
                    major_code = h_code.group(0)
                    for code, canonical_name, _ in MAJOR_KEYWORDS_MAP:
                        if code == major_code:
                            matched_major_name = canonical_name
                            break
                else:
                    for code, canonical_name, aliases in MAJOR_KEYWORDS_MAP:
                        if any(alias in norm_content for alias in aliases):
                            major_code = code
                            matched_major_name = canonical_name
                            break

    # 4. Trích xuất các chủ đề/ý định được hỏi (inquiry types)
    inquiries = []
    if any(k in q_norm for k in ["hoc phi", "tin chi", "tien hoc", "chi phi", "muc phi"]):
        inquiries.append("tuition")
    if any(k in q_norm for k in ["diem chuan", "diem trung tuyen", "trung tuyen"]):
        inquiries.append("cutoff")
    if any(k in q_norm for k in ["diem san", "nguong dam bao", "nhan ho so"]) and not any(k in q_norm for k in ["diem chuan", "trung tuyen"]):
        inquiries.append("floor_score")
    if any(k in q_norm for k in ["nhap hoc", "ho so nhap hoc", "thu tuc nhap hoc", "rut hoc phi", "hoan hoc phi"]):
        inquiries.append("admission_procedure")
    if any(k in q_norm for k in ["hoc bong", "giam hoc phi", "mien hoc phi"]):
        inquiries.append("scholarship")
    if any(k in q_norm for k in ["phuong thuc", "xet hoc ba", "danh gia nang luc"]):
        if "admission" not in inquiries:
            inquiries.append("admission")
    if not inquiries:
        inquiries.append(classify_intent(question))

    # 5. Phát hiện thiếu thông tin cốt lõi từ người hỏi (ngành, năm cụ thể khi hỏi chi tiết)
    missing_user_info = False
    clarification_prompt = None
    referential_major_phrases = ["nganh nay", "nganh do", "nganh kia", "nganh tren", "diem nganh nay", "hoc phi nganh nay"]
    has_referential_major = any(p in q_norm for p in referential_major_phrases)

    if has_referential_major and not major_code:
        missing_user_info = True
        clarification_prompt = (
            "Bạn vui lòng cho biết cụ thể ngành học bạn đang quan tâm "
            "(ví dụ: Công nghệ thông tin, Trí tuệ nhân tạo, Logistics,...) để mình tra cứu chính xác nhất nhé!"
        )

    return {
        "years": sorted(list(years)) if years else [],
        "major_code": major_code,
        "major_name": matched_major_name,
        "admission_methods": methods,
        "inquiries": inquiries,
        "is_multi_intent": len(inquiries) > 1,
        "missing_user_info": missing_user_info,
        "clarification_prompt": clarification_prompt,
    }


def decompose_sub_intents(question: str, entities: Optional[dict] = None) -> list:
    """Tách câu hỏi đa ý thành các tác vụ con để theo dõi minh chứng độc lập."""
    if not entities:
        entities = extract_admission_entities(question)
    
    inquiries = entities.get("inquiries", [])
    if not inquiries:
        inquiries = ["general"]
        
    sub_tasks = []
    major_name = entities.get("major_name") or entities.get("major_code") or ""
    years = entities.get("years", [])
    target_year = years[0] if years else None

    for inq in inquiries:
        topic_desc = f"{inq} {major_name}".strip()
        if target_year:
            topic_desc += f" nam {target_year}"
        sub_tasks.append({
            "intent": inq,
            "topic": topic_desc,
            "year": target_year,
            "major": major_name,
            "major_code": entities.get("major_code"),
            "methods": entities.get("admission_methods", []),
        })
    return sub_tasks

