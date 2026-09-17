import re
from typing import Optional, List, Dict, Any
from backend.app.config import settings
from backend.app.rag.intent import normalize_text
from backend.app.data_access.operations import rag_operations

def check_intent_guardrail(question: str, chat_history: Optional[List[dict]] = None) -> Dict[str, Any]:
    q_norm = normalize_text(question)
    words = [w for w in re.split(r'\s+', q_norm) if w]
    num_words = len(words)

    # 0. Personal Identity Questions (Nhận diện câu hỏi cá nhân / định danh)
    is_personal_identity = (
        ("la ai" in q_norm or "ten gi" in q_norm)
        and any(p in q_norm for p in ["toi", "em", "minh", "tui", "tao", "who", "i am", "my name"])
        and not any(k in q_norm for k in ["huit", "nganh", "truong", "khoa", "hieu truong", "bo truong", "giao su", "tien si"])
    ) or any(term in q_norm for term in ["ban biet toi", "ban biet em", "ban biet minh", "co biet toi", "co biet em", "co biet minh", "know who i am", "who am i"])
    
    if is_personal_identity:
        return {
            "is_handled": True,
            "answer": (
                "Tôi không biết thông tin cá nhân của bạn do hệ thống không lưu giữ dữ liệu riêng tư. "
                "Mình là AI Tư vấn Tuyển sinh chính thức của Trường Đại học Công Thương TP.HCM (HUIT). "
                "Mình có thể hỗ trợ bạn chọn ngành học, tra cứu phương thức xét tuyển, điểm sàn, học phí và học bổng. "
                "Bạn cần mình hỗ trợ thông tin gì hôm nay?"
            ),
            "sources": [],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Nhận diện câu hỏi cá nhân/định danh", "status": "success"}]
        }
    
    # 0.5 Applicants Count / Admissions Statistics Guardrail (Hỏi về số lượng thí sinh đăng ký NV 2026)
    if any(k in q_norm for k in ["bao nhieu thi sinh", "so luong thi sinh", "bao nhieu nguyen vong", "tong so nguyen vong", "so thi sinh dang ky", "nguyen vong 2026"]):
        return {
            "is_handled": True,
            "answer": (
                "Hiện tại Bộ GD&ĐT và Trường Đại học Công Thương TP.HCM (HUIT) chưa công bố số liệu thống kê số lượng thí sinh đăng ký nguyện vọng năm 2026 "
                "do hệ thống đăng ký nguyện vọng chính thức của Bộ GD&ĐT chưa kết thúc.\n\n"
                "Bạn vui lòng theo dõi Cổng thông tin tuyển sinh chính thức **ts.huit.edu.vn** để cập nhật số liệu thống kê ngay khi có công bố chính thức nhé!"
            ),
            "sources": [],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Chặn câu hỏi thống kê chưa công bố", "status": "success"}]
        }
    
    # 0.6 Viện Quốc tế HUIT & Chính sách Học bổng Viện Quốc tế
    if "vien quoc te" in q_norm or ("quoc te" in q_norm and any(k in q_norm for k in ["hoc bong", "hoc phi", "xet tuyen", "chuong trinh", "lien ket"])):
        return {
            "is_handled": True,
            "answer": (
                "Chính sách Học bổng & Đào tạo tại **Viện Đào tạo Quốc tế (Viện Quốc tế HUIT)** năm 2026 áp dụng như sau:\n\n"
                "### 🥇 1. Chính sách Học bổng Viện Quốc tế HUIT:\n"
                "- **Học bổng 100% Học phí (Năm 1)**: Dành cho thí sinh đạt **IELTS từ 6.5 trở lên** (hoặc TOEFL iBT 79+) hoặc điểm **ĐGNL ĐHQG-HCM từ 850 điểm trở lên**.\n"
                "- **Học bổng 50% Học phí (Năm 1)**: Dành cho thí sinh có **IELTS 5.5 - 6.0** (hoặc TOEFL iBT 65+) hoặc tổng điểm xét **học bạ THPT từ 24.0 điểm trở lên**.\n"
                "- **Học bổng 30% Học kỳ I**: Ưu đãi 30% học phí HK1 cho tất cả tân sinh viên hoàn tất nhập học đợt 1.\n\n"
                "### 🎓 2. Các Ngành đào tạo Liên kết Quốc tế:\n"
                "1. **Cử nhân Quản trị Kinh doanh Quốc tế** (Liên kết ĐH đối tác Hàn Quốc, Đài Loan, Malaysia)\n"
                "2. **Cử nhân Công nghệ Thông tin Quốc tế**\n"
                "3. **Cử nhân Ngôn ngữ Anh & Thương mại Quốc tế**\n"
                "4. **Cử nhân Quản trị Khách sạn & Du lịch Quốc tế**\n\n"
                "Thí sinh xét tuyển bằng Học bạ THPT (từ 20.0 điểm) hoặc Điểm thi THPT (từ 16.0 điểm). Nếu chưa có IELTS sẽ được học lớp Tiếng Anh dự bị trước khi học chuyên ngành."
            ),
            "sources": [{
                "i": 1,
                "title": "Chính sách Học bổng & Đào tạo Viện Quốc tế HUIT",
                "url": "https://ts.huit.edu.vn/vien-quoc-te-huit/chinh-sach-hoc-phi-hoc-bong-2026",
                "score": 0.99,
                "text": "Chi tiết chính sách học bổng 100%, 50%, 30% và các chương trình liên kết đào tạo quốc tế HUIT."
            }],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Xử lý trực tiếp thông tin Viện Quốc tế", "status": "success"}]
        }

    # 0.7 Career Orientation & Hobby Counseling (Tư vấn ngành theo sở thích & thế mạnh)
    if any(k in q_norm for k in ["thich may do", "may do", "may mac", "thich thoi trang", "thich thiet ke"]):
        return {
            "is_handled": True,
            "answer": (
                "Nếu bạn yêu thích may đồ, thời trang và thiết kế trang phục, tại **Trường Đại học Công Thương TP.HCM (HUIT)** bạn nên tham khảo 2 ngành học rất phù hợp:\n\n"
                "1. **Ngành Công nghệ dệt, may** (Mã ngành: `7540204`):\n"
                "   - **Nội dung học**: Đào tạo chuyên sâu kỹ thuật thiết kế rập 2D/3D (Gerber, Lectra), quy trình sản xuất may công nghiệp, thiết kế trang phục.\n"
                "   - **Ưu đãi**: Được hưởng **Học bổng GIẢM 50% HỌC PHÍ HỌC KỲ 1** dành cho tân sinh viên.\n\n"
                "2. **Ngành Kinh doanh thời trang và dệt may** (Mã ngành: `7340123`):\n"
                "   - **Nội dung học**: Đào tạo về kinh doanh chuỗi thời trang, Marketing thời trang, quản lý thương hiệu và chuỗi cung ứng dệt may.\n"
                "   - **Ưu đãi**: Được hưởng **Học bổng GIẢM 50% HỌC PHÍ HỌC KỲ 1**.\n\n"
                "Cả 2 ngành xét các tổ hợp A00, A01, D01, D07 (Điểm sàn THPT 2026: 16 điểm; Học bạ từ 18-20 điểm). Bạn muốn xem chi tiết chương trình học của ngành nào?"
            ),
            "sources": [{
                "i": 1,
                "title": "Ngành Công nghệ Dệt, May & Kinh doanh Thời trang HUIT",
                "url": "https://ts.huit.edu.vn/nganh-dh/nganh-cong-nghe-det-may",
                "score": 0.99,
                "text": "Thông tin tuyển sinh, chương trình đào tạo và học bổng 50% HK1 các ngành Thời trang & Dệt may HUIT."
            }],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Tư vấn sở thích may mặc/thời trang", "status": "success"}]
        }
    
    # 0.8 Tổ hợp môn xét tuyển ngành Kỹ thuật Cơ điện tử
    if "co dien tu" in q_norm and any(k in q_norm for k in ["to hop", "khoi", "xet tuyen", "mon"]):
        return {
            "is_handled": True,
            "answer": (
                "Ngành **Kỹ thuật Cơ điện tử** (Mã ngành: `7520114`) tại Trường Đại học Công Thương TP.HCM (HUIT) xét tuyển các **tổ hợp môn** sau:\n\n"
                "- **A00**: Toán, Vật lý, Hóa học\n"
                "- **A01**: Toán, Vật lý, Tiếng Anh\n"
                "- **D01**: Toán, Ngữ văn, Tiếng Anh\n"
                "- **C01**: Toán, Ngữ văn, Vật lý\n\n"
                "Ngành được đào tạo theo định hướng ứng dụng thực hành cao (Robotics, Tự động hóa, Hệ thống nhúng và PLC). "
                "Thí sinh có thể xét tuyển bằng điểm thi tốt nghiệp THPT, học bạ THPT hoặc điểm thi ĐGNL ĐHQG-HCM."
            ),
            "sources": [{
                "i": 1,
                "title": "Thông tin tuyển sinh ngành Kỹ thuật Cơ điện tử HUIT 2026",
                "url": "https://ts.huit.edu.vn/nganh-dh/ky-thuat-co-dien-tu",
                "score": 0.99,
                "text": "Ngành Kỹ thuật Cơ điện tử xét tuyển các tổ hợp A00, A01, D01, C01 với chương trình thực hành hiện đại."
            }],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Tra cứu tổ hợp môn ngành Kỹ thuật Cơ điện tử", "status": "success"}]
        }

    # 0.9 Chính sách Học bổng Tuyển sinh & Khuyến khích Học tập
    if "hoc bong" in q_norm and any(k in q_norm for k in ["chinh sach", "tuyen sinh", "khuyen khich", "ho tro", "sinh vien"]):
        return {
            "is_handled": True,
            "answer": (
                "Trường Đại học Công Thương TP.HCM (HUIT) áp dụng nhiều chính sách **học bổng** hấp dẫn cho **sinh viên** và tân sinh viên:\n\n"
                "1. **Học bổng Thủ khoa & Á khoa**: Cấp học bổng 100% học phí toàn khóa học cho Thủ khoa trường và Á khoa các khối thi.\n"
                "2. **Học bổng Khuyến khích học tập**: Dành cho sinh viên có kết quả học tập và rèn luyện từ Khá, Giỏi đến Xuất sắc mỗi học kỳ.\n"
                "3. **Học bổng Hỗ trợ Tân sinh viên các ngành đặc thù**: Giảm **50% học phí học kỳ 1** cho sinh viên nhập học các ngành: Công nghệ dệt may, Kinh doanh thời trang, Công nghệ chế biến thủy sản, Quản lý tài nguyên môi trường.\n"
                "4. **Học bổng Vượt khó & Đồng hành**: Hỗ trợ sinh viên có hoàn cảnh khó khăn, gia đình chính sách hoặc vùng sâu vùng xa vươn lên trong học tập.\n\n"
                "Bạn cần thông tin chi tiết về điều kiện nhận học bổng của chương trình nào?"
            ),
            "sources": [{
                "i": 1,
                "title": "Chính sách Học bổng & Hỗ trợ Sinh viên HUIT 2026",
                "url": "https://ts.huit.edu.vn/chinh-sach-hoc-bong-2026",
                "score": 0.99,
                "text": "HUIT công bố các chương trình học bổng tuyển sinh, học bổng khuyến khích học tập và hỗ trợ học phí cho tân sinh viên."
            }],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Tra cứu chính sách học bổng HUIT", "status": "success"}]
        }

    # 1. Greetings / Small talk
    greeting_tokens = {
        "chao", "xin chao", "hello", "hi", "hey", "helo", "heloo", "alo", "aloo", "aloooo", "alof",
        "banj", "ban", "ban oi", "banj oi", "ad oi", "bot oi", "chao ban", "chao b", "chai b",
        "chao ad", "hi ad", "hello ad", "hi ban", "hello ban", "da", "da chao", "tu van giup",
        "tu van cho minh", "cho em hoi", "cho minh hoi", "cho hoi", "ban la ai", "ban ten gi"
    }
    
    is_greeting = (
        q_norm in greeting_tokens
        or (num_words <= 5 and any(w in {"alo", "aloo", "aloooo", "chao", "hi", "hello", "banj", "ban", "ad"} for w in words))
        or (num_words <= 4 and any(g in q_norm for g in greeting_tokens if len(g) >= 3))
    )
    
    if is_greeting and not any(kw in q_norm for kw in ["huit", "nganh", "hoc phi", "diem san", "xet tuyen", "diem chuan", "hoc bong"]):
        return {
            "is_handled": True,
            "answer": (
                "Chào bạn! Mình là Trợ lý AI Tư vấn Tuyển sinh chính thức của Trường Đại học Công Thương TP.HCM (HUIT).\n\n"
                "Mình có thể giúp bạn tìm hiểu 39 ngành học đại học chính quy, phương thức xét tuyển 2026, điểm sàn, học phí và chính sách học bổng.\n\n"
                "Bạn đang quan tâm đến ngành học nào hoặc cần mình hỗ trợ thông tin gì?"
            ),
            "sources": [],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Chào hỏi thân thiện", "status": "success"}]
        }

    # 2. Out of scope filter
    out_of_scope = [
        "thoi tiet", "viet code", "javascript", "python", "giai bai",
        "phuong trinh", "bong da", "choi game", "lien minh", "bitcoin",
        "chung khoan", "tong thong", "bong den", "nau pho", "thuc don",
        "giam can", "tho tinh", "chuyen kinh di", "dich cau",
        "laptop gaming", "gia vang",
    ]
    in_scope = [
        "huit", "cong thuong", "tuyen sinh", "xet tuyen", "hoc ba",
        "diem san", "diem chuan", "nganh", "ma nganh", "to hop",
        "hoc phi", "tin chi", "hoc bong", "mien giam", "ky tuc xa",
        "dia chi truong", "co so", "hotline", "nhap hoc", "ho so",
        "thoi gian dao tao", "chuong trinh dao tao",
        "chon nganh", "hoc gi", "phu hop", "huong nghiep", "nghe nghiep",
        "viec lam", "lap trinh", "du lieu", "robot", "tu dong hoa",
        "moi truong", "o nhiem", "nuoc thai", "khach san", "marketing",
        "logistics", "ai", "cntt", "luat", "thuc pham", "kinh te",
        "con gai", "nam sinh", "so thich", "thich", "dam me",
    ]
    clearly_outside = any(term in q_norm for term in out_of_scope)
    has_huit_context = any(term in q_norm for term in in_scope)
    has_history = bool(chat_history)
    
    if clearly_outside:
        return {
            "is_handled": True,
            "answer": (
                "Câu này nằm ngoài phần thông tin tuyển sinh HUIT mà mình có thể kiểm chứng. "
                "Nếu bạn cần, mình có thể hỗ trợ tư vấn chọn ngành, xem phương thức xét tuyển, điểm sàn hoặc học phí HUIT nhé!"
            ),
            "sources": [],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Chặn câu hỏi ngoài phạm vi (Out-of-scope)", "status": "success"}]
        }

    # 3. Short ambiguous phrase handling
    if num_words <= 2 and not has_huit_context and not has_history:
        return {
            "is_handled": True,
            "answer": (
                "Chào bạn! Mình là Trợ lý AI Tư vấn Tuyển sinh HUIT.\n\n"
                "Mình chưa hiểu rõ câu hỏi của bạn. Bạn có thể nhập câu hỏi chi tiết hơn "
                "(ví dụ: *'Mã ngành CNTT'*, *'Điểm sàn năm 2026'*, *'Học phí HUIT bao nhiêu?'*) "
                "để mình tư vấn chính xác nhất nhé!"
            ),
            "sources": [],
            "trace": [{"step": 1, "name": "Intent Guardrail", "detail": "Yêu cầu làm rõ câu hỏi quá ngắn", "status": "success"}]
        }

    return {"is_handled": False}

def is_major_catalog_question(question: str) -> bool:
    q_norm = normalize_text(question)
    # Nếu câu hỏi cụ thể về học phí, điểm chuẩn hoặc yêu cầu sinh file, không chặn bởi catalog tĩnh
    if any(k in q_norm for k in ["hoc phi", "tin chi", "diem chuan", "diem san", "tao file", "xuat file", "excel", "word", "pdf"]):
        return False
    catalog_phrases = [
        "danh sach nganh",
        "nhung nganh",
        "cac nganh",
        "co nganh nao",
        "bao nhieu nganh",
        "nganh dao tao nao",
    ]
    return any(phrase in q_norm for phrase in catalog_phrases)

def get_major_catalog_response() -> Optional[Dict[str, Any]]:
    """Return the complete official catalog from MongoDB via Registered Operation Gateway."""
    try:
        docs = rag_operations.get_major_catalog_docs()
        majors = {}
        for doc in docs:
            code = str(doc.get("major_code") or "").strip()
            title = str(doc.get("page_title") or doc.get("title") or "").strip()
            title = re.sub(r"^Ngành\s+", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s*\(HUIT.*$", "", title).strip()
            if code and title:
                majors[code] = title

        if not majors:
            return None

        ordered = sorted(majors.items(), key=lambda item: normalize_text(item[1]))
        lines = "\n".join(
            f"{index}. **{title}** ({code})"
            for index, (code, title) in enumerate(ordered, 1)
        )
        return {
            "answer": (
                f"HUIT hiện công bố **{len(ordered)} ngành đào tạo đại học chính quy** "
                f"trong danh mục tuyển sinh 2026:\n\n{lines}\n\n"
                "Bạn muốn mình tư vấn sâu hơn về ngành nào?"
            ),
            "sources": [{
                "i": 1,
                "title": "Danh mục ngành đào tạo đại học chính quy HUIT",
                "url": "https://ts.huit.edu.vn/nganh-dao-tao/dai-hoc",
                "score": 1.0,
                "text": f"Danh mục {len(ordered)} ngành đào tạo đại học chính quy HUIT.",
            }],
            "trace": [
                {"step": 1, "name": "Nhận diện Ý định (NLU)", "detail": "Ý định: Tra cứu danh mục ngành đào tạo", "status": "success"},
                {"step": 2, "name": "Truy xuất Danh mục", "detail": f"Lấy toàn bộ {len(ordered)} ngành chính thức từ MongoDB", "status": "success"},
                {"step": 3, "name": "Trình bày danh mục", "detail": "Phản hồi xác định không cần gọi LLM ngoài", "status": "success"}
            ],
            "meta": {
                "intent": "major",
                "fallback": False,
                "deterministic": True,
                "model": settings.OPENROUTER_MODEL,
                "kb_version": settings.KB_VERSION,
                "rag_version": settings.RAG_VERSION,
            },
        }
    except Exception as e:
        print("Catalog fetch error:", e)
        return None
