"""
pdf_renderer.py
Trình dựng tài liệu PDF (.pdf) chuyên nghiệp chuẩn nhận diện HUIT.
Sử dụng thư viện reportlab:
- Đăng ký font TrueType Unicode tiếng Việt (Arial / Tahoma / DejaVuSans).
- Header xanh hoàng gia HUIT (#0066C4), căn chỉnh lề chuyên nghiệp.
- Bảng dữ liệu có dòng xen kẽ (zebra striping), viền lưới thanh lịch, căn lề số liệu tự động.
- Chân trang đánh số trang và ghi chú bản quyền tuyển sinh.
"""
import io
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Đăng ký font tiếng Việt Unicode
_FONT_NAME = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"

def _setup_vietnamese_fonts():
    global _FONT_NAME, _FONT_BOLD
    font_candidates = [
        ("VietnameseFont", "VietnameseFont-Bold", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("VietnameseFont", "VietnameseFont-Bold", "C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahomabd.ttf"),
        ("VietnameseFont", "VietnameseFont-Bold", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
        ("VietnameseFont", "VietnameseFont-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for fn, fnb, p_reg, p_bold in font_candidates:
        if os.path.exists(p_reg) and os.path.exists(p_bold):
            try:
                pdfmetrics.registerFont(TTFont(fn, p_reg))
                pdfmetrics.registerFont(TTFont(fnb, p_bold))
                _FONT_NAME = fn
                _FONT_BOLD = fnb
                return
            except Exception:
                pass

_setup_vietnamese_fonts()

# Màu sắc thương hiệu HUIT
COLOR_HUIT_BLUE = colors.HexColor("#0066C4")
COLOR_HUIT_NAVY = colors.HexColor("#004C99")
COLOR_ZEBRA_BG = colors.HexColor("#F8FAFC")
COLOR_BORDER = colors.HexColor("#CBD5E1")
COLOR_TEXT_MAIN = colors.HexColor("#0F172A")
COLOR_TEXT_MUTED = colors.HexColor("#64748B")


def render_manifest_to_pdf(manifest: Dict[str, Any]) -> io.BytesIO:
    """
    Dựng file PDF (.pdf) từ Artifact Manifest.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName=_FONT_BOLD,
        fontSize=15,
        leading=19,
        textColor=COLOR_HUIT_NAVY,
        alignment=1,  # Center
        spaceAfter=4
    )

    sub_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName=_FONT_NAME,
        fontSize=8.5,
        leading=12,
        textColor=COLOR_TEXT_MUTED,
        alignment=1,  # Center
        spaceAfter=14
    )

    inst_style = ParagraphStyle(
        'InstitutionHeader',
        parent=styles['Normal'],
        fontName=_FONT_BOLD,
        fontSize=10.5,
        leading=14,
        textColor=COLOR_HUIT_BLUE,
        spaceAfter=2
    )

    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName=_FONT_NAME,
        fontSize=8.5,
        leading=11,
        textColor=COLOR_TEXT_MAIN
    )

    cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName=_FONT_BOLD,
        fontSize=8.5,
        leading=11,
        textColor=COLOR_HUIT_NAVY
    )

    header_cell_style = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontName=_FONT_BOLD,
        fontSize=9,
        leading=12,
        textColor=colors.white,
        alignment=1
    )

    elements = []

    # 1. Cơ quan chủ quản & Trường
    elements.append(Paragraph("BỘ CÔNG THƯƠNG", ParagraphStyle('Sub', fontName=_FONT_BOLD, fontSize=8, textColor=COLOR_TEXT_MUTED)))
    elements.append(Paragraph("TRƯỜNG ĐẠI HỌC CÔNG THƯƠNG TP. HỒ CHÍ MINH (HUIT)", inst_style))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=COLOR_HUIT_BLUE, spaceBefore=4, spaceAfter=12))

    # 2. Tiêu đề
    title = manifest.get("title") or "BÁO CÁO THÔNG TIN TUYỂN SINH HUIT"
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    elements.append(Paragraph(title.upper(), title_style))
    elements.append(Paragraph(f"Cổng thông tin tuyển sinh chính thức: ts.huit.edu.vn  •  Thời gian xuất: {now_str}", sub_style))

    # 3. Dữ liệu bảng
    content = manifest.get("content") or {}
    headers = content.get("headers")
    rows = content.get("rows")

    if headers and rows:
        col_count = len(headers)
        page_width = A4[0] - 72  # 523 points
        # Tính toán độ rộng từng cột
        if col_count == 5:
            col_widths = [65, 175, 125, 80, 78]
        elif col_count == 4:
            col_widths = [75, 210, 120, 118]
        else:
            col_widths = [page_width / col_count] * col_count

        table_data = []
        # Dòng tiêu đề
        table_data.append([Paragraph(str(h), header_cell_style) for h in headers])

        for r_idx, r in enumerate(rows):
            row_items = []
            for c_idx, val in enumerate(r):
                if c_idx >= col_count:
                    break
                val_str = str(val).strip()
                align_center = c_idx in (0, col_count - 1) or bool(re.match(r"^\d+(\.\d+)?$", val_str))
                c_style = cell_bold if c_idx == 0 or (c_idx == 3 and any(ch.isdigit() for ch in val_str)) else cell_style
                if align_center:
                    c_style = ParagraphStyle('Center', parent=c_style, alignment=1)
                row_items.append(Paragraph(val_str, c_style))
            table_data.append(row_items)

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t_style = [
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_HUIT_BLUE),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ]
        # Thêm zebra background
        for r_i in range(1, len(table_data)):
            if r_i % 2 == 0:
                t_style.append(('BACKGROUND', (0, r_i), (-1, r_i), COLOR_ZEBRA_BG))
        t.setStyle(TableStyle(t_style))
        elements.append(t)

    elif content.get("cutoff_boxes") or content.get("major_code"):
        fields = [
            ("Mã ngành", content.get("major_code", "7XXXXXX")),
            ("Tên ngành đào tạo", content.get("title", content.get("major_name", ""))),
            ("Khoa phụ trách", content.get("faculty", "Khoa Đào tạo HUIT")),
            ("Thời gian đào tạo", content.get("duration", "3.5 - 4 năm (150 tín chỉ)")),
            ("Định mức học phí", content.get("tuition", "14 - 16 triệu đồng/học kỳ")),
            ("Tổ hợp môn xét tuyển", ", ".join(content.get("subject_combinations", []))),
            ("Chính sách học bổng", content.get("scholarship_highlight", "Học bổng khuyến khích học tập")),
        ]
        table_data = []
        for label, val in fields:
            table_data.append([Paragraph(label, cell_bold), Paragraph(str(val), cell_style)])
        t = Table(table_data, colWidths=[140, 383])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), COLOR_ZEBRA_BG),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ]))
        elements.append(t)

    # 4. Ghi chú chân trang
    elements.append(Spacer(1, 14))
    note_text = (
        "<b>📌 Lưu ý:</b> Dữ liệu chính thức được cung cấp bởi Hội đồng Tuyển sinh Trường Đại học Công Thương TP.HCM (HUIT). "
        "Nhà trường cam kết minh bạch học phí và không tăng học phí đột biến. Thí sinh tra cứu thêm thông tin tại ts.huit.edu.vn."
    )
    elements.append(Paragraph(note_text, ParagraphStyle('Note', parent=styles['Normal'], fontName=_FONT_NAME, fontSize=8, textColor=COLOR_TEXT_MUTED, leading=11)))

    doc.build(elements)
    buf.seek(0)
    return buf
