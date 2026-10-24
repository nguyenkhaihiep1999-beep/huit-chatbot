"""Export the proposed JEV architecture as a portable SVG and PNG (offline)."""
from pathlib import Path
from html import escape
import math
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 2400, 1880
BG, INK, MUTED = '#f5f7fa', '#172636', '#536477'
BLUE, PALE, LINE = '#176b91', '#e8f3f8', '#8a9bad'
img = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(img)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       '<title>JEV — Kiến trúc cải tiến đề xuất</title>',
       '<desc>Sơ đồ đề xuất dựa trên mã nguồn ngày 22/10/2026; chưa triển khai và chưa đối chiếu ảnh gốc.</desc>',
       f'<rect width="{W}" height="{H}" fill="{BG}"/>']
fonts = {}

def font(size, bold=False):
    k = (size, bold)
    if k not in fonts:
        fonts[k] = ImageFont.truetype('C:/Windows/Fonts/' + ('arialbd.ttf' if bold else 'arial.ttf'), size)
    return fonts[k]

def text(x, y, value, size=26, color=INK, bold=False, center=False):
    f = font(size, bold)
    width = d.textlength(value, font=f)
    left = x-width/2 if center else x
    d.text((left, y), value, font=f, fill=color)
    svg.append(f'<text x="{x}" y="{y+size}" font-family="Arial, sans-serif" font-size="{size}" '
               f'font-weight="{700 if bold else 400}" fill="{color}" text-anchor="{"middle" if center else "start"}">{escape(value)}</text>')

def rect(x, y, w, h, fill='white', stroke='#cad4de', radius=16, dashed=False):
    d.rounded_rectangle((x,y,x+w,y+h), radius, fill=fill, outline=stroke, width=2)
    dash = 'stroke-dasharray="10 7"' if dashed else ''
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2" {dash}/>')

def node(x, y, w, h, title, lines=(), new=False):
    rect(x,y,w,h,PALE if new else 'white',BLUE if new else '#cad4de')
    text(x+25,y+18,title,29,BLUE if new else INK,True)
    for i, value in enumerate(lines):
        text(x+25,y+60+i*34,value,25,MUTED)

def arrow(points, label=None, label_at=None, dashed=False, color=LINE):
    for a,b in zip(points,points[1:]):
        if dashed:
            length=math.dist(a,b)
            for offset in range(0,int(length),17):
                p=min(1,offset/max(length,1)); q=min(1,(offset+9)/max(length,1))
                d.line((a[0]+(b[0]-a[0])*p,a[1]+(b[1]-a[1])*p,a[0]+(b[0]-a[0])*q,a[1]+(b[1]-a[1])*q),fill=color,width=3)
        else:
            d.line((a,b),fill=color,width=3)
    a,b=points[-2:]
    angle=math.atan2(b[1]-a[1],b[0]-a[0])
    p=(b[0]-15*math.cos(angle-.5),b[1]-15*math.sin(angle-.5))
    q=(b[0]-15*math.cos(angle+.5),b[1]-15*math.sin(angle+.5))
    d.polygon((b,p,q),fill=color)
    pts=' '.join(f'{x},{y}' for x,y in points)
    dash='stroke-dasharray="10 7"' if dashed else ''
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3" {dash}/>')
    svg.append(f'<polygon points="{b[0]},{b[1]} {p[0]},{p[1]} {q[0]},{q[1]}" fill="{color}"/>')
    if label:
        x,y=label_at
        tw=d.textlength(label,font=font(23))
        d.rectangle((x-5,y-2,x+tw+5,y+30),fill=BG)
        svg.append(f'<rect x="{x-5}" y="{y-2}" width="{tw+10}" height="32" fill="{BG}"/>')
        text(x,y,label,23,MUTED)

text(70,40,'JEV / KIẾN TRÚC CẢI TIẾN ĐỀ XUẤT',46,bold=True)
text(70,105,'HUIT Chatbot · Kiểm tra mã nguồn 22/10/2026 · Chưa triển khai · Chưa đối chiếu ảnh gốc',26,MUTED)
rect(70,158,24,24,PALE,BLUE,4)
text(108,154,'Khối xanh: phần cần bổ sung hoặc thay đổi',24,MUTED)
text(1520,154,'Nét đứt: đo lường ngoài luồng trả lời',24,MUTED)

node(760,220,720,90,'Câu hỏi + lịch sử hội thoại liên quan')
node(760,360,720,100,'Guardrail → Danh mục → Cache', ['Giữ các lối trả lời nhanh đang có'])
node(1660,360,650,100,'Trả lời trực tiếp', ['Guardrail / danh mục / cache có kết quả'])
node(760,520,720,140,'1. Chuẩn hóa ngữ cảnh tối thiểu', ['Ngành · năm · phương thức · ý định hiện có', 'Dữ liệu gửi JEV phải được che thông tin riêng tư'],True)
node(70,520,590,140,'JEV A / Phân giải ý định', ['Chỉ gọi khi mơ hồ; kiểm tra schema + ngưỡng', 'Giữ baseline nếu lỗi / thiếu độ tin cậy'])
node(760,780,720,130,'2. Truy xuất + xếp hạng theo intent', ['Truyền intent đã duyệt vào retrieve / rerank', 'Ràng buộc ngành · năm; giữ tìm kiếm dự phòng'],True)
node(70,1010,590,175,'3. JEV B / Đánh giá minh chứng', ['Dùng cùng dữ kiện thực tế sẽ gửi cho LLM', 'Kèm URL · năm · đoạn chứa câu trả lời', 'Giới hạn byte sau khi che dữ liệu riêng tư'],True)
node(760,1000,720,200,'4. Policy quyết định hành động', ['Đủ → trả lời; một phần → nêu phần còn thiếu', 'Thiếu chi tiết câu hỏi → hỏi lại cụ thể', 'Thiếu / xung đột nguồn → thử truy xuất lại', 'Hết lượt hoặc vẫn thiếu → nêu giới hạn'],True)
node(1660,1000,650,100,'Hỏi lại hoặc trả lời giới hạn', ['Không khẳng định dữ kiện thiếu căn cứ'])
node(1660,1160,650,140,'Truy xuất bổ sung tối đa 1 lần', ['Chỉ khi còn ngân sách request', 'Nếu vẫn thiếu → quay về policy'],True)
node(760,1320,720,110,'LLM chính sinh câu trả lời', ['Chỉ dùng minh chứng được policy cho phép'])
node(760,1490,720,100,'NDJSON → giao diện người dùng', ['Câu trả lời + nguồn trích dẫn'])

node(1660,520,650,290,'5. Shadow qua hàng đợi có giới hạn', ['Đề xuất: tách khỏi thời gian chờ trả lời', 'Nhận câu hỏi + evidence của baseline', 'Lấy mẫu state đã che dữ liệu riêng tư', 'Worker được quản lý, timeout rõ ràng', 'Đầy hàng đợi → bỏ mẫu, không chặn chat', 'Không dùng kết quả để sửa câu trả lời'],True)
node(1660,1460,650,130,'Telemetry đã khử thông tin nhạy cảm', ['TTFT · timeout · fallback · quyết định áp dụng', 'Chất lượng câu trả lời · token / chi phí'])

rect(70,1270,590,320,'white','#cad4de')
text(95,1290,'RÀO CHẮN XUYÊN SUỐT',27,bold=True)
for i,line in enumerate(['Sửa cap UTF-8 và evidence_count.', 'Che dữ liệu trước khi cắt đoạn.', 'Deadline chung + phần dành cho evidence.', 'Giữ breaker / giới hạn đồng thời / retry.', 'Lỗi JEV → baseline hiện có.', 'Bump policy_version trong cache assist.']):
    text(95,1340+36*i,line,24,MUTED)

arrow([(1120,310),(1120,360)])
arrow([(1480,410),(1660,410)],'Có kết quả',(1488,373))
arrow([(1120,460),(1120,520)],'Chưa có',(1136,473))
arrow([(760,590),(660,590)],'Mơ hồ',(675,553))
arrow([(365,660),(365,725),(900,725),(900,780)],'Intent đạt ngưỡng / baseline',(400,687))
arrow([(1120,660),(1120,780)],'Rõ / off / shadow',(1140,694))
arrow([(760,845),(705,845),(705,975),(365,975),(365,1010)],'Assist + còn budget',(374,933))
arrow([(660,1090),(760,1090)])
arrow([(1120,910),(1120,1000)],'Baseline khi bỏ qua JEV',(1140,941))
arrow([(1480,1040),(1660,1040)])
arrow([(1480,1160),(1550,1160),(1550,1215),(1660,1215)])
arrow([(1985,1300),(1985,1335),(1590,1335),(1590,845),(1480,845)])
arrow([(1120,1200),(1120,1320)],'Có dữ kiện được phép dùng',(1138,1237))
arrow([(1120,1430),(1120,1490)])
arrow([(1480,1540),(1660,1540)],dashed=True)
arrow([(1480,590),(1660,590)],dashed=True)
arrow([(1480,890),(1620,890),(1620,750),(1660,750)],dashed=True)
arrow([(2310,670),(2350,670),(2350,1525),(2310,1525)],dashed=True)

rect(70,1660,2240,160,'#eaf0f5','#cad4de')
text(95,1680,'6. KIỂM CHỨNG TRƯỚC KHI MỞ RỘNG ASSIST',29,bold=True)
text(95,1728,'Tập câu hỏi có nhãn người duyệt → so sánh off / shadow / assist → đánh giá câu trả lời và nguồn trích dẫn.',27,MUTED)
text(95,1772,'Các báo cáo đã đọc dùng mock; chưa đủ kết luận JEV thật cải thiện chất lượng. Ngưỡng cần hiệu chỉnh bằng dữ liệu live.',25,MUTED)
text(70,1840,'Nguồn: pipeline.py · reranker.py · decision_engine/{service,policies,redaction}.py · docs/ARCHITECTURE.md',23,MUTED)

svg.append('</svg>')
(OUT/'jev-kien-truc-de-xuat.svg').write_text('\n'.join(svg),encoding='utf-8')
img.save(OUT/'jev-kien-truc-de-xuat.png',dpi=(180,180))
img.resize((1200,940),Image.Resampling.LANCZOS).save(OUT/'jev-preview.png')
print('Exported SVG, PNG (2400 x 1880) and preview.')
