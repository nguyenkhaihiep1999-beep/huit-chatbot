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
        (r"\b(chàng trai|con trai|nam sinh|bạn nam|anh chàng|trai đẹp|soái ca)\b", "1 handsome young man, 1boy, handsome Asian male, masculine, short hair"),
        (r"\b(đàn ông|nam giới)\b", "handsome mature Asian man, masculine"),
        (r"\b(cô gái|con gái|nữ sinh|bạn nữ|cô nàng|thiếu nữ|gái xinh|hotgirl)\b", "1 beautiful young woman, 1girl, attractive Asian female"),
        (r"\b(phụ nữ|nữ giới)\b", "elegant beautiful Asian woman"),
        (r"\b(chó con|chó cún|cún con|cún)\b", "adorable fluffy cute puppy dog"),
        (r"\b(chó)\b", "cute dog"),
        (r"\b(mèo con|mèo)\b", "adorable fluffy cute kitten cat"),
        (r"\b(hổ|cọp)\b", "majestic tiger"),
        (r"\b(rồng)\b", "majestic fantasy dragon"),
        (r"\b(ngựa)\b", "majestic horse"),
        (r"\b(chim)\b", "beautiful colorful bird"),
        (r"\b(áo dài)\b", "traditional Vietnamese Ao Dai dress"),
        (r"\b(áo sơ mi trắng)\b", "crisp white button-down shirt"),
        (r"\b(áo sơ mi)\b", "button-down shirt"),
        (r"\b(áo thun|áo phông)\b", "casual t-shirt"),
        (r"\b(vest|com lê)\b", "tailored formal suit"),
        (r"\b(đeo kính|mắt kính)\b", "wearing stylish eyeglasses"),
        (r"\b(dễ thương|đáng yêu)\b", "cute, adorable"),
        (r"\b(đẹp trai)\b", "handsome, good-looking"),
        (r"\b(xinh đẹp|xinh gái)\b", "gorgeous, beautiful"),
        (r"\b(ngầu)\b", "cool, charismatic"),
        (r"\b(trường đại học công thương|trường huit|huit)\b", "modern university campus, HUIT university in Vietnam"),
        (r"\b(trường học|trường đại học|khuôn viên)\b", "modern university campus, academic setting"),
        (r"\b(bãi cỏ|đồng cỏ)\b", "green sunny meadow grass"),
        (r"\b(công viên)\b", "city park with lush green trees and flowers"),
        (r"\b(quán cà phê|quán cafe)\b", "cozy modern cafe coffee shop"),
        (r"\b(đường phố|phố)\b", "vibrant city street"),
        (r"\b(hoàng hôn)\b", "golden hour sunset glow"),
        (r"\b(bình minh)\b", "soft morning sunrise light"),
        (r"\b(ban đêm)\b", "night scene, cinematic city lights"),
        (r"\b(robot|người máy)\b", "futuristic sleek humanoid AI robot"),
    ]

    translated = p_clean
    for pat, rep in replacements:
        translated = re.sub(pat, rep, translated, flags=re.I)

    if is_male and not any(k in translated.lower() for k in ["man", "boy", "male"]):
        translated = f"1 handsome young man, 1boy, handsome Asian male, masculine, {translated}"
    elif is_female and not any(k in translated.lower() for k in ["woman", "girl", "female"]):
        translated = f"1 beautiful young woman, 1girl, attractive Asian female, {translated}"

    return translated.strip(", ")


def generate_flux_image(req):
    import urllib.request
    import urllib.parse
    import random
    raw_prompt = req.prompt.strip()
    translated_prompt = translate_prompt_to_english(raw_prompt)
    style_prompts = {
        "photorealistic": f"{translated_prompt}, photorealistic, 8k resolution, highly detailed, sharp focus, professional photography, realistic lighting",
        "3d": f"{translated_prompt}, 3d render, octane render, unreal engine 5, volumetric lighting, masterpiece, clean 3d model",
        "anime": f"{translated_prompt}, beautiful anime art style, studio ghibli, Makoto Shinkai, vibrant colors, detailed illustration",
        "painting": f"{translated_prompt}, fine art painting, oil on canvas, digital masterpiece, rich vibrant colors, expressive strokes"
    }
    style = getattr(req, "style", "photorealistic") or "photorealistic"
    enhanced_prompt = style_prompts.get(style, translated_prompt)
    seed = random.randint(1000, 9999999)
    encoded = urllib.parse.quote(enhanced_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={req.width}&height={req.height}&model=flux&nologo=true&seed={seed}"
    req_obj = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HUIT-Chatbot/2.0)"})
    with urllib.request.urlopen(req_obj, timeout=40) as res:
        data = res.read()
    if not data or len(data) < 1000:
        raise ValueError("Dữ liệu ảnh nhận được từ mô hình FLUX không hợp lệ.")
    return data, "image/jpeg"


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
