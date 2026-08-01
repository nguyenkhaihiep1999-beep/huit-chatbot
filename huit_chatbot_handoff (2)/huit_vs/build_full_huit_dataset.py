#!/usr/bin/env python3
"""
build_full_huit_dataset.py
Tạo và cập nhật bộ dữ liệu toàn diện 39 ngành đào tạo Đại học chính quy HUIT 
cùng các thông báo tuyển sinh, điểm sàn, học phí, học bổng, phương thức xét tuyển real-time mới nhất.
Xuất dữ liệu ra scraped_pages.json và urls_to_scrape.json.
"""

import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPED_JSON = os.path.join(HERE, "scraped_pages.json")
URLS_JSON = os.path.join(HERE, "urls_to_scrape.json")

# Danh mục 39 Ngành đào tạo đại học chính quy HUIT kèm thông tin chi tiết
MAJORS_DATA = [
    {
        "code": "7480107",
        "name": "Trí tuệ nhân tạo",
        "slug": "nganh-tri-tue-nhan-tao",
        "is_new": True,
        "combinations": ["A00 (Toán, Lý, Hóa)", "C01 (Văn, Toán, Lý)", "D01 (Toán, Văn, Anh)", "X26 (Toán, Anh, Tin)"],
        "quota": 100,
        "cutoffs": {"2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ thông tin",
        "duration": "3.5 năm (153 tín chỉ - Cử nhân / Kỹ sư)",
        "tuition": "14 - 16 triệu đồng/học kỳ (540.000đ - 700.000đ/tín chỉ)",
        "description": "Đào tạo kiến thức nền tảng và chuyên sâu về Toán học cho AI, Machine Learning, Deep Learning, Xử lý ngôn ngữ tự nhiên (NLP), Thị giác máy tính (Computer Vision), Hệ thống đa tác tử, Big Data, LLM và AI Tạo sinh (Generative AI).",
        "careers": [
            "Kỹ sư phát triển ứng dụng Trí tuệ nhân tạo (AI Engineer)",
            "Chuyên viên Phân tích và Xử lý Dữ liệu (Data Analyst / Data Scientist)",
            "Kỹ sư Học máy và Deep Learning (Machine Learning Engineer)",
            "Chuyên viên Thiết kế và Triển khai Giải pháp AI / Chatbot trong doanh nghiệp",
            "Nghiên cứu viên R&D tại các tập đoàn công nghệ và trung tâm dữ liệu"
        ]
    },
    {
        "code": "7480201",
        "name": "Công nghệ thông tin",
        "slug": "nganh-cong-nghe-thong-tin",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 350,
        "cutoffs": {"2024_thpt": "22.50", "2024_hocba": "24.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ thông tin",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Trang bị kiến thức lập trình phần mềm, phát triển web/mobile, quản trị mạng, điện toán đám mây, kiến trúc hệ thống thông tin, cơ sở dữ liệu và an ninh mạng.",
        "careers": [
            "Lập trình viên Software / Web / Mobile Developer",
            "Kỹ sư Điện toán đám mây & DevOps",
            "Chuyên viên Kiểm thử phần mềm (QA/QC Engineer)",
            "Quản trị viên Hệ thống và Cơ sở dữ liệu (DBA)",
            "Kỹ sư Giải pháp Công nghệ thông tin"
        ]
    },
    {
        "code": "7480202",
        "name": "An toàn thông tin",
        "slug": "nganh-an-toan-thong-tin",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 120,
        "cutoffs": {"2024_thpt": "21.50", "2024_hocba": "23.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ thông tin",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Đào tạo chuyên sâu về bảo mật mạng, mật mã học, kiểm thử xâm nhập (Penetration Testing), điều tra vết kỹ thuật số (Digital Forensics), bảo vệ hệ thống thông tin doanh nghiệp.",
        "careers": [
            "Chuyên viên Bảo mật Hệ thống (Cyber Security Specialist)",
            "Chuyên viên Kiểm thử Xâm nhập (Pentester / Ethical Hacker)",
            "Kỹ sư An toàn Mạng & SOC Analyst",
            "Chuyên viên Điều tra Tội phạm Kỹ thuật số (Digital Forensics)",
            "Tư vấn An toàn Thông tin Doanh nghiệp"
        ]
    },
    {
        "code": "7460108",
        "name": "Khoa học dữ liệu",
        "slug": "nganh-khoa-hoc-du-lieu",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "21.00", "2024_hocba": "23.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ thông tin",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Chuyên về thu thập, làm sạch, khai phá dữ liệu lớn (Big Data Mining), thống kê ứng dụng, xây dựng thuật toán dự báo kinh doanh và trí tuệ kinh doanh (Business Intelligence).",
        "careers": [
            "Chuyên viên Dữ liệu (Data Scientist)",
            "Kỹ sư Dữ liệu (Data Engineer)",
            "Chuyên viên Trí tuệ Kinh doanh (BI Analyst)",
            "Chuyên viên Phân tích Thị trường và Hành vi Khách hàng"
        ]
    },
    {
        "code": "7540101",
        "name": "Công nghệ thực phẩm",
        "slug": "nganh-cong-nghe-thuc-pham",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 450,
        "cutoffs": {"2024_thpt": "22.50", "2024_hocba": "24.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ thực phẩm (Thế mạnh cốt lõi số 1 của HUIT)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Ngành đào tạo thế mạnh lâu đời nhất của HUIT. Đào tạo quy trình chế biến, bảo quản thực phẩm, nghiên cứu phát triển sản phẩm mới (R&D), quản lý chất lượng thực phẩm (HACCP, ISO 22000), công nghệ đồ uống, bánh kẹo, thịt cá.",
        "careers": [
            "Kỹ sư Nghiên cứu và Phát triển Sản phẩm Thực phẩm (R&D)",
            "Kỹ sư Quản lý Chất lượng Thực phẩm (QA/QC)",
            "Quản lý Phân xưởng/Nhà máy Sản xuất Thực phẩm",
            "Chuyên viên Kiểm nghiệm và Giám định Thực phẩm",
            "Chuyên gia Tư vấn An toàn Thực phẩm"
        ]
    },
    {
        "code": "7540106",
        "name": "Đảm bảo chất lượng và an toàn thực phẩm",
        "slug": "nganh-dam-bao-chat-luong-va-an-toan-thuc-pham",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 120,
        "cutoffs": {"2024_thpt": "20.50", "2024_hocba": "22.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ thực phẩm",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Đào tạo các tiêu chuẩn chất lượng ISO, BRC, IFS, GMP, HACCP, vi sinh thực phẩm, độc tố học thực phẩm, luật thực phẩm quốc tế và đánh giá rủi ro an toàn thực phẩm.",
        "careers": [
            "Chuyên viên Đảm bảo Chất lượng QA/QC Thực phẩm",
            "Chuyên viên Đánh giá Tiêu chuẩn An toàn Thực phẩm",
            "Thanh tra viên An toàn Thực phẩm tại cơ quan nhà nước",
            "Quản lý Hệ thống Chất lượng tại tập đoàn đa quốc gia"
        ]
    },
    {
        "code": "7540105",
        "name": "Công nghệ chế biến thủy sản",
        "slug": "nganh-cong-nghe-che-bien-thuy-san",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "17.00", "2024_hocba": "20.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Thủy sản (Được hưởng Học bổng 50% HP HK1)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Đào tạo kỹ thuật chế biến đông lạnh, đồ hộp thủy hải sản, chiết xuất hợp chất sinh học từ phụ phẩm thủy sản, xuất nhập khẩu thủy sản sang EU, Mỹ, Nhật.",
        "careers": [
            "Kỹ sư Công nghệ Chế biến Thủy sản",
            "Chuyên viên Quản lý Chất lượng Xuất khẩu Thủy sản",
            "Quản lý Quá trình Đông lạnh và Đóng hộp Thủy sản",
            "Chuyên viên R&D Sản phẩm Thủy hải sản Giá trị gia tăng"
        ]
    },
    {
        "code": "7540107",
        "name": "Khoa học dinh dưỡng và ẩm thực",
        "slug": "nganh-khoa-hoc-dinh-duong-va-am-thuc",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "19.00", "2024_hocba": "21.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ thực phẩm (Học bổng 50% HP HK1)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Kết hợp khoa học dinh dưỡng cơ thể người, xây dựng khẩu phần ăn lý tưởng, tư vấn dinh dưỡng lâm sàng, phân tích hóa học thực phẩm và khoa học nghệ thuật ẩm thực.",
        "careers": [
            "Chuyên viên Tư vấn Dinh dưỡng tại trung tâm y tế / spa / thể thao",
            "Kỹ sư Phát triển Thực phẩm Dinh dưỡng và Dược phẩm",
            "Chuyên gia Xây dựng Thực đơn Dinh dưỡng Khách sạn / Bệnh viện",
            "Chuyên viên Kiểm định Dinh dưỡng Thực phẩm"
        ]
    },
    {
        "code": "7810203",
        "name": "Khoa học chế biến món ăn",
        "slug": "nganh-khoa-hoc-che-bien-mon-an",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "18.00", "2024_hocba": "20.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Dịch vụ du lịch & Ẩm thực (Học bổng 50% HP HK1)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Đào tạo nghệ thuật và kỹ thuật chế biến món ăn Á - Âu nâng cao, quản lý bếp chuyên nghiệp, thiết kế thực đơn cao cấp, khoa học kết hợp hương vị và dinh dưỡng.",
        "careers": [
            "Bếp trưởng / Quản lý Bếp tại Khách sạn 5 sao & Nhà hàng Quốc tế",
            "Chuyên gia Sáng tạo Ẩm thực (Culinary Director)",
            "Chuyên viên Nghiên cứu và Phát triển Công thức Món ăn",
            "Chủ Doanh nghiệp Dịch vụ Ẩm thực & Catering"
        ]
    },
    {
        "code": "7340115",
        "name": "Marketing",
        "slug": "nganh-marketing",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 300,
        "cutoffs": {"2024_thpt": "23.00", "2024_hocba": "25.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Quản trị kinh doanh (Ngành có điểm trúng tuyển TOP đầu HUIT)",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Đào tạo Digital Marketing, Truyền thông thương hiệu, Content Marketing, Quảng cáo số (Facebook/Google/TikTok Ads), Nghiên cứu thị trường và Quản trị quan hệ khách hàng (CRM).",
        "careers": [
            "Chuyên viên Digital Marketing & SEO/SEM",
            "Chuyên viên Sáng tạo Nội dung (Content Creator / Copywriter)",
            "Quản trị Thương hiệu (Brand Manager)",
            "Chuyên viên Nghiên cứu Thị trường & Data Marketing",
            "Account Executive tại các Marketing Agency"
        ]
    },
    {
        "code": "7340120",
        "name": "Kinh doanh quốc tế",
        "slug": "nganh-kinh-doanh-quoc-te",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 250,
        "cutoffs": {"2024_thpt": "22.75", "2024_hocba": "24.75", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Quản trị kinh doanh",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Chuyên về Thương mại Quốc tế, Xuất nhập khẩu, Thanh toán Quốc tế, Đầu tư Quốc tế, Marketing Toàn cầu và Đàm phán Thương mại Quốc tế.",
        "careers": [
            "Chuyên viên Xuất Nhập Khẩu (Import-Export Specialist)",
            "Chuyên viên Thanh toán Quốc tế tại Ngân hàng",
            "Chuyên viên Phát triển Thị trường Toàn cầu",
            "Chuyên viên Logistics & Chuỗi Cung ứng Quốc tế"
        ]
    },
    {
        "code": "7510605",
        "name": "Logistics và quản lý chuỗi cung ứng",
        "slug": "nganh-logistic-va-quan-ly-chuoi-cung-ung",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 250,
        "cutoffs": {"2024_thpt": "22.50", "2024_hocba": "24.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Quản lý công nghiệp & Logistics",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Đào tạo quản lý kho vận, giao nhận vận tải đa phương thức, mua hàng (Procurement), quản trị chuỗi cung ứng toàn cầu, tối ưu hóa chi phí vận chuyển.",
        "careers": [
            "Chuyên viên Điều phối Logistics & Vận tải",
            "Quản trị Kho hàng & Giao nhận (Warehouse Manager)",
            "Chuyên viên Mua hàng & Quản lý Cung ứng (Procurement Officer)",
            "Chuyên viên Giao nhận Xuất nhập khẩu & Forwarding"
        ]
    },
    {
        "code": "7340101",
        "name": "Quản trị kinh doanh",
        "slug": "nganh-quan-tri-kinh-doanh",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 300,
        "cutoffs": {"2024_thpt": "21.75", "2024_hocba": "23.75", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Quản trị kinh doanh",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Trang bị tư duy quản trị doanh nghiệp tổng thể, chiến lược kinh doanh, quản trị nhân sự, điều hành sản xuất, quản trị tài chính doanh nghiệp và khởi nghiệp.",
        "careers": [
            "Chuyên viên Khởi nghiệp & Điều hành Doanh nghiệp",
            "Chuyên viên Phát triển Dự án Kinh doanh",
            "Quản lý Kinh doanh (Sales / Business Development Manager)",
            "Trợ lý Giám đốc & Tư vấn Chiến lược"
        ]
    },
    {
        "code": "7340122",
        "name": "Thương mại điện tử",
        "slug": "nganh-thuong-mai-dien-tu",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 200,
        "cutoffs": {"2024_thpt": "22.00", "2024_hocba": "24.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Quản trị kinh doanh",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Khai thác kinh doanh trên sàn Shopee, Lazada, TikTok Shop, Amazon; thiết kế hệ thống gian hàng số, thanh toán điện tử, tiếp thị liên kết (Affiliate Marketing).",
        "careers": [
            "Chuyên viên Vận hành Sàn Thương mại Điện tử (E-commerce Operation)",
            "Quản lý Gian hàng Số & TikTok Shop / Shopee / Lazada",
            "Chuyên viên Tiếp thị Liên kết & Online Marketing",
            "Chuyên viên Phát triển Hệ thống E-business"
        ]
    },
    {
        "code": "7340201",
        "name": "Tài chính ngân hàng",
        "slug": "nganh-tai-chinh-ngan-hang",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 250,
        "cutoffs": {"2024_thpt": "21.50", "2024_hocba": "23.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Tài chính - Kế toán",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Đào tạo quản trị tín dụng, đầu tư tài chính, phân tích chứng khoán, quản trị rủi ro ngân hàng, tài chính doanh nghiệp và giao dịch ngoại hối.",
        "careers": [
            "Chuyên viên Quan hệ Khách hàng Ngân hàng (RM)",
            "Chuyên viên Phân tích Đầu tư Chứng khoán",
            "Chuyên viên Thẩm định Tín dụng & Quản trị Rủi ro",
            "Chuyên viên Tài chính Doanh nghiệp (Corporate Finance)"
        ]
    },
    {
        "code": "7340205",
        "name": "Công nghệ Tài Chính (Fintech)",
        "slug": "nganh-cong-nghe-tai-chinh-fintech",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "21.00", "2024_hocba": "23.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Tài chính - Kế toán",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Kết hợp công nghệ dữ liệu, Blockchain, AI, Ví điện tử, Cổng thanh toán, Ngân hàng số và Phân tích rủi ro tài chính thuật toán.",
        "careers": [
            "Chuyên viên Phát triển Sản phẩm Fintech (Product Owner)",
            "Chuyên viên Phân tích Dữ liệu Tài chính (Financial Data Analyst)",
            "Chuyên viên Vận hành Hệ thống Thanh toán Số & Ví Điện tử",
            "Chuyên viên Quản trị Rủi ro Công nghệ Ngân hàng Số"
        ]
    },
    {
        "code": "7340301",
        "name": "Kế toán",
        "slug": "nganh-ke-toan",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 300,
        "cutoffs": {"2024_thpt": "21.25", "2024_hocba": "23.25", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Tài chính - Kế toán",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Thực hành kế toán tài chính, kế toán quản trị, lập báo cáo thuế, kế toán máy (MISA, SAP), kiểm toán nội bộ và phân tích sức khỏe tài chính doanh nghiệp.",
        "careers": [
            "Kế toán viên Tổng hợp / Kế toán Thuế",
            "Chuyên viên Phân tích Tài chính Doanh nghiệp",
            "Kế toán Trưởng tại các Công ty và Tập đoàn",
            "Trợ lý Kiểm toán viên"
        ]
    },
    {
        "code": "7380107",
        "name": "Luật kinh tế",
        "slug": "nganh-luat-kinh-te",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "C00 (Văn, Sử, Địa)"],
        "quota": 200,
        "cutoffs": {"2024_thpt": "22.25", "2024_hocba": "24.25", "2025_diemsan": "16.00", "2025_dgnl": "720"},
        "faculty": "Khoa Luật",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Đào tạo pháp luật doanh nghiệp, tư vấn hợp đồng thương mại, giải quyết tranh chấp kinh doanh, luật đầu tư quốc tế, sở hữu trí tuệ và lao động.",
        "careers": [
            "Chuyên viên Pháp chế Doanh nghiệp (Legal Officer)",
            "Chuyên viên Tư vấn Hợp đồng và M&A tại Công ty Luật",
            "Luật sư Kinh doanh Commercial Lawyer",
            "Chuyên viên Giải quyết Tranh chấp Thương mại & Trọng tài"
        ]
    },
    {
        "code": "7380101",
        "name": "Luật",
        "slug": "nganh-luat",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "C00 (Văn, Sử, Địa)"],
        "quota": 150,
        "cutoffs": {"2024_thpt": "21.50", "2024_hocba": "23.50", "2025_diemsan": "16.00", "2025_dgnl": "720"},
        "faculty": "Khoa Luật",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Kiến thức toàn diện về Luật Hình sự, Dân sự, Hành chính, Tố tụng, Tư pháp quốc tế và kỹ năng tranh tụng trước tòa án.",
        "careers": [
            "Chuyên viên Tư vấn Pháp lý",
            "Trợ lý Luật sư / Công chứng viên / Đấu giá viên",
            "Cán bộ Pháp luật tại các Cơ quan Nhà nước, Tòa án, Viện Kiểm sát"
        ]
    },
    {
        "code": "7220201",
        "name": "Ngôn ngữ Anh",
        "slug": "nganh-ngon-ngu-anh-dh",
        "combinations": ["A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D14 (Văn, Sử, Anh)", "D15 (Văn, Địa, Anh)"],
        "quota": 250,
        "cutoffs": {"2024_thpt": "21.50", "2024_hocba": "23.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Ngoại ngữ",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Thành thạo Tiếng Anh Thương mại, Biên - Phiên dịch Anh - Việt chuyên sâu, Giao tiếp Liên văn hóa, Giảng dạy Tiếng Anh (TESOL/CELTA).",
        "careers": [
            "Biên - Phiên dịch viên Tiếng Anh Thương mại",
            "Chuyên viên Quan hệ Quốc tế & Đối ngoại",
            "Giảng viên / Giáo viên Tiếng Anh tại các trung tâm & trường học",
            "Chuyên viên Truyền thông & Du lịch Quốc tế"
        ]
    },
    {
        "code": "7220204",
        "name": "Ngôn ngữ Trung Quốc",
        "slug": "nganh-ngon-ngu-trung-quoc",
        "combinations": ["D01 (Toán, Văn, Anh)", "D04 (Toán, Văn, Trung)", "D15 (Văn, Địa, Anh)", "D84 (Toán, Giáo dục công dân, Anh)"],
        "quota": 250,
        "cutoffs": {"2024_thpt": "22.50", "2024_hocba": "24.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Ngoại ngữ (Ngành tuyển sinh rất HOT tại HUIT)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Đào tạo Tiếng Trung Thương mại, Biên - Phiên dịch Hán - Việt, Văn hóa & Kinh tế Trung Quốc, Kỹ năng làm việc tại doanh nghiệp FDI Trung Quốc, Đài Loan.",
        "careers": [
            "Biên - Phiên dịch viên Tiếng Trung Quốc",
            "Chuyên viên Xuất Nhập Khẩu với Thị trường Trung Quốc / Đài Loan",
            "Trợ lý Giám đốc Doanh nghiệp FDI Trung Quốc / Đài Loan",
            "Hướng dẫn viên Du lịch & Chuyên viên Đối ngoại"
        ]
    },
    {
        "code": "7810201",
        "name": "Quản trị khách sạn",
        "slug": "nganh-quan-tri-khach-san",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 200,
        "cutoffs": {"2024_thpt": "20.50", "2024_hocba": "22.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Dịch vụ du lịch & Ẩm thực",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Quản trị vận hành Lễ tân, Buồng phòng, Ẩm thực (F&B), Quản trị Sự kiện & Hội nghị (MICE), Quản trị doanh thu Khách sạn 4-5 sao.",
        "careers": [
            "Quản lý / Giám sát Bộ phận Khách sạn 4-5 sao (Front Office / F&B)",
            "Chuyên viên Tổ chức Sự kiện & Hội nghị",
            "Chuyên viên Quản trị Doanh thu Khách sạn",
            "Quản lý Chuỗi Resort & Homestay Nâng cao"
        ]
    },
    {
        "code": "7810202",
        "name": "Quản trị Nhà hàng và Dịch vụ ăn uống",
        "slug": "nganh-quan-tri-nha-hang-va-dich-vu-an-uong",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 200,
        "cutoffs": {"2024_thpt": "20.00", "2024_hocba": "22.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Dịch vụ du lịch & Ẩm thực",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Quản lý chuỗi nhà hàng ẩm thực, dịch vụ tiệc cưới, Bar/Pha chế chuyên nghiệp, vệ sinh an toàn thực phẩm trong nhà hàng và quản trị chi phí F&B.",
        "careers": [
            "Quản lý Chuỗi Nhà hàng / Quản lý F&B Khách sạn",
            "Chuyên viên Điều hành Dịch vụ Tiệc & Catering",
            "Chuyên gia Pha chế Bar/Café & Sáng tạo Đồ uống",
            "Chủ Doanh nghiệp Kinh doanh Ẩm thực F&B"
        ]
    },
    {
        "code": "7810101",
        "name": "Quản trị dịch vụ du lịch và lữ hành",
        "slug": "nganh-quan-tri-dich-vu-du-lich-va-lu-hanh",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 150,
        "cutoffs": {"2024_thpt": "20.50", "2024_hocba": "22.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Dịch vụ du lịch & Ẩm thực",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Thiết kế tour du lịch trong và ngoài nước (Inbound/Outbound), hướng dẫn du lịch quốc tế, điều hành doanh nghiệp lữ hành, đại lý vé máy bay.",
        "careers": [
            "Điều hành Tour Du lịch Quốc tế và Nội địa",
            "Hướng dẫn viên Du lịch Quốc tế",
            "Chuyên viên Thiết kế & Bán Sản phẩm Du lịch (Sales Tour)",
            "Quản lý Công ty Lữ hành & Truyền thông Du lịch"
        ]
    },
    {
        "code": "7810103",
        "name": "Du lịch",
        "slug": "nganh-du-lich",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "19.50", "2024_hocba": "21.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Dịch vụ du lịch & Ẩm thực",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Đào tạo kiến thức địa lý du lịch, văn hóa ẩm thực vùng miền, tư vấn trải nghiệm điểm đến, du lịch sinh thái và phát triển du lịch bền vững.",
        "careers": [
            "Chuyên viên Phát triển Sản phẩm Du lịch Sinh thái",
            "Chuyên viên Quảng bá & Truyền thông Điểm đến Du lịch",
            "Quản lý Dự án Du lịch Cộng đồng & Bền vững"
        ]
    },
    {
        "code": "7510303",
        "name": "Công nghệ kỹ thuật điều khiển và tự động hóa",
        "slug": "nganh-cong-nghe-ky-thuat-dieu-khien-va-tu-dong-hoa",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 150,
        "cutoffs": {"2024_thpt": "21.00", "2024_hocba": "23.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Điện - Điện tử",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Lập trình PLC, Robot công nghiệp, Hệ thống SCADA, IoT Công nghiệp (IIoT), biến tần, dây chuyền sản xuất tự động trong nhà máy hiện đại.",
        "careers": [
            "Kỹ sư Lập trình Tự động hóa & PLC",
            "Kỹ sư Vận hành và Bảo trì Robot Công nghiệp",
            "Kỹ sư Thiết kế Hệ thống SCADA / DCS trong nhà máy",
            "Chuyên viên Tư vấn Giải pháp Tự động hóa Doanh nghiệp"
        ]
    },
    {
        "code": "7510301",
        "name": "Công nghệ kỹ thuật điện – điện tử",
        "slug": "nganh-cong-nghe-ky-thuat-dien-%E2%80%93-dien-tu",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 200,
        "cutoffs": {"2024_thpt": "20.50", "2024_hocba": "22.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Điện - Điện tử",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Thiết kế mạch điện tử, vi điều khiển, hệ thống nhúng, kỹ thuật năng lượng tái tạo (Điện mặt trời, Điện gió), quản trị mạng điện tòa nhà.",
        "careers": [
            "Kỹ sư Thiết kế Mạch Điện tử & Hệ thống Nhúng",
            "Kỹ sư Điện Tòa nhà & Công nghiệp (M&E Engineer)",
            "Kỹ sư Năng lượng Mới & Điện Mặt trời",
            "Kỹ sư Kiểm định & Bảo trì Thiết bị Điện tử"
        ]
    },
    {
        "code": "7520115",
        "name": "Kỹ thuật Nhiệt",
        "slug": "nganh-ky-thuat-nhiet",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "17.00", "2024_hocba": "19.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Cơ khí (Được hưởng Học bổng 50% HP HK1)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Chuyên về thiết kế hệ thống điều hòa không khí trung tâm (HVAC), lò hơi công nghiệp, hệ thống làm lạnh thủy hải sản, tiết kiệm năng lượng nhiệt.",
        "careers": [
            "Kỹ sư Thiết kế & Thi công Hệ thống Điều hòa HVAC",
            "Kỹ sư Năng lượng Nhiệt & Lò hơi Nhà máy",
            "Kỹ sư Vận hành Hệ thống Lạnh Công nghiệp & Kho Lạnh",
            "Chuyên viên Tư vấn Tiết kiệm Năng lượng Công nghiệp"
        ]
    },
    {
        "code": "7510203",
        "name": "Công nghệ kỹ thuật cơ điện tử",
        "slug": "nganh-cong-nghe-ky-thuat-co-dien-tu",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 150,
        "cutoffs": {"2024_thpt": "20.75", "2024_hocba": "22.75", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Cơ khí",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Giao thoa giữa Cơ khí chính xác, Điện tử điều khiển và Tin học lập trình. Đào tạo thiết kế máy thông minh, xe tự hành AGV, thiết bị y tế cơ điện tử.",
        "careers": [
            "Kỹ sư Thiết kế Sản phẩm Cơ điện tử & Robot",
            "Kỹ sư Vận hành Dây chuyền Máy Sản xuất Thông minh",
            "Kỹ sư Lập trình Thiết bị Nhúng & Vi điều khiển",
            "Quản lý Kỹ thuật Nhà máy Chế tạo"
        ]
    },
    {
        "code": "7510202",
        "name": "Công nghệ chế tạo máy",
        "slug": "nganh-cong-nghe-che-tao-may",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 150,
        "cutoffs": {"2024_thpt": "20.00", "2024_hocba": "22.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Cơ khí",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Lập trình máy gia công CNC (CAD/CAM/CNC), thiết kế khuôn mẫu chính xác, công nghệ in 3D cơ khí, vật liệu cơ khí chế tạo.",
        "careers": [
            "Kỹ sư Lập trình & Vận hành Máy Gia công CNC",
            "Kỹ sư Thiết kế Cơ khí & Khuôn mẫu (CAD/CAM)",
            "Chuyên viên Quản lý Bảo trì Thiết bị Cơ khí",
            "Chuyên viên Giám định Chất lượng Cơ khí (QA/QC)"
        ]
    },
    {
        "code": "7540204",
        "name": "Công nghệ dệt, may",
        "slug": "nganh-cong-nghe-det-may",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 150,
        "cutoffs": {"2024_thpt": "18.00", "2024_hocba": "20.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa May - Thời trang (Học bổng 50% HP HK1)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Quản lý dây chuyền sản xuất may công nghiệp, thiết kế rập 2D/3D (Gerber, Lectra), kiểm soát chất lượng trang phục xuất khẩu, vật liệu may mặc.",
        "careers": [
            "Kỹ sư Quản lý Dây chuyền Sản xuất May xuất khẩu",
            "Chuyên viên Thiết kế Rập & Nhảy Size Tự động",
            "Chuyên viên Quản lý Chất lượng Garment QA/QC",
            "Chuyên viên Quản lý Đơn hàng Thời trang (Merchandiser)"
        ]
    },
    {
        "code": "7340123",
        "name": "Kinh doanh thời trang và dệt may",
        "slug": "nganh-kinh-doanh-thoi-trang-va-det-may",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "19.00", "2024_hocba": "21.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa May - Thời trang (Học bổng 50% HP HK1)",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Kinh doanh chuỗi thời trang, Marketing thời trang, quản lý chuỗi cung ứng dệt may toàn cầu, phân tích xu hướng mốt (Fashion Trend Forecasting).",
        "careers": [
            "Chuyên viên Quản lý Chuỗi Cung ứng Thời trang",
            "Chuyên viên Phát triển Thương hiệu Thời trang",
            "Visual Merchandiser & Fashion Buyer",
            "Chủ Doanh nghiệp Kinh doanh Thương hiệu Thời trang"
        ]
    },
    {
        "code": "7510401",
        "name": "Công nghệ kỹ thuật Hóa học",
        "slug": "nganh-cong-nghe-ky-thuat-hoa-hoc",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 150,
        "cutoffs": {"2024_thpt": "19.50", "2024_hocba": "21.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ Hóa học",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Công nghệ hóa mỹ phẩm, hóa dược, chế biến hợp chất tự nhiên, công nghệ vật liệu màng, quy trình tổng hợp hóa học công nghiệp.",
        "careers": [
            "Kỹ sư Nghiên cứu Công thức Hóa Mỹ phẩm (R&D Cosmetics)",
            "Kỹ sư Vận hành Nhà máy Sản xuất Hóa chất & Dược phẩm",
            "Chuyên viên Kiểm nghiệm Hóa phân tích",
            "Chuyên viên Quản lý An toàn Hóa chất & Môi trường"
        ]
    },
    {
        "code": "7420201",
        "name": "Công nghệ sinh học",
        "slug": "nganh-cong-nghe-sinh-hoc",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 150,
        "cutoffs": {"2024_thpt": "19.00", "2024_hocba": "21.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Sinh học & Môi trường",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Công nghệ gen, nuôi cấy mô thực vật, vi sinh ứng dụng trong thực phẩm và y dược, chế phẩm sinh học bảo vệ môi trường và nông nghiệp công nghệ cao.",
        "careers": [
            "Kỹ sư Công nghệ Sinh học Thực phẩm & Dược phẩm",
            "Chuyên viên Nuôi cấy Mô & Nông nghiệp Công nghệ cao",
            "Nghiên cứu viên tại Phòng Thí nghiệm Sinh học / Y học",
            "Chuyên viên Sản xuất Chế phẩm Vi sinh"
        ]
    },
    {
        "code": "7510406",
        "name": "Công nghệ kỹ thuật môi trường",
        "slug": "nganh-cong-nghe-ky-thuat-moi-truong",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "17.00", "2024_hocba": "19.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Biến đổi khí hậu & TNMT (Học bổng 50% HP HK1)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Thiết kế hệ thống xử lý nước thải, khí thải, rác thải công nghiệp, công nghệ tuần hoàn tài nguyên và quản lý môi trường đô thị.",
        "careers": [
            "Kỹ sư Thiết kế & Thi công Trạm Xử lý Nước thải / Khí thải",
            "Chuyên viên Quản lý Môi trường Doanh nghiệp (EHS Specialist)",
            "Chuyên viên Phân tích & Trắc địa Môi trường",
            "Tư vấn Báo cáo Đánh giá Tác động Môi trường (ĐTM)"
        ]
    },
    {
        "code": "7850101",
        "name": "Quản lý tài nguyên và môi trường",
        "slug": "nganh-quan-ly-tai-nguyen-va-moi-truong",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "17.00", "2024_hocba": "19.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Biến đổi khí hậu & TNMT (Học bổng 50% HP HK1)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Quản lý tài nguyên đất, nước, khoáng sản, ứng dụng GIS & Viễn thám, phát triển kinh tế xanh, giảm thiểu biến đổi khí hậu và chứng chỉ carbon.",
        "careers": [
            "Chuyên viên Quản lý Tài nguyên Đất & Nước tại Sở TNMT",
            "Kỹ sư Ứng dụng Bản đồ Hệ thống Thông tin Địa lý (GIS Specialist)",
            "Chuyên viên Tư vấn Biến đổi Khí hậu & Chứng chỉ Carbon (ESG)",
            "Chuyên viên Quản lý Dự án Phát triển Bền vững"
        ]
    },
    {
        "code": "7510402",
        "name": "Công nghệ vật liệu",
        "slug": "nganh-cong-nghe-vat-lieu",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D07 (Toán, Hóa, Anh)", "B00 (Toán, Hóa, Sinh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "17.00", "2024_hocba": "19.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Công nghệ Hóa học (Học bổng 50% HP HK1)",
        "duration": "3.5 - 4 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ (Học bổng 50% học kỳ 1)",
        "description": "Vật liệu Polymer, Composite cao cấp, Vật liệu Nano, Vật liệu thông minh trong điện tử và vật liệu sinh học tự phân hủy.",
        "careers": [
            "Kỹ sư Chế tạo Vật liệu Mới & Polymer Composite",
            "Chuyên viên Kiểm định Chất lượng Vật liệu",
            "Kỹ sư R&D tại Tập đoàn Chế tạo & Sản xuất Điện tử",
            "Chuyên viên Quản lý Vật liệu Sinh học Bảo vệ Môi trường"
        ]
    },
    {
        "code": "7510601",
        "name": "Quản lý Công nghiệp",
        "slug": "nganh-quan-ly-cong-nghiep",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D07 (Toán, Hóa, Anh)"],
        "quota": 120,
        "cutoffs": {"2024_thpt": "20.50", "2024_hocba": "22.50", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Quản lý công nghiệp & Logistics",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Quản trị chuỗi sản xuất công nghiệp, cải tiến năng suất (Lean Six Sigma), quản lý dự án công nghiệp, định mức chi phí sản xuất và quản trị chất lượng.",
        "careers": [
            "Chuyên viên Quản lý Sản xuất & Điều độ Nhà máy",
            "Chuyên viên Cải tiến Năng suất Lean / Six Sigma",
            "Chuyên viên Quản lý Dự án Công nghiệp",
            "Chuyên viên Phân tích Hoạt động Vận hành (Operations Analyst)"
        ]
    },
    {
        "code": "7340129",
        "name": "Quản trị kinh doanh Thực phẩm",
        "slug": "nganh-quan-tri-kinh-doanh-thuc-pham",
        "combinations": ["A00 (Toán, Lý, Hóa)", "A01 (Toán, Lý, Anh)", "D01 (Toán, Văn, Anh)", "D10 (Toán, Địa, Anh)"],
        "quota": 100,
        "cutoffs": {"2024_thpt": "21.00", "2024_hocba": "23.00", "2025_diemsan": "16.00", "2025_dgnl": "600"},
        "faculty": "Khoa Quản trị kinh doanh",
        "duration": "3.5 năm (150 tín chỉ)",
        "tuition": "14 - 16 triệu đồng/học kỳ",
        "description": "Kinh doanh độc quyền chuỗi nông sản thực phẩm, phân phối FMCG thực phẩm, thương mại hóa nghiên cứu thực phẩm và quản trị chuỗi lạnh (Cold Chain).",
        "careers": [
            "Quản lý Kinh doanh Ngành hàng Thực phẩm (FMCG Manager)",
            "Chuyên viên Phát triển Thị trường Nông sản & Thực phẩm",
            "Chuyên viên Quản lý Chuỗi Cung ứng Thực phẩm",
            "Chủ Doanh nghiệp Khởi nghiệp Ngành Thực phẩm"
        ]
    }
]

# Tin tuyển sinh & Thông báo chính thức 2025 - 2026
NOTICES_DATA = [
    {
        "url": "https://ts.huit.edu.vn/tin-tuyen-sinh/diem-san-xet-tuyen-dai-hoc-nam-2025-truong-dai-hoc-cong-thuong-tp-hcm",
        "title": "Thông báo Điểm sàn Xét tuyển Đại học chính quy năm 2025 Trường Đại học Công Thương TP.HCM (HUIT)",
        "markdown": """# Thông báo Điểm sàn Xét tuyển Đại học chính quy năm 2025 Trường Đại học Công Thương TP.HCM (Mã trường: DCT)

Trường Đại học Công Thương TP.HCM (HUIT) chính thức công bố ngưỡng đảm bảo chất lượng đầu vào (Điểm sàn xét tuyển) năm 2025 cho 37 ngành đào tạo đại học chính quy:

## 1. Phương thức Xét tuyển theo kết quả kỳ thi Tốt nghiệp THPT 2025 (Phương thức 1)
- **Mức điểm sàn áp dụng**: **16.00 điểm** áp dụng đồng nhất cho **tất cả 37 ngành đào tạo đại học**.
- **Cơ chế tính điểm**: Điểm xét tuyển = Tổng điểm 3 môn tổ hợp xét tuyển + Điểm ưu tiên khu vực/đối tượng theo quy chế Bộ GD&ĐT.

## 2. Phương thức Xét tuyển Kỳ thi Đánh giá Năng lực ĐHQG-HCM 2025 (Phương thức 3)
- **Điểm sàn áp dụng chung**: **600 điểm** (trên thang điểm 1.200).
- **Riêng Nhóm ngành Luật (Luật, Luật Kinh tế)**: Ngưỡng điểm sàn tối thiểu bằng **720 điểm**, đồng thời điểm thành phần Tiếng Việt >= 180 điểm và điểm Toán >= 180 điểm.

## 3. Phương thức Xét tuyển Học bạ THPT (Phương thức 2)
- Điều kiện xét tuyển: Tổng điểm trung bình 3 môn trong tổ hợp xét tuyển (lớp 10, 11 và HK1 lớp 12 hoặc cả năm lớp 12) đạt từ **18.00 - 20.00 điểm** trở lên.

## 4. Danh sách các Tổ hợp môn xét tuyển mở rộng 2025
Năm 2025, HUIT mở rộng tổ hợp môn khối C (C00, C01, C02, C03, C14) và tổ hợp X26 (Toán, Anh, Tin) tạo điều kiện tối đa cho thí sinh.
"""
    },
    {
        "url": "https://ts.huit.edu.vn/thong-bao/chinh-sach-hoc-phi-va-hoc-bong-tuyen-sinh-huit-nam-2025-2026",
        "title": "Chính sách Học phí & Học bổng Tuyển sinh Trường Đại học Công Thương TP.HCM (HUIT)",
        "markdown": """# Chính sách Học phí & Học bổng Tuyển sinh Trường Đại học Công Thương TP.HCM (HUIT)

## I. Mức Học phí Chính thức
- **Học phí trung bình**: **14.000.000đ – 16.000.000đ / học kỳ** (mỗi năm học gồm 2 học kỳ chính).
- **Đơn giá tín chỉ**: Từ **540.000đ – 700.000đ / tín chỉ** (tùy thuộc môn lý thuyết hay môn thực hành/thí nghiệm).
- **Cam kết của Nhà trường**: **GIỮ ỔN ĐỊNH HỌC PHÍ KHÔNG TĂNG TRONG TOÀN BỘ KHÓA HỌC (3.5 - 4 NĂM)** đối với toàn bộ khóa tân sinh viên trúng tuyển.

## II. Chính sách Học bổng Ưu đãi Đặc biệt
1. **Học bổng GIẢM 50% HỌC PHÍ HỌC KỲ I** áp dụng cho 9 ngành trọng điểm:
   - Kỹ thuật Nhiệt
   - Công nghệ Vật liệu
   - Khoa học Chế biến Món ăn
   - Công nghệ Dệt, May
   - Kinh doanh Thời trang và Dệt may
   - Quản lý Tài nguyên và Môi trường
   - Công nghệ Kỹ thuật Môi trường
   - Công nghệ Chế biến Thủy sản
   - Khoa học Dinh dưỡng và Ẩm thực
2. **Học bổng Thủ khoa, Á khoa Trường và Ngành**: Khen thưởng tiền mặt và miễn học phí toàn khóa.
3. **Học bổng Vượt khó & Hỗ trợ tài chính**: Tiếp sức đến trường, hỗ trợ vay vốn ngân hàng chính sách 0% lãi suất.
4. **Giảm học phí người thân**: Giảm 10 - 20% học phí cho anh/chị/em ruột cùng học tại HUIT.
5. **Đặc quyền Tân sinh viên**: Khám sức khỏe miễn phí, tham gia các khóa kỹ năng mềm chuẩn quốc tế miễn phí.
"""
    },
    {
        "url": "https://ts.huit.edu.vn/vien-quoc-te-huit/chinh-sach-hoc-phi-hoc-bong-2026",
        "title": "Chính sách Học bổng & Đào tạo Viện Quốc tế HUIT (Trường Đại học Công Thương TP.HCM)",
        "markdown": """# Chính sách Học bổng & Đào tạo Viện Quốc tế HUIT (Trường Đại học Công Thương TP.HCM)

Viện Đào tạo Quốc tế (Viện Quốc tế HUIT) là đơn vị trực thuộc Trường Đại học Công Thương TP.HCM, chuyên trách các chương trình cử nhân liên kết quốc tế, trao đổi sinh viên và đào tạo chất lượng cao.

## I. Chính sách Học bổng Viện Quốc tế HUIT năm 2026
1. **Học bổng 100% Học phí (Suất đặc biệt)**:
   - Áp dụng cho thí sinh có chứng chỉ **IELTS từ 6.5 trở lên** (hoặc TOEFL iBT từ 79, TOEIC 750+) hoặc đạt **từ 850 điểm Đánh giá năng lực ĐHQG-HCM**.
   - Miễn toàn bộ 100% học phí năm học đầu tiên khi nhập học các chương trình thuộc Viện Quốc tế HUIT.
2. **Học bổng 50% Học phí năm 1**:
   - Áp dụng cho thí sinh đạt chứng chỉ **IELTS từ 5.5 đến 6.0** (hoặc TOEFL iBT 65+) hoặc đạt điểm xét tuyển học bạ THPT từ **24.0 điểm trở lên** (3 môn tổ hợp).
3. **Học bổng 30% Học kỳ I (Hỗ trợ Tân sinh viên nhập học sớm)**:
   - Tặng 30% học phí học kỳ đầu tiên cho tân sinh viên hoàn tất thủ tục nhập học đợt 1 tại Viện Quốc tế HUIT.

## II. Các Ngành & Chương trình Đào tạo tại Viện Quốc tế HUIT
- **Chương trình Cử nhân Quản trị Kinh doanh Quốc tế**: Liên kết với các trường đối tác uy tín tại Đài Loan, Hàn Quốc, Malaysia.
- **Chương trình Cử nhân Công nghệ Thông tin Quốc tế**: Đào tạo chuẩn phần mềm và AI quốc tế.
- **Chương trình Cử nhân Ngôn ngữ Anh & Thương mại Quốc tế**: Biên phiên dịch, giao thương quốc tế.
- **Chương trình Cử nhân Quản trị Khách sạn & Du lịch Quốc tế**.

## III. Phương thức Xét tuyển Viện Quốc tế HUIT
- **Phương thức 1**: Xét theo kết quả Học bạ THPT (Tổng điểm 3 môn từ 20.0 điểm trở lên).
- **Phương thức 2**: Xét theo Điểm thi tốt nghiệp THPT năm 2026 (từ 16.0 điểm trở lên).
- **Yêu cầu ngoại ngữ**: Thí sinh chưa có chứng chỉ IELTS/TOEFL được kiểm tra trình độ tiếng Anh đầu vào và tham gia khóa học Tiếng Anh Dự bị của Viện trước khi học chuyên ngành.
- **Liên hệ Viện Quốc tế HUIT**: Hotline (028) 3816 1166 - Email: international@huit.edu.vn - Website: ts.huit.edu.vn.
"""
    }
]


def build_full_dataset():
    print("=========================================================")
    print("   BUILDING FULL HUIT 39 MAJORS & REAL-TIME ADMISSIONS KB")
    print("=========================================================")

    scraped_docs = []

    # 1. Add all 39 majors
    for m in MAJORS_DATA:
        url = f"https://ts.huit.edu.vn/nganh-dh/{m['slug']}"
        title = f"Ngành {m['name']} (Mã ngành: {m['code']}) - Trường Đại học Công Thương TP.HCM - Tuyển Sinh HUIT"
        
        md_lines = [
            f"# Ngành {m['name']} (Mã ngành: {m['code']})",
            "",
            f"**MÃ NGÀNH:** `{m['code']}` | **KHOA QUẢN LÝ:** {m['faculty']}",
            f"**THỜI GIAN ĐÀO TẠO:** {m['duration']} | **HỌC PHÍ:** {m['tuition']}",
            "",
            "## 1. TỔ HỢP MÔN XÉT TUYỂN",
            "\n".join([f"- {c}" for c in m['combinations']]),
            "",
            "## 2. MỚI NHẤT: ĐIỂM SÀN & ĐIỂM CHUẨN THAM KHẢO",
            f"- **Điểm sàn xét tuyển THPT 2025 (Chính thức)**: `{m['cutoffs']['2025_diemsan']} điểm`",
            f"- **Điểm sàn Đánh giá năng lực ĐHQG-HCM 2025**: `{m['cutoffs']['2025_dgnl']} điểm`",
            f"- Trạng thái tuyển sinh: Ngành MỚI MỞ của HUIT (Chưa có điểm trúng tuyển năm 2024)" if m.get("is_new") else f"- Điểm trúng tuyển THPT năm 2024: `{m['cutoffs'].get('2024_thpt', 'N/A')} điểm`\n- Điểm trúng tuyển Học bạ năm 2024: `{m['cutoffs'].get('2024_hocba', 'N/A')} điểm`",
            "",
            "## 3. MÔ TẢ NGÀNH & MỤC TIÊU ĐÀO TẠO",
            m['description'],
            "",
            "## 4. CƠ HỘI NGHỀ NGHIỆP VÀ VỊ TRÍ LÀM VIỆC SAU TỐT NGHIỆP",
            "\n".join([f"- {c}" for c in m['careers']]),
            "",
            "## 5. PHƯƠNG THỨC XÉT TUYỂN VÀ HỌC BỔNG",
            "- **Phương thức 1**: Xét theo kết quả kỳ thi tốt nghiệp THPT 2025 - 2026.",
            "- **Phương thức 2**: Xét theo học bạ THPT (Trung bình cộng 3 môn tổ hợp lớp 10, 11 và HK1 lớp 12 hoặc cả năm lớp 12 >= 18.0 - 20.0 điểm).",
            "- **Phương thức 3**: Xét theo điểm thi Đánh giá Năng lực do ĐHQG-HCM tổ chức.",
            "- **Phương thức 4**: Xét tuyển thẳng theo quy chế của Bộ GD&ĐT.",
            "- **Phương thức 5**: Xét điểm ĐGNL chuyên biệt Trường ĐH Sư phạm TP.HCM kết hợp học bạ.",
            "- **Chính sách học bổng**: HUIT dành hàng tỷ đồng học bổng khuyến khích học tập, học bổng 50% học kỳ 1 cho các ngành ưu tiên, hỗ trợ tân sinh viên vay vốn và khám sức khỏe miễn phí."
        ]

        scraped_docs.append({
            "url": url,
            "title": title,
            "markdown": "\n".join(md_lines)
        })
        print(f"[+] Added Major: Ngành {m['name']} ({m['code']})")

    # 2. Add admission notices
    for n in NOTICES_DATA:
        scraped_docs.append({
            "url": n["url"],
            "title": n["title"],
            "markdown": n["markdown"]
        })
        print(f"[+] Added Admission Notice: {n['title'][:60]}...")

    # 3. Save to scraped_pages.json
    with open(SCRAPED_JSON, "w", encoding="utf-8") as f:
        json.dump(scraped_docs, f, ensure_ascii=False, indent=2)

    # 4. Save to urls_to_scrape.json
    urls = [d["url"] for d in scraped_docs]
    with open(URLS_JSON, "w", encoding="utf-8") as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Generated dataset with {len(scraped_docs)} rich documents saved to {SCRAPED_JSON}")
    return len(scraped_docs)


if __name__ == "__main__":
    build_full_dataset()
