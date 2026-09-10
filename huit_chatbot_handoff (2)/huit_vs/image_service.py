"""Free text-to-scene generation. No local inference, raw SVG, or raster blobs."""
import json
import os
import re
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, Field
from pymongo import MongoClient

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Coord = Annotated[int, Field(ge=0, le=1024)]


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: Coord
    y: Coord
    fill: Color


class Rect(Shape):
    type: Literal["rect"]
    width: Coord
    height: Coord


class Circle(Shape):
    type: Literal["circle"]
    radius: Annotated[int, Field(ge=1, le=512)]


class Text(Shape):
    type: Literal["text"]
    text: Annotated[str, Field(min_length=1, max_length=160)]
    size: Annotated[int, Field(ge=8, le=120)]


class Polygon(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["polygon"]
    fill: Color
    points: Annotated[list[Annotated[list[Coord], Field(min_length=2, max_length=2)]], Field(min_length=3, max_length=32)]


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    background: Color
    shapes: Annotated[list[Annotated[Union[Rect, Circle, Text, Polygon], Field(discriminator="type")]], Field(min_length=1, max_length=100)]


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=800)
    width: int = Field(default=512, ge=128, le=1024)
    height: int = Field(default=512, ge=128, le=1024)
    max_json_kb: int = Field(default=12, ge=2, le=24)
    style: Optional[str] = Field(default="photorealistic")
    backend: Literal["flux", "svg"] = Field(default="flux")


_mongo = None


def collection():
    # Separate from rag_core._init(): image requests never load an embedder.
    global _mongo
    if _mongo is None:
        import rag_core
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            password = os.environ.get("MONGODB_PASSWORD")
            if not password:
                raise RuntimeError("MongoDB chưa được cấu hình.")
            uri = f"mongodb+srv://{rag_core.USER}:{quote_plus(password)}@{rag_core.HOST}/?appName=Cluster0"
        _mongo = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, socketTimeoutMS=10000)
    import rag_core
    return _mongo[rag_core.DB]["generated_images"]


def translate_prompt_to_english(prompt: str) -> str:
    p = prompt.strip()
    p_lower = p.lower()

    p_clean = re.sub(
        r"^(?:tạo|vẽ|sinh|cho\s+(?:tôi|mình|em)?\s*(?:xem|xin)?)\s+(?:cho\s+(?:tôi|mình|em)?\s*)?(?:1\s+|một\s+)?(?:ảnh|hình|bức\s+ảnh|bức\s+hình)?\s*",
        "",
        p_lower,
        flags=re.I,
    ).strip()
    if not p_clean:
        p_clean = p_lower

    is_male = any(
        re.search(r"\b" + re.escape(w) + r"\b", p_clean)
        for w in [
            "chàng trai", "con trai", "nam giới", "đàn ông", "nam sinh",
            "bạn nam", "anh chàng", "trai đẹp", "soái ca", "chàng", "trai", "nam", "cậu bé"
        ]
    )
    is_female = any(
        re.search(r"\b" + re.escape(w) + r"\b", p_clean)
        for w in [
            "cô gái", "con gái", "nữ giới", "phụ nữ", "nữ sinh",
            "bạn nữ", "cô nàng", "thiếu nữ", "gái xinh", "hotgirl", "nàng", "gái", "nữ", "cô bé"
        ]
    )

    replacements = [
        # Trường HUIT & Khuôn viên học đường
        (r"\b(trường đại học công thương tphcm|trường đại học công thương|trường huit|đại học huit|đại học công thương|huit)\b", "modern HUIT University campus in Ho Chi Minh City, modern architecture, prestigious campus"),
        (r"\b(cổng trường)\b", "university main entrance gate, grand campus gateway"),
        (r"\b(khuôn viên trường|khuôn viên)\b", "spacious green university campus, academic pathways, trees"),
        (r"\b(sân trường)\b", "university courtyard schoolyard with students"),
        (r"\b(thư viện)\b", "bright modern academic university library with tall bookshelves and cozy study tables"),
        (r"\b(giảng đường|phòng học)\b", "modern university lecture hall classroom, amphitheater desks"),
        (r"\b(phòng thí nghiệm|phòng lab|phòng thực hành)\b", "high-tech science laboratory with glass equipment and scientific instruments"),
        (r"\b(phòng máy tính)\b", "modern university computer lab with glowing monitors"),
        (r"\b(hội trường)\b", "grand university auditorium hall with stage lights"),
        (r"\b(căng tin|căn tin|nhà ăn)\b", "vibrant cheerful university cafeteria"),
        (r"\b(kí túc xá|ký túc xá)\b", "modern university student dormitory building"),
        (r"\b(lễ tốt nghiệp|buổi lễ tốt nghiệp|tốt nghiệp đại học)\b", "joyful university graduation ceremony, commencement celebration, flying confetti"),
        (r"\b(kỷ yếu|kỉ yếu)\b", "graduation yearbook photo session, cherished memories"),

        # Con người & Quốc gia
        (r"\b(gái nhật|cô gái nhật|nữ sinh nhật|nữ sinh nhật bản)\b", "1 beautiful young Japanese woman, 1girl, attractive Japanese female student, expressive lovely eyes, natural beauty"),
        (r"\b(gái hàn|cô gái hàn|nữ sinh hàn|nữ sinh hàn quốc)\b", "1 beautiful young Korean woman, 1girl, attractive Korean female student, radiant natural beauty"),
        (r"\b(gái việt nam|gái việt|cô gái việt|nữ sinh việt)\b", "1 beautiful young Vietnamese woman, 1girl, charming Vietnamese female student, graceful gentle beauty"),
        (r"\b(gái trung quốc|gái trung|cô gái trung)\b", "1 beautiful young Chinese woman, 1girl, attractive Chinese female"),
        (r"\b(gái tây|cô gái tây)\b", "1 beautiful young Western woman, 1girl, attractive Caucasian female"),
        (r"\b(trai nhật|chàng trai nhật|nam sinh nhật)\b", "1 handsome young Japanese man, 1boy, handsome Japanese male"),
        (r"\b(trai hàn|chàng trai hàn|nam sinh hàn)\b", "1 handsome young Korean man, 1boy, handsome Korean male"),
        (r"\b(trai việt|chàng trai việt|nam sinh việt)\b", "1 handsome young Vietnamese man, 1boy, handsome Vietnamese male"),
        (r"\b(trai tây|chàng trai tây)\b", "1 handsome young Western Caucasian man, 1boy"),
        (r"\b(gái xinh|gái đẹp|hotgirl)\b", "1 gorgeous beautiful attractive young woman, 1girl, radiant smile"),
        (r"\b(cô gái|con gái|nữ sinh viên|nữ sinh|bạn nữ|cô nàng|thiếu nữ|nàng|gái|nữ)\b", "1 beautiful young woman, 1girl, charming Asian female, expressive lovely eyes, radiant gentle smile"),
        (r"\b(chàng trai|con trai|nam sinh viên|nam sinh|bạn nam|anh chàng|trai đẹp|soái ca|trai|nam)\b", "1 handsome young man, 1boy, handsome Asian male, masculine, styled short hair, attractive face"),
        (r"\b(đàn ông|nam giới)\b", "handsome mature Asian gentleman, masculine, refined"),
        (r"\b(phụ nữ|nữ giới)\b", "elegant beautiful Asian woman, graceful"),
        (r"\b(sinh viên đại học|sinh viên huit|sinh viên)\b", "Vietnamese university college students, cheerful youth"),
        (r"\b(thầy cô|giảng viên|thầy giáo|cô giáo)\b", "inspiring university professor, intellectual Asian educator"),
        (r"\b(bác bảo vệ)\b", "kind-hearted campus security guard in uniform"),
        (r"\b(nhóm bạn|bạn bè)\b", "group of happy Asian college friends enjoying student life"),
        (r"\b(nhật bản|nước nhật|nhật)\b", "Japan, Japanese aesthetic"),
        (r"\b(hàn quốc|nước hàn|hàn)\b", "Korea, Korean aesthetic"),
        (r"\b(việt nam|nước việt)\b", "Vietnam, Vietnamese aesthetic"),

        # Trang phục & Phụ kiện
        (r"\b(áo dài trắng|áo dài)\b", "traditional flowing white Vietnamese Ao Dai dress, graceful and elegant"),
        (r"\b(áo cử nhân|áo tốt nghiệp)\b", "black graduation gown robe with blue and red academic hood, mortarboard cap"),
        (r"\b(bằng tốt nghiệp|bằng cử nhân)\b", "holding an official diploma graduation certificate scroll"),
        (r"\b(áo sơ mi trắng)\b", "crisp neat white button-down collared shirt"),
        (r"\b(áo sơ mi)\b", "smart button-down shirt"),
        (r"\b(áo thun|áo phông)\b", "casual trendy t-shirt"),
        (r"\b(vest|com lê|bộ vest)\b", "tailored formal suit blazer"),
        (r"\b(áo blouse|áo lab|áo choàng trắng)\b", "professional white laboratory doctor coat blouse"),
        (r"\b(balo|ba lô|cặp sách)\b", "stylish student school backpack"),
        (r"\b(đeo kính|mắt kính|kính cận)\b", "wearing stylish clear eyeglasses"),

        # Hành động & Cử chỉ
        (r"\b(đang học bài|học bài|ôn thi)\b", "studying attentively with notebook and pen"),
        (r"\b(đọc sách)\b", "focused reading a book"),
        (r"\b(cầm sách|ôm sách)\b", "holding textbooks in arms"),
        (r"\b(dùng laptop|dùng máy tính|cầm laptop)\b", "working on modern ultra-thin laptop computer"),
        (r"\b(thuyết trình)\b", "giving a confident presentation with microphone"),
        (r"\b(mỉm cười|cười tươi|cười rạng rỡ)\b", "warm enchanting radiant smile, glowing happy expression"),
        (r"\b(vẫy tay)\b", "cheerfully waving hand to camera"),
        (r"\b(uống trà sữa|uống cafe|uống cà phê)\b", "enjoying delicious drink with cup"),

        # Hoa, thiên nhiên, thời tiết
        (r"\b(hoa hướng dương)\b", "vibrant blooming yellow sunflowers bouquet"),
        (r"\b(hoa phượng|hoa phượng vĩ|hoa phượng đỏ)\b", "iconic vibrant red royal poinciana summer flowers"),
        (r"\b(hoa sen)\b", "delicate serene pink sacred lotus flowers"),
        (r"\b(hoa cúc họa mi)\b", "fresh white daisy flowers bouquet"),
        (r"\b(bãi cỏ|đồng cỏ)\b", "lush green sunny university lawn grass"),
        (r"\b(công viên)\b", "scenic public park with green trees and flowers"),
        (r"\b(bầu trời xanh)\b", "bright sunny clear blue sky with fluffy white clouds"),
        (r"\b(hoàng hôn)\b", "spectacular sunset with warm golden hour cinematic glow"),
        (r"\b(bình minh)\b", "soft gentle early morning sunrise light"),
        (r"\b(trời mưa|cơn mưa)\b", "romantic gentle rain with glistening wet reflections"),
        (r"\b(ban đêm|buổi tối)\b", "enchanting night cityscape, sparkling bokeh lights"),

        # Động vật & Linh vật
        (r"\b(robot huit|mascot huit|linh vật huit)\b", "friendly cute 3D mascot robot of HUIT university, sleek futuristic blue and white AI assistant robot"),
        (r"\b(robot|người máy)\b", "futuristic sleek humanoid AI robot"),
        (r"\b(chó con shiba|shiba)\b", "adorable fluffy Shiba Inu dog"),
        (r"\b(chó con|chó cún|cún con|cún)\b", "adorable fluffy cute puppy dog"),
        (r"\b(chó)\b", "cute loyal dog"),
        (r"\b(mèo con|mèo)\b", "adorable fluffy cute kitten cat with big bright eyes"),
        (r"\b(hổ|cọp)\b", "majestic powerful tiger"),
        (r"\b(rồng)\b", "majestic fantasy dragon with glowing scales"),
        (r"\b(ngựa)\b", "majestic graceful horse"),
        (r"\b(chim)\b", "beautiful colorful songbird"),

        # Tính từ mô tả & Thẩm mỹ
        (r"\b(dễ thương|đáng yêu)\b", "extremely cute, adorable, charming"),
        (r"\b(đẹp trai|soái ca)\b", "handsome, charismatic, good-looking"),
        (r"\b(xinh đẹp|xinh gái|duyên dáng)\b", "gorgeous, beautiful, graceful"),
        (r"\b(ngầu|chất)\b", "cool, stylish, charismatic"),
        (r"\b(lung linh|rực rỡ)\b", "sparkling, radiant, breathtaking"),
        # Giới từ, vị trí & liên từ
        (r"\b(trước cổng trường)\b", "in front of the university main entrance gate"),
        (r"\b(trong thư viện)\b", "inside the university library"),
        (r"\b(trong phòng lab|trong phòng thí nghiệm)\b", "inside modern science laboratory"),
        (r"\b(trên sân trường)\b", "in the university schoolyard"),
        (r"\b(mặc áo|đang mặc áo|mặc|đang mặc)\b", "wearing"),
        (r"\b(cầm trên tay|đang cầm|cầm|ôm|đang ôm)\b", "holding"),
        (r"\b(ở|tại|trong)\b", "at"),
        (r"\b(trước|phía trước)\b", "in front of"),
        (r"\b(cùng|với)\b", "with"),
        (r"\b(và)\b", "and"),
        (r"\b(tương lai|hiện đại)\b", "high-tech, modern futuristic atmosphere"),
    ]

    translated = p_clean
    for pat, rep in replacements:
        translated = re.sub(pat, rep, translated, flags=re.I)

    if is_male and not any(k in translated.lower() for k in ["man", "boy", "male", "gentleman"]):
        translated = f"1 handsome young Asian man, 1boy, masculine, styled hair, {translated}"
    elif is_female and not any(k in translated.lower() for k in ["woman", "girl", "female", "lady"]):
        translated = f"1 beautiful young Asian woman, 1girl, lovely facial features, {translated}"

    if is_male or is_female or any(k in translated.lower() for k in ["student", "man", "woman", "person", "girl", "boy"]):
        translated = f"{translated}, highly detailed face, expressive eyes, natural skin texture, proportionate limbs and hands"

    return translated.strip(", ")


def extract_image_options(raw_text: str):
    """Trích xuất phong cách (style), kích thước (aspect ratio) và làm sạch prompt từ văn bản tự nhiên."""
    text = (raw_text or "").strip()
    style = "photorealistic"
    width, height = 512, 512

    # Nhận diện phong cách
    if re.search(r"\b(anime|manga|ghibli|shinkai|hoạt hình nhật)\b", text, re.I):
        style = "anime"
    elif re.search(r"\b(3d|pixar|unreal|chibi|mô hình 3d)\b", text, re.I):
        style = "3d"
    elif re.search(r"\b(sơn dầu|tranh vẽ|tranh sơn dầu|painting|màu nước|sơn mài)\b", text, re.I):
        style = "painting"
    elif re.search(r"\b(cyberpunk|khoa học viễn tưởng|sci-fi|neon|tương lai)\b", text, re.I):
        style = "cyberpunk"
    elif re.search(r"\b(điện ảnh|cinematic|phim|movie)\b", text, re.I):
        style = "cinematic"

    # Nhận diện tỷ lệ khung hình
    if re.search(r"\b(16:9|ngang|khung ngang|nằm ngang|phong cảnh|banner|wallpaper)\b", text, re.I):
        width, height = 768, 432
    elif re.search(r"\b(9:16|dọc|khung dọc|đứng|story|điện thoại|hình nền điện thoại)\b", text, re.I):
        width, height = 432, 768
    elif re.search(r"\b(hd|sắc nét|1024|chất lượng cao)\b", text, re.I):
        width, height = 768, 768

    cleaned_prompt = re.sub(r"\b(?:phong cách|kiểu|style)?\s*(?:anime|3d|tranh sơn dầu|sơn dầu|cyberpunk|điện ảnh|chân thực)\b", "", text, flags=re.I)
    cleaned_prompt = re.sub(r"\b(?:tỷ lệ|khung|kích thước)?\s*(?:16:9|9:16|1:1|ngang|dọc|hd)\b", "", cleaned_prompt, flags=re.I)
    cleaned_prompt = re.sub(r"\s+", " ", cleaned_prompt).strip()
    if not cleaned_prompt:
        cleaned_prompt = text

    return cleaned_prompt, style, width, height


def generate_flux_image(req):
    import urllib.request
    import urllib.parse
    import random
    import time

    raw_prompt = req.prompt.strip()
    translated_prompt = translate_prompt_to_english(raw_prompt)

    style_prompts = {
        "photorealistic": f"{translated_prompt}, photorealistic, 8k resolution, highly detailed, sharp focus, professional photography, natural lighting, studio quality, award winning masterpiece",
        "anime": f"{translated_prompt}, beautiful anime art style, studio ghibli, Makoto Shinkai aesthetic, vibrant colors, detailed anime illustration, expressive eyes, wallpaper masterpiece",
        "3d": f"{translated_prompt}, 3d render, octane render, unreal engine 5, volumetric soft lighting, masterpiece, clean 3d character model, Pixar style, ray tracing",
        "painting": f"{translated_prompt}, fine art painting, oil on canvas, digital masterpiece, rich vibrant colors, expressive brush strokes, dramatic artistic lighting",
        "cyberpunk": f"{translated_prompt}, futuristic cyberpunk aesthetic, neon cyan and magenta lights, high-tech sci-fi city atmosphere, volumetric fog, hyper-detailed, cinematic",
        "cinematic": f"{translated_prompt}, cinematic film still, 35mm photograph, dramatic atmospheric lighting, shallow depth of field, blockbuster movie scene, warm color grading, masterpiece"
    }
    style = getattr(req, "style", "photorealistic") or "photorealistic"
    enhanced_prompt = style_prompts.get(style, f"{translated_prompt}, highly detailed, high quality, 8k")

    seed = random.randint(1000, 9999999)
    encoded = urllib.parse.quote(enhanced_prompt)

    # Multi-model fallback: Thử FLUX chính -> nếu lỗi mạng thì thử FLUX-Realism (tuyệt đối không dùng model turbo vì tạo mặt biến dạng)
    models_to_try = ["flux", "flux-realism"]
    last_err = None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
    }

    for model_name in models_to_try:
        # Lưu ý: Tuyệt đối không thêm &safe=true vì bộ lọc Pollinations sẽ nhận diện nhầm ảnh chân dung thành phòng tối / hành lang song sắt
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={req.width}&height={req.height}&model={model_name}&nologo=true&seed={seed}"
        for attempt in range(2):
            try:
                req_obj = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req_obj, timeout=30) as res:
                    data = res.read()
                if data and len(data) >= 1000:
                    return data, "image/jpeg"
            except Exception as e:
                last_err = e
                time.sleep(0.5)
                continue

    raise ValueError(f"Không thể kết nối đến máy chủ vẽ ảnh sau các lượt thử: {last_err}")


def generate_scene(req):
    from openai import OpenAI
    key = os.environ.get("HUIT_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Cần API key OpenRouter hiện có để tạo ảnh miễn phí.")
    # Fixed free router; deliberately never use the paid fallbacks in RAG.
    with OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1", max_retries=0, timeout=40) as client:
        result = client.chat.completions.create(
            model="openrouter/free", max_tokens=6000, temperature=0.7,
            messages=[
                {"role": "system", "content": (
                    "Create a beautiful flat vector illustration matching the user's request. "
                    "Return ONLY JSON matching this schema, no markdown, no explanations. "
                    "Use a 1024x1024 coordinate space, rendered at the requested aspect ratio. "
                    "Use a cohesive palette, deliberate composition, readable short Vietnamese labels if needed. "
                    "No scripts, URLs, HTML or embedded images. "
                    f"Keep the compact UTF-8 scene JSON under {req.max_json_kb * 1024} bytes. "
                    + json.dumps(Scene.model_json_schema(), ensure_ascii=False)
                )},
                {"role": "user", "content": json.dumps({"prompt": req.prompt, "width": req.width, "height": req.height}, ensure_ascii=False)},
            ],
        )
    raw = result.choices[0].message.content or ""
    if len(raw.encode("utf-8")) > 100000:
        raise ValueError("AI response too large")
    raw = raw.strip()
    code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if code_match:
        raw_json = code_match.group(1).strip()
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw_json = raw[start:end+1].strip()
        else:
            raw_json = raw
    scene = Scene.model_validate_json(raw_json)
    size = len(scene.model_dump_json().encode("utf-8"))
    if size > req.max_json_kb * 1024:
        raise ValueError("Scene exceeds requested size")
    return scene, size


def create_image(req):
    if not req.prompt.strip():
        raise ValueError("Empty prompt")
    coll = collection()
    # Check storage before consuming the free API quota.
    coll.database.command("ping")

    if getattr(req, "backend", "flux") == "flux":
        image_bytes, ctype = generate_flux_image(req)
        image_id = secrets.token_hex(24)
        doc = {
            "_id": image_id,
            "version": 2,
            "prompt": req.prompt,
            "width": req.width,
            "height": req.height,
            "style": getattr(req, "style", "photorealistic"),
            "model": "flux",
            "content_type": ctype,
            "image_data": image_bytes,
            "image_bytes": len(image_bytes),
            "created_at": datetime.now(timezone.utc)
        }
        coll.insert_one(doc)
        return {
            "id": image_id,
            "url": f"/api/images/{image_id}/file",
            "svg_url": f"/api/images/{image_id}/svg",
            "json_url": f"/api/images/{image_id}",
            "image_bytes": len(image_bytes),
            "scene_bytes": len(image_bytes),
            "width": req.width,
            "height": req.height,
            "model": "FLUX.1-schnell",
            "billing": "free"
        }

    scene, size = generate_scene(req)
    image_id = secrets.token_hex(24)
    doc = {"_id": image_id, "version": 1, "prompt": req.prompt,
           "width": req.width, "height": req.height, "scene": scene.model_dump(),
           "scene_bytes": size, "max_json_kb": req.max_json_kb,
           "model": "openrouter/free", "created_at": datetime.now(timezone.utc)}
    coll.insert_one(doc)
    return {"id": image_id, "url": f"/api/images/{image_id}/svg",
            "json_url": f"/api/images/{image_id}", "scene_bytes": size,
            "width": req.width, "height": req.height, "billing": "free"}


def get_image(image_id):
    if not re.fullmatch(r"[0-9a-f]{48}", image_id):
        return None
    return collection().find_one({"_id": image_id})


def render_svg(doc):
    scene = Scene.model_validate(doc["scene"])
    width, height = int(doc["width"]), int(doc["height"])
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 1024 1024" preserveAspectRatio="none">',
             f'<rect width="1024" height="1024" fill="{scene.background}"/>']
    for s in scene.shapes:
        if isinstance(s, Rect):
            parts.append(f'<rect x="{s.x}" y="{s.y}" width="{s.width}" height="{s.height}" fill="{s.fill}"/>')
        elif isinstance(s, Circle):
            parts.append(f'<circle cx="{s.x}" cy="{s.y}" r="{s.radius}" fill="{s.fill}"/>')
        elif isinstance(s, Text):
            parts.append(f'<text x="{s.x}" y="{s.y}" font-family="sans-serif" font-size="{s.size}" fill="{s.fill}">{escape(s.text)}</text>')
        else:
            points = " ".join(f"{x},{y}" for x, y in s.points)
            parts.append(f'<polygon points="{points}" fill="{s.fill}"/>')
    return "".join(parts) + "</svg>"


def image_prompt(question):
    patterns = [
        r"^\s*(?:/anh\b|(?:tạo|sinh)\s+(?:ảnh|hình)(?:\s+ảnh)?)(?:\s*[:：]\s*|\s+)(.+)$",
        r"^\s*(?:vẽ|vẽ\s+giúp|vẽ\s+cho\s+(?:tôi|mình|em)?)(?:\s+(?:ảnh|hình\s*ảnh|hình))?(?:\s*[:：]\s*|\s+)(.+)$",
        r"^\s*(?:cho\s+(?:tôi|mình|em)?\s*(?:xem|xin)?\s*(?:ảnh|hình\s*ảnh|hình))\s*(?:[:：]\s*|\s+)(.+)$",
    ]
    for p in patterns:
        match = re.match(p, question, re.I | re.S)
        if match:
            return match.group(1).strip()
    return None
