"""Draw a proposed multi-question JEV controller. No product code is changed."""
from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont
import math

OUT = Path(__file__).resolve().parent
W,H = 2200,1980
BG,INK,MUTED,BLUE,PALE,LINE = '#f5f7fa','#172636','#536477','#176b91','#e8f3f8','#8a9bad'
img=Image.new('RGB',(W,H),BG)
d=ImageDraw.Draw(img)
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
     '<title>JEV 2.0 — Điều phối đa yêu cầu có kiểm chứng</title>',
     '<desc>Đề xuất kiến trúc, chưa triển khai. JEV chọn hành động trong policy; code điều phối công cụ và ngân sách.</desc>',
     f'<rect width="{W}" height="{H}" fill="{BG}"/>']
fonts={}

def text(x,y,value,size=25,bold=False,color=INK):
    key=(size,bold)
    if key not in fonts:
        fonts[key]=ImageFont.truetype('C:/Windows/Fonts/'+('arialbd.ttf' if bold else 'arial.ttf'),size)
    d.text((x,y),value,font=fonts[key],fill=color)
    svg.append(f'<text x="{x}" y="{y+size}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(value)}</text>')

def box(x,y,w,h,title,lines=(),accent=False):
    fill,stroke=(PALE,BLUE) if accent else ('white','#cad4de')
    d.rounded_rectangle((x,y,x+w,y+h),16,fill=fill,outline=stroke,width=2)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
    text(x+22,y+18,title,28,True,BLUE if accent else INK)
    for i,line in enumerate(lines):
        text(x+22,y+61+35*i,line,24,color=MUTED)

def arrow(points,label=None,at=None,dashed=False):
    for a,b in zip(points,points[1:]):
        length=math.dist(a,b)
        if dashed:
            for o in range(0,int(length),18):
                p=o/max(length,1);q=min(1,(o+10)/max(length,1))
                d.line((a[0]+(b[0]-a[0])*p,a[1]+(b[1]-a[1])*p,a[0]+(b[0]-a[0])*q,a[1]+(b[1]-a[1])*q),fill=LINE,width=3)
        else:
            d.line((a,b),fill=LINE,width=3)
    a,b=points[-2:];angle=math.atan2(b[1]-a[1],b[0]-a[0])
    p=(b[0]-15*math.cos(angle-.5),b[1]-15*math.sin(angle-.5))
    q=(b[0]-15*math.cos(angle+.5),b[1]-15*math.sin(angle+.5))
    d.polygon((b,p,q),fill=LINE)
    pts=' '.join(f'{x},{y}' for x,y in points)
    dash='stroke-dasharray="10 8"' if dashed else ''
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{LINE}" stroke-width="3" {dash}/>')
    svg.append(f'<polygon points="{b[0]},{b[1]} {p[0]},{p[1]} {q[0]},{q[1]}" fill="{LINE}"/>')
    if label:
        text(*at,label,22,color=MUTED)

text(70,40,'JEV 2.0 / ĐIỀU PHỐI ĐA YÊU CẦU CÓ KIỂM CHỨNG',43,True)
text(70,105,'Đề xuất thay đổi kiến trúc · HUIT Chatbot · 22/10/2026 · Chưa triển khai',26,color=MUTED)
box(70,170,2060,125,'BƯỚC THAY ĐỔI CHÍNH',[
    'Hiện tại: chọn một intent chính + đánh giá minh chứng → LLM trả lời.',
    'Đề xuất: tách từng yêu cầu → tìm nguồn riêng → kiểm tra từng kết luận → tổng hợp câu trả lời.'],True)

box(660,355,870,115,'Câu hỏi nhiều ý + ngữ cảnh cần thiết',[
    '“Học phí, điểm chuẩn CNTT và học bổng năm 2026?”'])
box(70,530,480,185,'Ngữ cảnh hội thoại',[
    'Ngành · năm · phương thức',
    'Chỉ giữ thông tin có căn cứ',
    'Che dữ liệu riêng tư trước gửi'])
box(660,530,870,185,'1. Tách yêu cầu + JEV chọn bước tiếp theo',[
    'Bộ lập kế hoạch dùng rule / LLM với schema chặt chẽ',
    'JEV hỗ trợ chọn: tìm nguồn / hỏi lại / trả lời',
    'Code kiểm tra kế hoạch và thực thi action cho phép'],True)
box(1650,530,480,185,'Bộ điều khiển bằng code',[
    'Giới hạn thời gian và chi phí',
    'Giới hạn số tác vụ song song',
    'Lỗi JEV → luồng RAG hiện có'])
text(70,825,'2. TRUY XUẤT TỪNG YÊU CẦU',26,True,color=BLUE)
text(70,870,'Song song trong giới hạn cấu hình',24,color=MUTED)
box(660,825,270,145,'Học phí', ['CNTT · 2026','Nguồn + dữ kiện'],True)
box(960,825,270,145,'Điểm chuẩn', ['CNTT · 2026','Nguồn + dữ kiện'],True)
box(1260,825,270,145,'Học bổng', ['Điều kiện · 2026','Nguồn + dữ kiện'],True)
box(660,1060,870,150,'3. Bảng kết luận gắn minh chứng',[
    'Mỗi kết luận có document_id + đoạn trích + năm + URL',
    'Ghi rõ: đã đủ / còn thiếu / xung đột nguồn'],True)
box(660,1300,870,150,'4. Cổng kiểm chứng trước khi trả lời',[
    'JEV đánh giá độ đủ; code kiểm tra nguồn / năm / số liệu',
    'Kết luận chưa có căn cứ → không cho khẳng định'],True)
box(1650,1060,480,185,'Tự bổ sung minh chứng',[
    'Tìm lại đúng phần còn thiếu',
    'Tối đa 1 vòng, còn budget',
    'Nguồn xung đột → nêu rõ'],True)
box(1650,1450,480,150,'Hỏi lại đúng một điểm',[
    'Chỉ hỏi khi thiếu ngữ cảnh',
    'Giữ các phần đã đủ dữ kiện'],True)
box(660,1550,870,115,'5. LLM tổng hợp từ kết luận được duyệt',[
    'Đủ các ý · trích dẫn từng phần · nêu phần chưa biết'],True)
box(660,1750,870,115,'Giao diện trả lời có nguồn kiểm chứng',[
    'Chỉ stream nội dung sau khi qua cổng kiểm chứng'])

box(70,1060,480,360,'GIÁ TRỊ NGƯỜI DÙNG THẤY',[
    'Một câu hỏi → xử lý đủ 3 ý',
    'Mỗi ý có nguồn riêng',
    'Thiếu học bổng → tìm lại',
    'Không hỏi lại toàn bộ câu',
    'Không tự suy ra số liệu',
    'Đo cải thiện trên câu trả lời'],True)
box(70,1530,480,335,'LƯU Ý TRIỂN KHAI',[
    'Câu đơn giản giữ luồng nhanh',
    'Thử trên câu nhiều ý trước',
    'Kiểm chứng có thể tăng TTFT',
    'Đo độ phủ ý / đúng trích dẫn',
    'Đặt budget trước khi mở rộng',
    'Không tự học từ chat thô'])
box(1650,1720,480,145,'Quan sát và đánh giá',[
    'Chất lượng · TTFT · chi phí',
    'Bộ câu hỏi có nhãn người duyệt'])

arrow([(1095,470),(1095,530)])
arrow([(550,622),(660,622)])
arrow([(1650,622),(1530,622)],dashed=True)
arrow([(1095,715),(1095,745),(795,745),(795,825)])
arrow([(1095,745),(1095,825)])
arrow([(1095,745),(1395,745),(1395,825)])
arrow([(795,970),(795,1010),(1095,1010),(1095,1060)])
arrow([(1095,970),(1095,1010)])
arrow([(1395,970),(1395,1010),(1095,1010)])
arrow([(1095,1210),(1095,1300)])
arrow([(1530,1365),(1590,1365),(1590,1150),(1650,1150)],'Thiếu nguồn',(1587,1270))
arrow([(1890,1060),(1890,900),(1530,900)])
arrow([(1530,1415),(1555,1415),(1555,1520),(1650,1520)])
arrow([(1095,1450),(1095,1550)],'Đủ / trả lời một phần có căn cứ',(1115,1482))
arrow([(1890,1600),(1890,1635),(1530,1635)])
arrow([(1095,1665),(1095,1750)])
arrow([(1530,1805),(1650,1805)],dashed=True)
text(70,1910,'JEV chọn quyết định; code giữ quyền thực thi. LLM lập kế hoạch / diễn đạt. Kiến trúc mới cần kiểm chứng thực nghiệm.',24,color=MUTED)
text(70,1945,'Cơ sở: pipeline.py · reranker.py · decision_engine/policies.py · Không giả định JEV có sẵn khả năng tự chạy công cụ.',22,color=MUTED)

svg.append('</svg>')
(OUT/'jev-2-dieu-phoi-co-kiem-chung.svg').write_text('\n'.join(svg),encoding='utf-8')
img.save(OUT/'jev-2-dieu-phoi-co-kiem-chung.png',dpi=(180,180))
img.resize((1100,990),Image.Resampling.LANCZOS).save(OUT/'jev-2-preview.png')
print('Exported proposal v2: PNG 2200x1980, SVG and preview.')
