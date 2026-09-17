import re
import hashlib
import unicodedata

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
