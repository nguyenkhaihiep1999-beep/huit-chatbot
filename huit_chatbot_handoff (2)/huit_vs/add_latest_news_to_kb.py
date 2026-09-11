#!/usr/bin/env python3
"""Script bổ sung các tin tức, thông báo mới nhất trong 1 tháng vừa qua (tháng 8 - 9/2026)
vào MongoDB Atlas huit_kb, dùng embedder intfloat/multilingual-e5-large (1024D).
"""
import os
import sys
import hashlib
from urllib.parse import quote_plus
from pymongo import MongoClient
from dotenv import load_dotenv
from fastembed import TextEmbedding

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    raise RuntimeError("Chưa cấu hình MONGODB_PASSWORD trong .env")

uri = f"mongodb+srv://nguyenkhaihiep1999_db_user:{quote_plus(pwd)}@cluster0.hyj8rab.mongodb.net/?appName=Cluster0"
client = MongoClient(uri)
kb = client["huit_chatbot"]["huit_kb"]

print("Initializing FastEmbed multilingual-e5-large...")
embedder = TextEmbedding("intfloat/multilingual-e5-large")

LATEST_ARTICLES = [
    {
        "title": "Thông báo nhập học đối với Tân sinh viên khóa 2026 - HUIT (Cổng thông tin tuyển sinh)",
        "source_url": "https://ts.huit.edu.vn/thong-bao/thong-bao-nhap-hoc-doi-voi-tan-sinh-vien-khoa-2026",
        "category": "admission_procedure",
        "year": 2026,
        "date": "07/08/2026",
        "chunks": [
            """[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Thông báo nhập học Tân sinh viên Khóa 2026]
Thời gian làm thủ tục nhập học chính thức: Từ ngày 12/08/2026 đến hết 17h00 ngày 21/08/2026 (Nhà trường làm việc tất cả các ngày trong tuần, kể cả Thứ Bảy và Chủ Nhật).
Địa điểm hỗ trợ nhập học trực tiếp: Trường Đại học Công Thương TP.HCM, số 140 Lê Trọng Tấn, Phường Tây Thạnh, Quận Tân Phú, TP. Hồ Chí Minh.
Hotline hỗ trợ tân sinh viên: 028 3816 1673 (số nội bộ 124) hoặc 028 6270 6275 hoặc 096 205 1080.
Dự kiến lịch sinh hoạt đầu khóa của Tân sinh viên Khóa 2026 bắt đầu từ ngày 24/08/2026. Sinh viên sẽ được cấp tài khoản cá nhân để theo dõi thời khóa biểu và lịch học chi tiết.""",
            """[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Quy trình 2 bước nhập học Tân sinh viên Khóa 2026]
Quy trình nhập học gồm 2 bước bắt buộc:
- Bước 1: Xác nhận nhập học trực tuyến trên Cổng thông tin tuyển sinh của Bộ Giáo dục và Đào tạo (https://thisinh.thitotnghiepthpt.edu.vn/) trước 17h00 ngày 21/08/2026. Đây là điều kiện tiên quyết để được công nhận trúng tuyển chính thức.
- Bước 2: Làm thủ tục và nộp học phí, lệ phí nhập học trực tuyến qua Cổng nhập học của HUIT tại địa chỉ: https://nhaphoc.huit.edu.vn.
Thông tin đăng nhập: Thí sinh sử dụng Mã hồ sơ hoặc Mã sinh viên kết hợp với số CCCD hoặc Số điện thoại (thông tin này đã được Nhà trường gửi qua tin nhắn SMS và Email cho thí sinh trúng tuyển). Sau khi hoàn tất nộp học phí và hồ sơ trực tuyến, thí sinh nhận giấy báo và lịch sinh hoạt đầu khóa."""
        ]
    },
    {
        "title": "HUIT tiếp tục nhận hồ sơ xét tuyển 100 chỉ tiêu đợt bổ sung năm 2026 (LKQT và Công nghệ chế biến thủy sản)",
        "source_url": "https://ts.huit.edu.vn/thong-bao/huit-tiep-tuc-nhan-ho-so-xet-tuyen-80-chi-tieu-o-cac-chuong-trinh-lien-ket-quoc-te-va-nganh-cong-nghe-che-bien-thuy-san",
        "category": "admission",
        "year": 2026,
        "date": "10/08/2026",
        "chunks": [
            """[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Xét tuyển bổ sung 100 chỉ tiêu năm 2026]
Trường Đại học Công Thương TP.HCM tiếp tục nhận hồ sơ xét tuyển bổ sung 100 chỉ tiêu năm 2026, gồm:
1. Các chương trình liên kết quốc tế (80 chỉ tiêu):
- Ngôn ngữ Trung Quốc (LKQT với ĐH Lỗ Đông, Trung Quốc - Mã: LK7220204)
- Quản trị kinh doanh (LKQT với ĐH Shinawatra, Thái Lan - Mã: LK7340101)
- Kinh doanh quốc tế (LKQT với ĐH Văn hóa Trung Quốc, Đài Loan - Mã: CU7340120)
2. Ngành Công nghệ chế biến thủy sản (Mã ngành: 7540105): Nhận 20 chỉ tiêu bổ sung.
Đặc biệt: Thí sinh trúng tuyển ngành Công nghệ chế biến thủy sản được hưởng chính sách GIẢM 50% HỌC PHÍ trong học kỳ 1.""",
            """[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Điểm sàn nhận hồ sơ xét tuyển bổ sung 100 chỉ tiêu năm 2026]
Mức điểm sàn nhận hồ sơ xét tuyển đợt bổ sung cho các chương trình LKQT và ngành Công nghệ chế biến thủy sản:
- Điểm thi tốt nghiệp THPT 2026: Từ 16.00 điểm trở lên.
- Xét học bạ THPT: Từ 20.00 điểm trở lên.
- Điểm Đánh giá năng lực ĐHQG-HCM: Từ 600 điểm trở lên.
- Điểm ĐGNL chuyên biệt ĐHSP TP.HCM: Từ 20 điểm trở lên (một số ngành LKQT áp dụng thang 30 điểm).
Hình thức nộp hồ sơ: Nộp trực tiếp tại Trung tâm Tuyển sinh & Truyền thông HUIT (140 Lê Trọng Tấn, P. Tây Thạnh, Q. Tân Phú, TP.HCM) hoặc đăng ký trực tuyến tại website: ts.huit.edu.vn."""
        ]
    },
    {
        "title": "Thông báo rút học phí đối với sinh viên nhập học năm học 2026 - 2027 - HUIT",
        "source_url": "https://ts.huit.edu.vn/thong-bao/thong-bao-rut-hoc-phi-sinh-vien-nhap-hoc-nam-hoc-2026-2027",
        "category": "tuition",
        "year": 2026,
        "date": "14/08/2026",
        "chunks": [
            """[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Chính sách rút học phí sinh viên nhập học năm học 2026 - 2027]
Nhà trường ban hành thông báo ngày 14/08/2026 quy định điều kiện và thủ tục giải quyết rút học phí đối với tân sinh viên đã nộp học phí nhập học nhưng có nguyện vọng rút hồ sơ (do trúng tuyển trường khác theo diện ưu tiên hoặc lý do chính đáng khác).
Thí sinh hoặc phụ huynh cần chuẩn bị: Đơn xin rút học phí (theo mẫu của HUIT), Phiếu thu/Biên lai nộp tiền hoặc sao kê chuyển khoản hợp lệ, Bản sao CCCD, Giấy báo trúng tuyển/chứng minh lý do rút hồ sơ.
Địa điểm tiếp nhận và xử lý: Phòng Tài chính - Kế toán phối hợp Phòng Công tác Sinh viên tại Trụ sở chính HUIT (140 Lê Trọng Tấn, P. Tây Thạnh, Q. Tân Phú, TP.HCM). Hotline: 096 205 1080."""
        ]
    },
    {
        "title": "Thông báo tuyển sinh liên thông từ Cao đẳng lên Đại học đợt 2 năm 2026 khoa Du lịch và Ẩm thực",
        "source_url": "https://ts.huit.edu.vn/thong-bao/thong-bao-tuyen-sinh-lien-thong-tu-cao-dang-len-dai-hoc-nam-2026-dot-2-khoa-du-lich-va-am-thuc",
        "category": "admission",
        "year": 2026,
        "date": "03/09/2026",
        "chunks": [
            """[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Tuyển sinh liên thông CĐ lên ĐH đợt 2 năm 2026 Khoa Du lịch và Ẩm thực]
Ngày 03/09/2026, Nhà trường thông báo tuyển sinh liên thông từ trình độ Cao đẳng lên trình độ Đại học đợt 2 năm 2026 cho Khoa Du lịch và Ẩm thực.
Đối tượng: Thí sinh đã tốt nghiệp Cao đẳng các ngành Du lịch, Khách sạn, Nhà hàng, Chế biến món ăn và các ngành gần.
Thời gian đào tạo: 1.5 năm (khoảng 3 học kỳ). Bằng tốt nghiệp Đại học chính quy do Trường Đại học Công Thương TP.HCM cấp."""
        ]
    },
    {
        "title": "Tổng quan Bảng Điểm chuẩn Trúng tuyển Đại học chính quy HUIT năm 2026 (Chính thức công bố 09/08/2026)",
        "source_url": "https://ts.huit.edu.vn/tin-tuyen-sinh/diem-chuan-truong-dai-hoc-cong-thuong-tp-hcm-nam-2026",
        "category": "cutoff",
        "year": 2026,
        "date": "09/08/2026",
        "chunks": [
            """[Trường Đại học Công Thương TP.HCM (HUIT) | Nguồn chính thức ts.huit.edu.vn | Chủ đề: Điểm chuẩn trúng tuyển Đại học chính quy năm 2026]
Trường Đại học Công Thương TP.HCM đã chính thức công bố Điểm chuẩn trúng tuyển năm 2026 vào ngày 09/08/2026 cho 44 ngành và chương trình đào tạo.
1. Theo phương thức Điểm thi tốt nghiệp THPT năm 2026:
- Mức điểm trúng tuyển dao động từ 16.00 đến 23.00 điểm.
- Ngành lấy điểm chuẩn cao nhất: Công nghệ kỹ thuật điều khiển và tự động hóa (23.00 điểm).
- Ngành Logistics và Quản lý chuỗi cung ứng: 22.50 điểm.
- Ngành Công nghệ kỹ thuật điện, điện tử: 22.00 điểm.
- Ngành Công nghệ thực phẩm: 22.00 điểm.
- Ngành Marketing, Thương mại điện tử, Luật kinh tế: 21.75 điểm.
- Ngành Quản trị kinh doanh, Cơ điện tử: 21.50 điểm.
- Ngành Luật, Kế toán, Tài chính - ngân hàng: 21.25 điểm.
- Ngành Trí tuệ nhân tạo: 20.50 điểm.
- Ngành Công nghệ thông tin, Khoa học dữ liệu, An toàn thông tin: 20.00 điểm.
- Các ngành có điểm chuẩn thấp nhất: Công nghệ dệt, may (18.00 điểm); Công nghệ chế biến thủy sản (16.00 điểm).
2. Theo phương thức Xét học bạ THPT: Điểm chuẩn từ 20.00 đến 25.63 điểm (Tự động hóa 25.63 điểm, Logistics 25.00 điểm, CNTT 24.50 điểm).
3. Theo phương thức Đánh giá năng lực ĐHQG-HCM: Điểm chuẩn từ 600 đến 825 điểm (Tự động hóa 825 điểm, Logistics/Ngôn ngữ 800 điểm)."""
        ]
    }
]

added_count = 0
for article in LATEST_ARTICLES:
    for idx, chunk_text in enumerate(article["chunks"]):
        chunk_hash = hashlib.md5(f"{article['source_url']}_{idx}_{chunk_text[:50]}".encode("utf-8")).hexdigest()
        
        # Check if already indexed
        existing = kb.find_one({"chunk_hash": chunk_hash})
        if existing:
            print(f"Skipping existing chunk: {article['title'][:40]} (chunk {idx})")
            continue
            
        print(f"Generating embedding for: {article['title'][:40]} (chunk {idx})...")
        emb_list = list(embedder.embed([f"passage: {chunk_text}"]))[0].tolist()
        
        doc = {
            "chunk_hash": chunk_hash,
            "title": article["title"],
            "url": article["source_url"],
            "source_url": article["source_url"],
            "text": chunk_text,
            "raw_text": chunk_text,
            "category": article["category"],
            "year": article["year"],
            "date": article["date"],
            "embedding": emb_list,
            "cluster_id": 0,
            "created_at": "2026-09-11T18:30:00Z"
        }
        kb.insert_one(doc)
        added_count += 1

print(f"Successfully added {added_count} new real-time news chunks to MongoDB Atlas huit_kb!")
print(f"Total chunks in collection now: {kb.count_documents({})}")
