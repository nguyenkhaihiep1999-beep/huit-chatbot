#!/usr/bin/env python3
"""Build a conservative source set containing only verified HUIT facts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from build_full_huit_dataset import MAJORS_DATA


HERE = Path(__file__).resolve().parent
RETRIEVED_AT = datetime.now(timezone.utc).isoformat()
CATALOG_URL = "https://ts.huit.edu.vn/nganh-dao-tao/dai-hoc"


def page(url: str, title: str, markdown: str) -> dict:
    return {
        "url": url,
        "title": title,
        "markdown": markdown.strip(),
        "official": True,
        "retrieved_at": RETRIEVED_AT,
        "source_domain": "ts.huit.edu.vn",
    }


def major_pages() -> list[dict]:
    docs = []
    for major in MAJORS_DATA:
        name = major["name"]
        code = major["code"]
        url = f"https://ts.huit.edu.vn/nganh-dh/{major['slug']}"
        docs.append(page(
            url,
            f"Ngành {name}",
            (
                f"# Ngành {name}\n\n"
                f"- Mã ngành: {code}\n"
                "- Hệ đào tạo: Đại học chính quy HUIT.\n"
                f"- Ngành {name} nằm trong danh mục 39 ngành đào tạo đại học "
                "chính quy được HUIT công bố cho mùa tuyển sinh 2026.\n\n"
                "Các thông tin về tổ hợp, chương trình học và thời gian đào tạo "
                "cần được đối chiếu trực tiếp tại trang ngành theo đường dẫn nguồn."
            ),
        ))
    return docs


CORE_PAGES = [
    page(
        "https://ts.huit.edu.vn/thong-bao/thong-tin-tuyen-sinh-dai-hoc-nam-2026",
        "Thông tin tuyển sinh Đại học năm 2026",
        """
# Phương thức tuyển sinh đại học chính quy HUIT năm 2026

HUIT tuyển sinh trong cả nước và không tổ chức xét tuyển sớm. Trường công bố 5 phương thức:

1. Xét kết quả thi tốt nghiệp THPT năm 2026.
2. Xét kết quả học tập THPT của lớp 10, 11 và 12.
3. Xét kết quả kỳ thi Đánh giá năng lực do Đại học Quốc gia TP.HCM tổ chức năm 2026.
4. Xét tuyển thẳng theo quy định của Bộ Giáo dục và Đào tạo.
5. Xét kết quả môn thi Đánh giá năng lực chuyên biệt của Trường Đại học Sư phạm TP.HCM năm 2026 kết hợp kết quả học tập THPT.

Thí sinh cần thực hiện các bước đăng ký theo lịch và hướng dẫn chính thức của HUIT và Bộ Giáo dục và Đào tạo.
""",
    ),
    page(
        "https://ts.huit.edu.vn/thong-bao/diem-san-xet-tuyen-dai-hoc-nam-2026-truong-dai-hoc-cong-thuong-tp-hcm",
        "Điểm sàn xét tuyển đại học HUIT năm 2026",
        """
# Điểm sàn HUIT năm 2026

- Điểm thi tốt nghiệp THPT: ngành Luật và Luật kinh tế 20 điểm; các ngành còn lại 16 điểm.
- Kết quả học tập THPT: ngành Luật và Luật kinh tế 20 điểm; các ngành còn lại 20 điểm.
- Đánh giá năng lực ĐHQG-HCM: ngành Luật và Luật kinh tế 720 điểm; các ngành còn lại 600 điểm.
- Đánh giá năng lực chuyên biệt của Trường Đại học Sư phạm TP.HCM kết hợp học tập THPT: ngành Luật và Luật kinh tế 20 điểm; các ngành còn lại 20 điểm.

Đây là ngưỡng đảm bảo chất lượng đầu vào, không phải điểm trúng tuyển.
""",
    ),
    page(
        "https://ts.huit.edu.vn/47159/hoc-phi-huit-nam-2026-minh-bach-thong-tin-dong-hanh-cung-nguoi-hoc",
        "Học phí HUIT khóa K26 năm 2026",
        """
# Học phí đại học chính quy HUIT khóa K26 năm 2026

- Tín chỉ lý thuyết: 1.100.000 đồng/tín chỉ.
- Tín chỉ thực hành: 1.350.000 đồng/tín chỉ.
- Học phí toàn khóa của các ngành cử nhân phổ biến: khoảng 143–148 triệu đồng, tùy cơ cấu tín chỉ.
- Chương trình kỹ sư: khoảng 177–188 triệu đồng toàn khóa do thời gian và số tín chỉ nhiều hơn.
- Kinh doanh quốc tế hệ cử nhân: khoảng 144,05 triệu đồng toàn khóa năm 2026.
- Marketing hệ cử nhân: khoảng 144,55 triệu đồng toàn khóa năm 2026.

Học phí thực tế của từng sinh viên phụ thuộc chương trình và số tín chỉ đăng ký.
""",
    ),
    page(
        "https://ts.huit.edu.vn/47159/hoc-phi-huit-nam-2026-minh-bach-thong-tin-dong-hanh-cung-nguoi-hoc",
        "Học bổng và hỗ trợ người học HUIT năm 2026",
        """
# Học bổng và hỗ trợ tài chính HUIT năm 2026

HUIT công bố các nhóm hỗ trợ gồm học bổng khuyến khích học tập, học bổng tiếp sức đến trường, học bổng thành tích ngoại khóa, học bổng thủ khoa – á khoa đầu vào và học bổng sinh viên vượt khó.

Trường còn có chính sách trợ cấp khó khăn, hỗ trợ trường hợp đặc biệt, anh chị em ruột học chung trường, miễn giảm học phí, ưu đãi giáo dục và tín dụng học tập theo quy định.

Nguồn chính thức không công bố một mức giảm 50% học phí học kỳ đầu áp dụng chung cho mọi sinh viên hoặc mọi ngành chính quy.
""",
    ),
    page(
        "https://ts.huit.edu.vn/tuyen-sinh/co-hoi-nhan-hoc-bong-len-den-100-hoc-phi-cua-vien-quoc-te-huit-tu-diem-hoc-ba",
        "Học bổng Viện Quốc tế HUIT năm 2026",
        """
# Học bổng riêng của Viện Quốc tế HUIT năm 2026

Chính sách này áp dụng cho chương trình liên kết quốc tế, không phải chính sách chung của hệ đại học chính quy.

- Học bổng 100% dành cho thí sinh đủ điều kiện thành tích được công bố; điều kiện duy trì gồm điểm trung bình tích lũy và điểm rèn luyện.
- Học bổng 70% học phí học kỳ I dành cho thí sinh đăng ký sớm đủ điều kiện điểm học bạ theo thông báo.
- Có voucher hoặc miễn học phí theo mức chứng chỉ ngoại ngữ IELTS, TOEIC, VSTEP hoặc HSK quy định trong thông báo.

Thời hạn và điều kiện cần kiểm tra lại trên trang chính thức trước khi đăng ký.
""",
    ),
    page(
        CATALOG_URL,
        "Thông tin liên hệ tuyển sinh HUIT",
        """
# Liên hệ tuyển sinh HUIT

- Địa chỉ: 140 Lê Trọng Tấn, Phường Tây Thạnh, TP.HCM.
- Điện thoại: 028 6270 6275.
- Hotline: 096 205 1080.
- Email: tuyensinh@huit.edu.vn.
- Cổng thông tin tuyển sinh: https://ts.huit.edu.vn.
""",
    ),
]


def main() -> None:
    docs = major_pages() + CORE_PAGES
    output = HERE / "scraped_pages.json"
    output.write_text(
        json.dumps(docs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (HERE / "urls_to_scrape.json").write_text(
        json.dumps([doc["url"] for doc in docs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] verified_pages={len(docs)} output={output}")


if __name__ == "__main__":
    main()
