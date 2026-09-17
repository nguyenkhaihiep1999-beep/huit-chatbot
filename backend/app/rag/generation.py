import os
import re
from typing import Generator, List, Tuple, Optional
from openai import OpenAI
from backend.app.config import settings
from backend.app.rag.intent import normalize_text, classify_intent

def clean_llm_text(text: str) -> str:
    if not text:
        return ""
    # Strip unwanted system headers / preambles like "User Safety: safe", "<think>...", "Here is the answer:"
    text = re.sub(r"^(User Safety:\s*safe|User Safety:\s*\w+|Safety status:\s*\w+)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^(here is the answer|we need to answer|here's the response):\s*", "", text, flags=re.IGNORECASE)
    return text.strip()

def get_llm_endpoints() -> List[Tuple[OpenAI, str, str]]:
    """Build prioritized multi-provider LLM endpoint list (Gemini Direct -> Groq Direct -> OpenRouter)."""
    endpoints = []

    # 1. Google Gemini Direct API
    if settings.GEMINI_API_KEY:
        try:
            client = OpenAI(api_key=settings.GEMINI_API_KEY, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
            for m in [settings.GEMINI_MODEL, "gemini-1.5-flash", "gemini-1.5-flash-8b"]:
                endpoints.append((client, m, "GeminiDirect"))
        except Exception as e:
            print("Gemini Direct init warning:", e)

    # 2. Groq Direct API (14,400 free requests/day)
    if settings.GROQ_API_KEY:
        try:
            client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            for m in [
                "openai/gpt-oss-120b",
                "openai/gpt-oss-20b",
                "qwen/qwen3.8-27b",
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant"
            ]:
                endpoints.append((client, m, "GroqDirect"))
        except Exception as e:
            print("Groq Direct init warning:", e)

    # 3. OpenRouter API (Fallback)
    if settings.OPENROUTER_KEY:
        try:
            client = OpenAI(api_key=settings.OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
            for m in [
                settings.OPENROUTER_MODEL,
                "qwen/qwen-2.5-72b-instruct",
                "google/gemma-4-26b-a4b-it:free",
                "google/gemma-4-31b-it:free",
                "openrouter/free",
            ]:
                endpoints.append((client, m, "OpenRouter"))
        except Exception as e:
            print("OpenRouter init warning:", e)

    return endpoints

def call_llm(system_prompt: str, user_prompt: str) -> str:
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    endpoints = get_llm_endpoints()
    if not endpoints:
        raise RuntimeError("Chưa cấu hình API Key cho bất kỳ nhà cung cấp LLM nào (Gemini, Groq, OpenRouter).")

    last_error = None
    for client, model_name, provider in endpoints:
        try:
            r = client.chat.completions.create(
                model=model_name,
                messages=msgs,
                temperature=0.3,
                max_tokens=settings.LLM_MAX_TOKENS,
                timeout=25,
            )
            if r and r.choices and r.choices[0].message.content:
                content = r.choices[0].message.content.strip()
                content = clean_llm_text(content)
                leaked_reasoning = (
                    content.lower().startswith(("we need to answer", "we need answer"))
                    or "must end with a short question" in content.lower()
                    or "provide answer in vietnamese" in content.lower()
                )
                if leaked_reasoning or len(content) < 25:
                    continue
                return content
        except Exception as e:
            print(f"LLM Provider '{provider}' Model '{model_name}' warning:", e)
            last_error = e
            continue

    raise RuntimeError(f"Tất cả nhà cung cấp LLM đều tạm thời gián đoạn. Lỗi gần nhất: {last_error}")

def stream_llm(system_prompt: str, user_prompt: str) -> Generator[str, None, None]:
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    endpoints = get_llm_endpoints()
    if not endpoints:
        raise RuntimeError("Chưa cấu hình API Key cho bất kỳ nhà cung cấp LLM nào (Gemini, Groq, OpenRouter).")

    last_error = None
    for client, model_name, provider in endpoints:
        try:
            stream = client.chat.completions.create(
                model=model_name,
                messages=msgs,
                temperature=0.3,
                max_tokens=settings.LLM_MAX_TOKENS,
                timeout=25,
                stream=True,
            )
            buffer = ""
            header_cleaned = False
            token_yielded_count = 0

            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0 and chunk.choices[0].delta:
                    token = chunk.choices[0].delta.content or ""
                    if not token:
                        continue
                    
                    if not header_cleaned:
                        buffer += token
                        if len(buffer) >= 50 or "\n" in buffer:
                            cleaned_buffer = clean_llm_text(buffer)
                            header_cleaned = True
                            if cleaned_buffer:
                                token_yielded_count += 1
                                yield cleaned_buffer
                        continue
                    else:
                        token_yielded_count += 1
                        yield token

            if not header_cleaned and buffer:
                cleaned_buffer = clean_llm_text(buffer)
                if cleaned_buffer:
                    token_yielded_count += 1
                    yield cleaned_buffer

            if token_yielded_count > 0:
                return

        except Exception as e:
            print(f"LLM Provider '{provider}' Streaming Model '{model_name}' warning:", e)
            last_error = e
            continue

    raise RuntimeError(f"Tất cả nhà cung cấp LLM đều tạm thời gián đoạn. Lỗi gần nhất: {last_error}")

def fallback_answer(question: str, docs: List[dict]) -> str:
    """Create a concise grounded answer when LLM streaming is unavailable or truncated."""
    if not docs:
        return "Hiện chưa tìm thấy thông tin chi tiết phù hợp trong kho tri thức tuyển sinh HUIT. Bạn vui lòng đặt câu hỏi cụ thể hơn hoặc liên hệ hotline Cổng tuyển sinh HUIT nhé!"

    q_normalized = normalize_text(question)
    intent = classify_intent(question)

    # 1. Tuition
    if intent == "tuition" or any(k in q_normalized for k in ["hoc phi", "tin chi", "tien hoc", "muc phi", "chi phi"]):
        return (
            "Theo công bố cho khóa K26 năm 2026, học phí HUIT là "
            "**1.100.000 đồng/tín chỉ lý thuyết** và **1.350.000 đồng/tín chỉ "
            "thực hành**. Các ngành cử nhân phổ biến khoảng **143–148 triệu "
            "đồng/toàn khóa**, chương trình kỹ sư khoảng **177–188 triệu đồng/toàn khóa**. [1]"
        )

    # 2. Cutoff Scores
    if intent in ("cutoff", "floor_score") or any(k in q_normalized for k in ["diem san", "diem chuan", "diem trung tuyen"]):
        is_floor = (intent == "floor_score" or "diem san" in q_normalized or "nguong dam bao" in q_normalized) and not any(k in q_normalized for k in ["chuan", "trung tuyen"])
        if is_floor:
            is_law = "luat" in q_normalized
            if "danh gia nang luc" in q_normalized:
                score = "720" if is_law else "600"
                return (
                    f"Điểm sàn Đánh giá năng lực ĐHQG-HCM năm 2026 HUIT là **{score} điểm** "
                    f"cho {'nhóm Luật và Luật kinh tế' if is_law else 'các ngành ngoài nhóm Luật'}. [1]"
                )
            score = "20" if is_law else "16"
            return (
                f"Điểm sàn xét điểm thi THPT năm 2026 HUIT là **{score} điểm** "
                f"cho {'nhóm Luật' if is_law else 'các ngành ngoài nhóm Luật'}. Điểm sàn xét học bạ là 20 điểm. [1]"
            )
        else:
            if "tri tue nhan tao" in q_normalized or "ai" in q_normalized:
                return "Theo công bố điểm chuẩn trúng tuyển chính thức năm 2026 của HUIT (ngày 09/08/2026), ngành **Trí tuệ nhân tạo (Mã ngành: 7480107)** có điểm chuẩn theo điểm thi tốt nghiệp THPT là **20.50 điểm**, xét theo học bạ THPT là **23.50 điểm** và ĐGNL ĐHQG-HCM là **700 điểm**. [1]"
            if "cong nghe thong tin" in q_normalized or "cntt" in q_normalized:
                return "Theo công bố điểm chuẩn trúng tuyển chính thức năm 2026 của HUIT (ngày 09/08/2026), ngành **Công nghệ thông tin (Mã ngành: 7480201)** có điểm chuẩn theo điểm thi tốt nghiệp THPT là **20.00 điểm**, xét theo học bạ THPT là **24.50 điểm** và ĐGNL ĐHQG-HCM là **750 điểm**. [1]"
            if "tu dong hoa" in q_normalized or "dieu khien" in q_normalized:
                return "Theo công bố chính thức ngày 09/08/2026 của HUIT, ngành lấy điểm chuẩn cao nhất trường là **Công nghệ kỹ thuật điều khiển và tự động hóa** với mức **23.00 điểm** (điểm thi THPT) và 25.63 điểm (xét học bạ THPT). [1]"
            return (
                "Trường Đại học Công Thương TP.HCM (HUIT) đã **CHÍNH THỨC CÔNG BỐ Điểm chuẩn trúng tuyển năm 2026** vào ngày 09/08/2026:\n\n"
                "- **Phương thức Điểm thi tốt nghiệp THPT**: Dao động từ **16.00 đến 23.00 điểm**.\n"
                "  + Ngành cao nhất: *Công nghệ kỹ thuật điều khiển và tự động hóa* (**23.00 điểm**).\n"
                "  + *Logistics và Quản lý chuỗi cung ứng*: **22.50 điểm**.\n"
                "  + *Công nghệ thực phẩm*, *Công nghệ kỹ thuật điện - điện tử*: **22.00 điểm**.\n"
                "  + *Marketing*, *Thương mại điện tử*, *Luật kinh tế*: **21.75 điểm**.\n"
                "  + *Trí tuệ nhân tạo*: **20.50 điểm** | *Công nghệ thông tin*: **20.00 điểm**.\n"
                "  + Các ngành 18.0 điểm: *Công nghệ dệt, may*; thấp nhất là *Công nghệ chế biến thủy sản* (**16.00 điểm**).\n"
                "- **Phương thức Học bạ THPT**: Từ **20.00 đến 25.63 điểm**.\n"
                "- **Phương thức ĐGNL ĐHQG-HCM**: Từ **600 đến 825 điểm**. [1]"
            )

    # 3. Admission procedure / Tuition refund
    if intent == "admission_procedure" or any(k in q_normalized for k in ["nhap hoc", "thu tuc nhap hoc", "thoi gian nhap hoc", "ho so nhap hoc", "rut hoc phi"]):
        if any(k in q_normalized for k in ["rut hoc phi", "hoan hoc phi"]):
            return (
                "Theo Thông báo ngày 14/08/2026 của HUIT về việc rút học phí đối với sinh viên nhập học năm học 2026 - 2027:\n\n"
                "- Sinh viên có nguyện vọng rút học phí cần chuẩn bị: Đơn xin rút học phí (theo mẫu HUIT), Phiếu thu/Biên lai nộp tiền hoặc sao kê, Bản sao CCCD và minh chứng lý do chính đáng.\n"
                "- Nộp trực tiếp tại Phòng Tài chính - Kế toán phối hợp Phòng Công tác Sinh viên (140 Lê Trọng Tấn, P. Tây Thạnh, Q. Tân Phú, TP.HCM). Hotline: 096 205 1080. [1]"
            )
        return (
            "Theo Thông báo nhập học chính thức đối với Tân sinh viên khóa 2026 của Trường Đại học Công Thương TP.HCM (HUIT):\n\n"
            "- **Thời gian làm thủ tục**: Từ ngày **12/08/2026 đến hết 17h00 ngày 21/08/2026** (làm việc tất cả các ngày trong tuần, kể cả Thứ Bảy và Chủ Nhật).\n"
            "- **Quy trình nhập học 2 bước bắt buộc**:\n"
            "  1. **Bước 1**: Xác nhận nhập học trực tuyến trên Cổng thông tin của Bộ GD&ĐT (https://thisinh.thitotnghiepthpt.edu.vn/) trước 17h00 ngày 21/08/2026.\n"
            "  2. **Bước 2**: Nộp học phí và làm thủ tục trực tuyến tại Cổng nhập học HUIT (https://nhaphoc.huit.edu.vn) bằng mã hồ sơ/CCCD/SĐT đã nhận qua SMS/Email.\n"
            "- **Địa điểm hỗ trợ trực tiếp**: Trụ sở chính HUIT, số 140 Lê Trọng Tấn, P. Tây Thạnh, Q. Tân Phú, TP.HCM.\n"
            "- **Lịch sinh hoạt đầu khóa**: Dự kiến bắt đầu từ ngày **24/08/2026**. [1]"
        )

    # 4. Admission methods
    if intent == "admission" or any(k in q_normalized for k in ["phuong thuc", "xet hoc ba", "tuyen thang"]):
        return (
            "Năm 2026, HUIT áp dụng 5 phương thức xét tuyển: 1) Điểm thi tốt nghiệp THPT, "
            "2) Học bạ THPT (lớp 10, 11 và HK1 lớp 12), 3) Đánh giá năng lực ĐHQG-HCM, "
            "4) Tuyển thẳng theo quy định Bộ GD&ĐT, 5) Bài thi năng lực chuyên biệt ĐH Sư phạm TP.HCM kết hợp học bạ. [1]"
        )

    # 5. Dynamic grounded fallback matching TOP retrieved document content
    if docs and len(docs) > 0:
        top_doc = docs[0]
        doc_text = top_doc.get("text", "")
        clean_text = re.sub(r"^\[.*?\]\s*", "", doc_text).strip()
        if len(clean_text) > 400:
            clean_text = clean_text[:400] + "..."
        if clean_text:
            return (
                f"Theo thông tin tuyển sinh chính thức từ HUIT:\n\n"
                f"{clean_text}\n\n"
                f"Bạn có cần hỗ trợ chi tiết hơn về tổ hợp môn, điểm sàn hay phương thức xét tuyển không? [1]"
            )

    return "Hiện chưa tìm thấy thông tin chi tiết phù hợp trong kho tri thức tuyển sinh HUIT. Bạn vui lòng liên hệ hotline Cổng tuyển sinh HUIT nhé!"
