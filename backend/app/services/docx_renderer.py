"""
docx_renderer.py
Trình dựng tài liệu Microsoft Word (.docx) chuyên nghiệp chuẩn nhận diện HUIT.
Sử dụng thư viện python-docx:
- Tiêu đề trường chuẩn thương hiệu: TRƯỜNG ĐẠI HỌC CÔNG THƯƠNG TP. HỒ CHÍ MINH (HUIT).
- Bảng biểu định dạng màu sắc HUIT Royal Blue (#0066C4), đường viền sắc nét, dòng xen kẽ (zebra).
- Ghi chú quy chế tuyển sinh, nguồn dẫn và ngày giờ tạo.
"""
import io
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

# Màu sắc nhận diện HUIT
COLOR_HUIT_BLUE = RGBColor(0, 102, 196)       # #0066C4
COLOR_HUIT_NAVY = RGBColor(0, 76, 153)        # #004C99
COLOR_TEXT_MAIN = RGBColor(15, 23, 42)        # #0F172A
COLOR_TEXT_MUTED = RGBColor(100, 116, 139)    # #64748B

HEX_HUIT_BLUE = "0066C4"
HEX_ZEBRA_BG = "F8FAFC"
HEX_BORDER = "CBD5E1"


def _set_cell_background(cell, hex_color: str):
    """Đặt màu nền cho một ô trong bảng Word."""
    shading_xml = f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>'
    cell._tc.get_or_add_tcPr().append(parse_xml(shading_xml))


def _set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Đặt lề trong (padding) cho một ô trong bảng."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)


def _set_table_borders(table, color="CBD5E1", sz="4", val="single"):
    """Đặt viền mỏng tinh tế cho toàn bộ bảng Word."""
    tblPr = table._tbl.tblPr
    borders_xml = f"""
    <w:tblBorders {nsdecls("w")}>
        <w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
        <w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
        <w:insideH w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
        <w:insideV w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
        <w:left w:val="none"/>
        <w:right w:val="none"/>
    </w:tblBorders>
    """
    tblPr.append(parse_xml(borders_xml))


def render_manifest_to_docx(manifest: Dict[str, Any]) -> io.BytesIO:
    """
    Dựng file Word (.docx) từ Artifact Manifest.
    Hỗ trợ cả dạng bảng tra cứu số liệu (spreadsheet), thẻ ngành và văn bản lộ trình.
    """
    doc = docx.Document()

    # Thiết lập lề trang chuẩn (1 inch = 2.54 cm)
    sections = doc.sections
    for s in sections:
        s.top_margin = Inches(0.8)
        s.bottom_margin = Inches(0.8)
        s.left_margin = Inches(0.9)
        s.right_margin = Inches(0.9)

    title = manifest.get("title") or "BÁO CÁO THÔNG TIN TUYỂN SINH HUIT"
    content = manifest.get("content") or {}
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # 1. Header Cơ quan chủ quản & Tên trường
    header_para = doc.add_paragraph()
    header_para.paragraph_format.space_after = Pt(2)
    header_para.paragraph_format.line_spacing = 1.15
    run_inst = header_para.add_run("BỘ CÔNG THƯƠNG\n")
    run_inst.font.name = "Calibri"
    run_inst.font.size = Pt(10)
    run_inst.font.bold = True
    run_inst.font.color.rgb = COLOR_TEXT_MUTED

    run_school = header_para.add_run("TRƯỜNG ĐẠI HỌC CÔNG THƯƠNG TP. HỒ CHÍ MINH (HUIT)")
    run_school.font.name = "Calibri"
    run_school.font.size = Pt(12)
    run_school.font.bold = True
    run_school.font.color.rgb = COLOR_HUIT_BLUE

    # 2. Tiêu đề tài liệu
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_para.paragraph_format.space_before = Pt(14)
    title_para.paragraph_format.space_after = Pt(4)
    run_title = title_para.add_run(title.upper())
    run_title.font.name = "Calibri"
    run_title.font.size = Pt(16)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_HUIT_NAVY

    # Phụ đề & Thời gian xuất
    sub_para = doc.add_paragraph()
    sub_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_para.paragraph_format.space_after = Pt(16)
    run_sub = sub_para.add_run(f"Cổng thông tin tuyển sinh chính thức: https://ts.huit.edu.vn  •  Thời gian xuất: {now_str}")
    run_sub.font.name = "Calibri"
    run_sub.font.size = Pt(9.5)
    run_sub.font.italic = True
    run_sub.font.color.rgb = COLOR_TEXT_MUTED

    # 3. Dựng nội dung tùy theo cấu trúc dữ liệu
    headers = content.get("headers")
    rows = content.get("rows")

    if headers and rows:
        # Bảng biểu dạng Excel/Số liệu
        table = doc.add_table(rows=len(rows) + 1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(table, color=HEX_BORDER)

        # Header Bảng
        hdr_cells = table.rows[0].cells
        for col_idx, head_text in enumerate(headers):
            c = hdr_cells[col_idx]
            _set_cell_background(c, HEX_HUIT_BLUE)
            _set_cell_margins(c, top=140, bottom=140, left=160, right=160)
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = c.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if col_idx in (0, len(headers)-1) else WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(str(head_text))
            r.font.name = "Calibri"
            r.font.size = Pt(10.5)
            r.font.bold = True
            r.font.color.rgb = RGBColor(255, 255, 255)

        # Các dòng dữ liệu
        for row_idx, r_data in enumerate(rows, start=1):
            row_cells = table.rows[row_idx].cells
            is_zebra = (row_idx % 2 == 0)
            bg_color = HEX_ZEBRA_BG if is_zebra else "FFFFFF"

            for col_idx, val in enumerate(r_data):
                if col_idx >= len(headers):
                    break
                c = row_cells[col_idx]
                if is_zebra:
                    _set_cell_background(c, bg_color)
                _set_cell_margins(c, top=100, bottom=100, left=160, right=160)
                c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                p = c.paragraphs[0]
                val_str = str(val).strip()
                align_center = col_idx in (0, len(headers)-1) or bool(re.match(r"^\d+(\.\d+)?$", val_str))
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER if align_center else WD_ALIGN_PARAGRAPH.LEFT

                r = p.add_run(val_str)
                r.font.name = "Calibri"
                r.font.size = Pt(10)
                if col_idx == 0 or (col_idx == 3 and any(ch.isdigit() for ch in val_str)):
                    r.font.bold = True
                    r.font.color.rgb = COLOR_HUIT_NAVY
                else:
                    r.font.color.rgb = COLOR_TEXT_MAIN

    elif content.get("cutoff_boxes") or content.get("major_code"):
        # Thẻ thông tin ngành đào tạo
        table = doc.add_table(rows=0, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(table, color=HEX_BORDER)

        fields = [
            ("Mã ngành", content.get("major_code", "7XXXXXX")),
            ("Tên ngành đào tạo", content.get("title", content.get("major_name", ""))),
            ("Khoa phụ trách", content.get("faculty", "Khoa Đào tạo HUIT")),
            ("Thời gian đào tạo", content.get("duration", "3.5 - 4 năm (150 tín chỉ)")),
            ("Định mức học phí", content.get("tuition", "14 - 16 triệu đồng/học kỳ")),
            ("Tổ hợp môn xét tuyển", ", ".join(content.get("subject_combinations", []))),
            ("Chính sách học bổng", content.get("scholarship_highlight", "Học bổng khuyến khích học tập")),
            ("Vị trí việc làm sau tốt nghiệp", ", ".join(content.get("career_highlights", []))),
        ]

        for label, val in fields:
            row = table.add_row()
            c1, c2 = row.cells
            _set_cell_background(c1, HEX_ZEBRA_BG)
            _set_cell_margins(c1, top=100, bottom=100, left=160, right=160)
            _set_cell_margins(c2, top=100, bottom=100, left=160, right=160)

            p1 = c1.paragraphs[0]
            r1 = p1.add_run(label)
            r1.font.bold = True
            r1.font.size = Pt(10)
            r1.font.color.rgb = COLOR_HUIT_NAVY

            p2 = c2.paragraphs[0]
            r2 = p2.add_run(str(val))
            r2.font.size = Pt(10)
            r2.font.color.rgb = COLOR_TEXT_MAIN

    # 4. Ghi chú chân trang & Cam kết
    doc.add_paragraph().paragraph_format.space_before = Pt(12)
    note_p = doc.add_paragraph()
    note_p.paragraph_format.space_after = Pt(4)
    run_note_title = note_p.add_run("📌 LƯU Ý & CAM KẾT CHẤT LƯỢNG ĐÀO TẠO:\n")
    run_note_title.font.bold = True
    run_note_title.font.size = Pt(10)
    run_note_title.font.color.rgb = COLOR_HUIT_NAVY

    run_note_desc = note_p.add_run(
        "1. Thông tin trên được trích xuất từ Đề án Tuyển sinh chính thức năm 2026 của Trường Đại học Công Thương TP.HCM.\n"
        "2. Nhà trường cam kết minh bạch học phí và không tăng học phí đột biến trong suốt lộ trình đào tạo chuẩn.\n"
        "3. Thí sinh và phụ huynh có thể liên hệ trực tiếp Trung tâm Tuyển sinh & Truyền thông HUIT qua hotline: (028) 3816 1673."
    )
    run_note_desc.font.size = Pt(9.5)
    run_note_desc.font.color.rgb = COLOR_TEXT_MUTED

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
