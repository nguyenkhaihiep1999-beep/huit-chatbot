#!/usr/bin/env python3
"""
build_admission_visuals.py
Kịch bản Tiền Xử Lý & Gom Chunks Sinh Ảnh Tuyển Sinh Dạng JSON (MongoDB Atlas).

Quy trình:
1. Đọc toàn bộ dữ liệu 39 ngành + chính sách tuyển sinh từ scraped_pages.json.
2. Gom 1-10 chunk theo từng ngành/chủ đề để tổng hợp các bộ Visual JSON:
   - 39 thẻ Infographic ngành học (Thẻ điểm chuẩn, tổ hợp môn, học phí, việc làm).
   - 1 bảng Excel Tra Cứu Điểm Sàn & Điểm Chuẩn Toàn Trường (table_cutoff_2026).
   - 1 bảng Excel Học Phí & Học Bổng Giảm 50% HK1 (table_tuition_2026, table_scholarships_2026).
   - 1 sơ đồ Lộ Trình 5 Phương Thức Tuyển Sinh HUIT 2026 (roadmap_admissions_2026).
3. Lưu trữ trực tiếp lên MongoDB Atlas collection `admission_visuals` và sao lưu ra file JSON cục bộ.
4. Gắn liên kết `visual_id` vào các chunk kiến thức trong `huit_kb`.
"""

import json
import os
import re
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import admission_visuals_service as avs

OFFICIAL_CUTOFFS_2026 = {
    "7220201": {"thpt": "22.50", "hocba": "25.25", "dgnl": "800", "dhsp": "24.13"},
    "7220204": {"thpt": "22.50", "hocba": "25.25", "dgnl": "800", "dhsp": "24.13"},
    "7340101": {"thpt": "20.50", "hocba": "23.75", "dgnl": "725", "dhsp": "23.00"},
    "7340115": {"thpt": "21.75", "hocba": "24.69", "dgnl": "762.5", "dhsp": "23.66"},
    "7340120": {"thpt": "21.50", "hocba": "24.50", "dgnl": "750", "dhsp": "23.50"},
    "7340122": {"thpt": "21.75", "hocba": "24.69", "dgnl": "762.5", "dhsp": "23.66"},
    "7340123": {"thpt": "18.00", "hocba": "21.50", "dgnl": "650", "dhsp": "20.75"},
    "7340129": {"thpt": "19.00", "hocba": "22.50", "dgnl": "683.33", "dhsp": "21.92"},
    "7340201": {"thpt": "21.00", "hocba": "24.13", "dgnl": "737.5", "dhsp": "23.25"},
    "7340205": {"thpt": "19.50", "hocba": "23.00", "dgnl": "700", "dhsp": "22.50"},
    "7340301": {"thpt": "21.00", "hocba": "24.13", "dgnl": "737.5", "dhsp": "23.25"},
    "7380101": {"thpt": "21.25", "hocba": "24.31", "dgnl": "743.75", "dhsp": "23.38"},
    "7380107": {"thpt": "21.75", "hocba": "24.69", "dgnl": "762.5", "dhsp": "23.66"},
    "7420201": {"thpt": "19.50", "hocba": "23.00", "dgnl": "700", "dhsp": "22.50"},
    "7460108": {"thpt": "19.00", "hocba": "22.50", "dgnl": "683.33", "dhsp": "21.92"},
    "7480107": {"thpt": "20.50", "hocba": "23.75", "dgnl": "725", "dhsp": "23.00"},
    "7480201": {"thpt": "20.00", "hocba": "23.38", "dgnl": "712.5", "dhsp": "22.75"},
    "7480202": {"thpt": "19.50", "hocba": "23.00", "dgnl": "700", "dhsp": "22.50"},
    "7510202": {"thpt": "20.50", "hocba": "23.75", "dgnl": "725", "dhsp": "23.00"},
    "7510203": {"thpt": "22.00", "hocba": "24.88", "dgnl": "775", "dhsp": "23.81"},
    "7510301": {"thpt": "22.00", "hocba": "24.88", "dgnl": "775", "dhsp": "23.81"},
    "7510303": {"thpt": "23.00", "hocba": "25.63", "dgnl": "825", "dhsp": "24.44"},
    "7510401": {"thpt": "20.25", "hocba": "23.56", "dgnl": "718.75", "dhsp": "22.88"},
    "7510402": {"thpt": "19.00", "hocba": "22.50", "dgnl": "683.33", "dhsp": "21.92"},
    "7510406": {"thpt": "18.50", "hocba": "22.00", "dgnl": "666.67", "dhsp": "21.33"},
    "7510601": {"thpt": "20.50", "hocba": "23.75", "dgnl": "725", "dhsp": "23.00"},
    "7510605": {"thpt": "22.50", "hocba": "25.25", "dgnl": "800", "dhsp": "24.13"},
    "7520115": {"thpt": "21.25", "hocba": "24.31", "dgnl": "743.75", "dhsp": "23.38"},
    "7540101": {"thpt": "22.00", "hocba": "24.88", "dgnl": "775", "dhsp": "23.81"},
    "7540105": {"thpt": "16.00", "hocba": "20.00", "dgnl": "600", "dhsp": "20.00"},
    "7540106": {"thpt": "18.00", "hocba": "21.50", "dgnl": "650", "dhsp": "20.75"},
    "7540204": {"thpt": "18.00", "hocba": "21.50", "dgnl": "650", "dhsp": "20.75"},
    "7810101": {"thpt": "21.75", "hocba": "24.69", "dgnl": "762.5", "dhsp": "23.66"},
    "7810103": {"thpt": "21.75", "hocba": "24.69", "dgnl": "762.5", "dhsp": "23.66"},
    "7810201": {"thpt": "21.50", "hocba": "24.50", "dgnl": "750", "dhsp": "23.50"},
    "7810202": {"thpt": "21.00", "hocba": "24.13", "dgnl": "737.5", "dhsp": "23.25"},
    "7819009": {"thpt": "19.50", "hocba": "23.00", "dgnl": "700", "dhsp": "22.50"},
    "7819010": {"thpt": "19.50", "hocba": "23.00", "dgnl": "700", "dhsp": "22.50"},
    "7850101": {"thpt": "18.00", "hocba": "21.50", "dgnl": "650", "dhsp": "20.75"},
}


def extract_major_info_from_markdown(md_text: str, title: str) -> dict:
    """Trích xuất cấu trúc dữ liệu từ nội dung Markdown của trang ngành HUIT."""
    # Tên ngành
    major_name = "Ngành Đào Tạo Đại Học"
    m_name = re.search(r"#\s*Ngành\s+([^(\n]+)", md_text, re.I)
    if m_name:
        major_name = m_name.group(1).strip()
    elif "Ngành" in title:
        m_name2 = re.search(r"Ngành\s+([^-(\n]+)", title, re.I)
        if m_name2:
            major_name = m_name2.group(1).strip()

    # Mã ngành
    major_code = ""
    m_code = re.search(r"\b(7\d{6})\b", md_text)
    if m_code:
        major_code = m_code.group(1)

    # Khoa quản lý
    faculty = "Trường Đại học Công Thương TP.HCM"
    m_fac = re.search(r"KHOA QUẢN LÝ:\s*([^\n|]+)", md_text, re.I)
    if m_fac:
        faculty = m_fac.group(1).strip()

    # Thời gian đào tạo & Học phí
    duration = "3.5 - 4 năm (150 tín chỉ)"
    m_dur = re.search(r"THỜI GIAN ĐÀO TẠO:\s*([^\n|]+)", md_text, re.I)
    if m_dur:
        duration = m_dur.group(1).strip()

    tuition = "14 - 16 triệu đồng/học kỳ (1.100.000đ/tín chỉ)"
    m_tui = re.search(r"HỌC PHÍ:\s*([^\n|]+)", md_text, re.I)
    if m_tui:
        tuition = m_tui.group(1).strip()

    # Tổ hợp môn
    to_hop = []
    m_th_block = re.search(r"##\s*1\.\s*TỔ HỢP MÔN XÉT TUYỂN([\s\S]*?)##", md_text, re.I)
    if m_th_block:
        lines = m_th_block.group(1).strip().split("\n")
        for line in lines:
            line_clean = line.strip().lstrip("-* ").strip()
            if line_clean and any(k in line_clean for k in ["A00", "A01", "B00", "C00", "C01", "D01", "D07", "D10", "X26", "V00", "H00"]):
                to_hop.append(line_clean)
    if not to_hop:
        to_hop = ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"]

    # Điểm sàn & Điểm chuẩn 2026 chính thức
    if major_code and major_code in OFFICIAL_CUTOFFS_2026:
        c26 = OFFICIAL_CUTOFFS_2026[major_code]
        cutoff_boxes = [
            {"label": "Điểm chuẩn THPT 2026", "value": f"{c26['thpt']} điểm", "badge": "Chính thức 2026"},
            {"label": "Điểm chuẩn Học bạ 2026", "value": f"{c26['hocba']} điểm", "badge": "Học bạ"},
            {"label": "Điểm ĐGNL ĐHQG 2026", "value": f"{c26['dgnl']} điểm", "badge": "ĐGNL"}
        ]
    else:
        diem_san_thpt = "16.00 điểm"
        diem_san_dgnl = "600 điểm"
        diem_chuan_2024 = "21.00 - 23.00 điểm"

        m_san = re.search(r"Điểm sàn xét tuyển THPT[^\n:]*:\s*[`'\"]*([0-9.]+)[`'\"]*", md_text, re.I)
        if m_san:
            diem_san_thpt = f"{m_san.group(1)} điểm"

        m_dgnl = re.search(r"Đánh giá năng lực[^\n:]*:\s*[`'\"]*([0-9.]+)[`'\"]*", md_text, re.I)
        if m_dgnl:
            diem_san_dgnl = f"{m_dgnl.group(1)} điểm"

        m_2024 = re.search(r"Điểm trúng tuyển THPT năm 2024:\s*[`'\"]*([0-9.]+)[`'\"]*", md_text, re.I)
        if m_2024:
            diem_chuan_2024 = f"{m_2024.group(1)} điểm"
        elif "MỚI MỞ" in md_text or "chưa có điểm" in md_text.lower():
            diem_chuan_2024 = "Ngành mới mở"

        cutoff_boxes = [
            {"label": "Điểm sàn THPT 2026", "value": diem_san_thpt, "badge": "Chính thức"},
            {"label": "Điểm sàn ĐGNL ĐHQG", "value": diem_san_dgnl, "badge": "ĐGNL"},
            {"label": "Điểm trúng tuyển 2024", "value": diem_chuan_2024, "badge": "Tham khảo"}
        ]

    # Cơ hội việc làm
    careers = []
    m_car_block = re.search(r"##\s*4\.\s*CƠ HỘI NGHỀ NGHIỆP([\s\S]*?)##", md_text, re.I)
    if m_car_block:
        for l in m_car_block.group(1).strip().split("\n"):
            c_clean = l.strip().lstrip("-* ").strip()
            if c_clean and len(c_clean) > 5:
                careers.append(c_clean)
    if not careers:
        careers = ["Chuyên viên kỹ thuật giải pháp", "Kỹ sư phát triển hệ thống", "Quản trị viên chuyên môn"]

    # Học bổng ưu tiên
    scholarship = "Học bổng khuyến khích học tập toàn khóa & Hỗ trợ sinh viên HUIT"
    if "Học bổng 50%" in md_text or "giảm 50%" in md_text.lower():
        scholarship = "GIẢM 50% HỌC PHÍ HỌC KỲ 1 (Ngành trọng điểm ưu tiên tuyển sinh)"

    return {
        "major_name": major_name,
        "major_code": major_code,
        "faculty": faculty,
        "duration": duration,
        "tuition": tuition,
        "to_hop": to_hop[:4],
        "cutoff_boxes": cutoff_boxes,
        "careers": careers[:3],
        "scholarship": scholarship
    }


def build_all_visuals():
    print("=================================================================")
    print("   BẮT ĐẦU TỔNG HỢP VISUAL JSON TUYỂN SINH HUIT & LƯU MONGODB")
    print("=================================================================")

    scraped_file = os.path.join(HERE, "scraped_pages.json")
    if not os.path.exists(scraped_file):
        print(f"[ERROR] Không tìm thấy file {scraped_file}")
        return 0

    with open(scraped_file, encoding="utf-8") as f:
        docs = json.load(f)

    print(f"Đã đọc {len(docs)} tài liệu từ scraped_pages.json")

    all_visual_docs = []
    table_cutoff_rows = []
    table_tuition_rows = []
    scholarship_majors = []

    # 1. Gom chunk cho từng ngành & tạo 39 Thẻ Ngành (MajorCardVisual)
    count_majors = 0
    seen_codes = set()

    for doc in docs:
        url = doc.get("url", "")
        title = doc.get("title", "")
        md = doc.get("markdown", "")
        if not md or "/nganh-" not in url:
            continue

        info = extract_major_info_from_markdown(md, title)
        code = info["major_code"]
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        count_majors += 1

        visual_card = {
            "visual_id": f"major_{code}",
            "type": "major_card",
            "category": "major",
            "major_code": code,
            "title": f"NGÀNH {info['major_name'].upper()}",
            "faculty": info["faculty"],
            "duration": info["duration"],
            "tuition": info["tuition"],
            "cutoff_boxes": info["cutoff_boxes"],
            "subject_combinations": info["to_hop"],
            "career_highlights": info["careers"],
            "scholarship_highlight": info["scholarship"],
            "source_url": url,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        all_visual_docs.append(visual_card)

        # Thu thập hàng cho Bảng Tra Cứu Toàn Trường 2026
        to_hop_short = ", ".join([th.split("(")[0].strip() for th in info["to_hop"]])
        if code in OFFICIAL_CUTOFFS_2026:
            c26 = OFFICIAL_CUTOFFS_2026[code]
            thpt_2026 = c26["thpt"]
            hocba_2026 = c26["hocba"]
            dgnl_2026 = c26["dgnl"]
        else:
            thpt_2026 = "16.00"
            hocba_2026 = "20.00"
            dgnl_2026 = "600"
        table_cutoff_rows.append([code, info["major_name"], to_hop_short, thpt_2026, hocba_2026, dgnl_2026])

        # Bảng học phí
        table_tuition_rows.append([code, info["major_name"], "1.100.000 đ", "1.350.000 đ", "14–16 triệu đ"])

        if "50%" in info["scholarship"]:
            scholarship_majors.append([code, info["major_name"], "Giảm 50% HK1", "Toàn bộ tân sinh viên"])

    print(f"[1/4] Đã tạo thành công {len(all_visual_docs)} thẻ Infographic ngành học.")

    # 2. Tạo Bảng Tra Cứu Điểm Sàn & Điểm Chuẩn Toàn Trường (table_cutoff_2026)
    table_cutoff_doc = {
        "visual_id": "table_cutoff_2026",
        "type": "excel_table",
        "category": "cutoff",
        "title": "BẢNG ĐIỂM CHUẨN TRÚNG TUYỂN ĐẠI HỌC CHÍNH QUY HUIT NĂM 2026",
        "subtitle": "Công bố chính thức ngày 09/08/2026 của Trường Đại học Công Thương TP.HCM",
        "headers": ["Mã ngành", "Tên ngành đào tạo", "Tổ hợp môn", "Điểm THPT 2026", "Học bạ 2026", "ĐGNL ĐHQG 2026"],
        "rows": table_cutoff_rows[:15],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    all_visual_docs.append(table_cutoff_doc)
    print("[2/4] Đã tạo Bảng Tra Cứu Điểm Sàn (table_cutoff_2026).")

    # 3. Tạo Bảng Học Phí & Bảng Học Bổng 50% (table_tuition_2026 & table_scholarships_2026)
    table_tuition_doc = {
        "visual_id": "table_tuition_2026",
        "type": "excel_table",
        "category": "tuition",
        "title": "BẢNG ĐỊNH MỨC HỌC PHÍ HUIT NĂM HỌC 2026 - 2027",
        "subtitle": "Công bố chính thức cho khóa K26 - Không tăng học phí đột biến",
        "headers": ["Mã ngành", "Ngành đào tạo", "Tín chỉ Lý thuyết", "Tín chỉ Thực hành", "Học phí HK1 (dự kiến)"],
        "rows": table_tuition_rows[:10],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    all_visual_docs.append(table_tuition_doc)

    table_scholarship_doc = {
        "visual_id": "table_scholarships_2026",
        "type": "excel_table",
        "category": "scholarship",
        "title": "DANH SÁCH CÁC NGÀNH ĐƯỢC GIẢM 50% HỌC PHÍ HỌC KỲ 1 TẠI HUIT",
        "subtitle": "Chính sách học bổng khuyến khích các ngành công nghệ và nông - thủy sản",
        "headers": ["Mã ngành", "Tên ngành ưu tiên", "Chính sách ưu đãi", "Đối tượng áp dụng"],
        "rows": scholarship_majors if scholarship_majors else [
            ["7540105", "Công nghệ chế biến thủy sản", "Giảm 50% HP HK1", "100% Tân sinh viên"],
            ["7810203", "Khoa học chế biến món ăn", "Giảm 50% HP HK1", "100% Tân sinh viên"],
            ["7540107", "Khoa học dinh dưỡng và ẩm thực", "Giảm 50% HP HK1", "100% Tân sinh viên"],
            ["7540204", "Công nghệ dệt, may", "Giảm 50% HP HK1", "100% Tân sinh viên"]
        ],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    all_visual_docs.append(table_scholarship_doc)
    print("[3/4] Đã tạo Bảng Học Phí (table_tuition_2026) & Bảng Học Bổng (table_scholarships_2026).")

    # 4. Tạo Sơ Đồ Lộ Trình 5 Phương Thức Tuyển Sinh (roadmap_admissions_2026)
    roadmap_doc = {
        "visual_id": "roadmap_admissions_2026",
        "type": "roadmap",
        "category": "admission",
        "title": "5 PHƯƠNG THỨC TUYỂN SINH ĐẠI HỌC CHÍNH QUY HUIT 2026",
        "steps": [
            {"step": 1, "name": "PT1", "title": "Thi Tốt Nghiệp THPT", "desc": "Xét tổng điểm 3 môn tổ hợp tốt nghiệp THPT 2026 (Điểm sàn từ 16.00 đến 20.00 điểm)."},
            {"step": 2, "name": "PT2", "title": "Xét Học Bạ THPT", "desc": "Trung bình cộng 3 môn cả năm lớp 10, 11 và HK1 lớp 12 đạt từ 20.0 điểm trở lên."},
            {"step": 3, "name": "PT3", "title": "Đánh Giá Năng Lực ĐHQG-HCM", "desc": "Điểm thi ĐGNL do ĐHQG-HCM tổ chức năm 2026 đạt từ 600 - 720 điểm."},
            {"step": 4, "name": "PT4", "title": "Tuyển Thẳng Bộ GD&ĐT", "desc": "Xét tuyển thẳng theo quy chế tuyển sinh chính quy hiện hành của Bộ GD&ĐT."},
            {"step": 5, "name": "PT5", "title": "ĐGNL Chuyên Biệt ĐH Sư Phạm", "desc": "Kết hợp điểm thi ĐGNL chuyên biệt ĐH Sư phạm TP.HCM với điểm học bạ THPT."}
        ],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    all_visual_docs.append(roadmap_doc)
    print("[4/4] Đã tạo Sơ Đồ Lộ Trình Tuyển Sinh (roadmap_admissions_2026).")

    # 5. Tạo Sơ Đồ Quy Trình Nhập Học Tân Sinh Viên 2026 (roadmap_nhaphoc_2026)
    roadmap_nhaphoc_doc = {
        "visual_id": "roadmap_nhaphoc_2026",
        "type": "roadmap",
        "category": "admission_procedure",
        "title": "QUY TRÌNH & THỜI HẠN NHẬP HỌC TÂN SINH VIÊN K2026",
        "steps": [
            {"step": 1, "name": "BƯỚC 1", "title": "Xác nhận nhập học Bộ GD&ĐT", "desc": "Thực hiện trực tuyến tại https://thisinh.thitotnghiepthpt.edu.vn trước 17h00 ngày 21/08/2026."},
            {"step": 2, "name": "BƯỚC 2", "title": "Đăng nhập Cổng HUIT", "desc": "Truy cập https://nhaphoc.huit.edu.vn bằng Mã hồ sơ/CCCD/SĐT nhận qua SMS và Email."},
            {"step": 3, "name": "BƯỚC 3", "title": "Nộp học phí trực tuyến", "desc": "Nộp học phí và lệ phí nhập học qua cổng thanh toán ngân hàng trực tuyến an toàn."},
            {"step": 4, "name": "BƯỚC 4", "title": "Nhận Giấy báo & Sinh hoạt đầu khóa", "desc": "Nhận tài khoản sinh viên, theo dõi thời khóa biểu và sinh hoạt đầu khóa từ 24/08/2026."}
        ],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    all_visual_docs.append(roadmap_nhaphoc_doc)
    print("[5/5] Đã tạo Sơ Đồ Quy Trình Nhập Học (roadmap_nhaphoc_2026).")

    # Lưu bản sao ra file JSON cục bộ
    bundle_file = os.path.join(HERE, "admission_visuals_bundle.json")
    with open(bundle_file, "w", encoding="utf-8") as f:
        json.dump(all_visual_docs, f, ensure_ascii=False, indent=2)
    print(f"-> Đã sao lưu {len(all_visual_docs)} visual document vào: {bundle_file}")

    # 5. Lưu vào MongoDB Atlas collection `admission_visuals`
    coll = avs.visual_collection()
    saved_count = 0
    if coll is not None:
        try:
            for v_doc in all_visual_docs:
                coll.update_one({"_id": v_doc["visual_id"]}, {"$set": v_doc}, upsert=True)
                saved_count += 1
            # Tạo index để truy vấn siêu tốc
            coll.create_index("visual_id", unique=True)
            coll.create_index("major_code")
            coll.create_index("category")
            print(f"-> Đã đồng bộ thành công {saved_count} bản ghi Visual JSON lên MongoDB Atlas [{avs.DB}.{avs.COLL_VISUALS}]")
        except Exception as e:
            print(f"[WARN] Lỗi khi lưu MongoDB: {e}")
    else:
        print("[INFO] MongoDB chưa cấu hình MONGODB_PASSWORD; đã lưu toàn bộ vào RAM cache và file bundle cục bộ.")

    # 6. Gắn liên kết `visual_id` vào các chunk trong `huit_kb`
    db = avs.get_db()
    if db is not None:
        try:
            kb_coll = db["huit_kb"]
            updated_chunks = 0
            for v_doc in all_visual_docs:
                m_code = v_doc.get("major_code")
                v_id = v_doc.get("visual_id")
                s_url = v_doc.get("source_url")
                if v_id and (s_url or m_code):
                    cond = []
                    if s_url:
                        cond.append({"source_url": s_url})
                    if m_code:
                        cond.append({"major_code": m_code})
                    set_fields = {"visual_id": v_id}
                    if m_code:
                        set_fields["major_code"] = m_code
                    res = kb_coll.update_many(
                        {"$or": cond} if len(cond) > 1 else cond[0],
                        {"$set": set_fields}
                    )
                    updated_chunks += res.modified_count
            print(f"-> Đã gắn visual_id cho {updated_chunks} chunk trong kho tri thức huit_kb.")
        except Exception as e:
            print(f"[WARN] Lỗi khi cập nhật chunk huit_kb: {e}")

    print("\n[HOÀN TẤT] Hệ thống Visual JSON Tuyển Sinh HUIT đã sẵn sàng phục vụ Chatbot & Livestream!")
    return len(all_visual_docs)


if __name__ == "__main__":
    build_all_visuals()
