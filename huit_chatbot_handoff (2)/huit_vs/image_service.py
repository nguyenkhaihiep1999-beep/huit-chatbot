"""Free text-to-scene generation. No local inference, raw SVG, or raster blobs."""
import json
import os
import re
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Annotated, Literal, Union
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
