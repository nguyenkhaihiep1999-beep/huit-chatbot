import json
import os
import unittest
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from pydantic import ValidationError
import api
import image_service as images


SCENE = {"background": "#ffffff", "shapes": [{"type": "text", "x": 50, "y": 70,
         "fill": "#112233", "text": '<script>alert("x")</script>', "size": 30}]}


class ImageTests(unittest.TestCase):
    def setUp(self):
        api._request_windows.clear()
        self.client = TestClient(api.app)

    def test_rejects_executable_shapes_colors_and_extra_fields(self):
        for shape in [{"type": "script"}, {**SCENE["shapes"][0], "onclick": "alert(1)"},
                      {**SCENE["shapes"][0], "fill": "url(https://evil.test)"}]:
            with self.assertRaises(ValidationError):
                images.Scene.model_validate({"background": "#ffffff", "shapes": [shape]})

    def test_svg_escapes_text(self):
        svg = images.render_svg({"scene": SCENE, "width": 512, "height": 512})
        root = ElementTree.fromstring(svg)
        self.assertNotIn("<script>", svg)
        self.assertEqual(root[-1].text, SCENE["shapes"][0]["text"])

    def test_free_router_only_and_budget_enforced(self):
        with patch.dict(os.environ, {"HUIT_OPENROUTER_KEY": "test", "OPENROUTER_MODEL": "paid/model"}), patch("openai.OpenAI") as factory:
            client = factory.return_value.__enter__.return_value
            client.chat.completions.create.return_value.choices[0].message.content = json.dumps(SCENE)
            images.generate_scene(images.ImageRequest(prompt="mèo"))
            self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "openrouter/free")
            huge = {"background": "#ffffff", "shapes": [SCENE["shapes"][0]] * 50}
            client.chat.completions.create.return_value.choices[0].message.content = json.dumps(huge)
            with self.assertRaises(ValueError):
                images.generate_scene(images.ImageRequest(prompt="mèo", max_json_kb=2))

    def test_mongo_roundtrip_and_svg_download(self):
        coll = MagicMock()
        stored = {}
        coll.insert_one.side_effect = lambda doc: stored.update(doc)
        coll.find_one.side_effect = lambda query: dict(stored) if query["_id"] == stored.get("_id") else None
        scene = images.Scene.model_validate(SCENE)
        with patch.object(images, "collection", return_value=coll), patch.object(images, "generate_scene", return_value=(scene, 200)), patch.object(api.rag_core, "_init", side_effect=AssertionError("must not load embedder")):
            response = self.client.post("/api/images", json={"prompt": "mèo", "width": 768, "max_json_kb": 4})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(self.client.get(result["json_url"]).json()["scene"], SCENE)
            svg = self.client.get(result["url"] + "?download=true")
            self.assertEqual(svg.status_code, 200)
            self.assertIn("attachment", svg.headers["content-disposition"])
            self.assertIn("sandbox", svg.headers["content-security-policy"])
            self.assertEqual(stored["width"], 768)

    def test_failure_does_not_save_and_hides_secrets(self):
        coll = MagicMock()
        with patch.object(images, "collection", return_value=coll), patch.object(images, "generate_scene", side_effect=RuntimeError("secret-key")):
            response = self.client.post("/api/images", json={"prompt": "mèo"})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret-key", response.text)
            coll.insert_one.assert_not_called()

    def test_chat_routes_bypass_rag(self):
        result = {"id": "a" * 48, "url": "/api/images/" + "a" * 48 + "/svg", "json_url": "/api/images/" + "a" * 48, "scene_bytes": 100}
        with patch.object(images, "create_image", return_value=result), patch.object(api.rag_core, "answer", side_effect=AssertionError), patch.object(api.rag_core, "stream_answer", side_effect=AssertionError):
            for path in ["/api/chat", "/api/chat-stream"]:
                response = self.client.post(path, json={"question": "Tạo ảnh: mèo"})
                self.assertEqual(response.status_code, 200)
                self.assertIn("/svg", response.text)
            self.assertEqual(self.client.get("/api/chat-stream", params={"question": "/anh mèo"}).status_code, 200)

    def test_invalid_limits_missing_image_and_rate_limit(self):
        self.assertEqual(self.client.post("/api/images", json={"prompt": "mèo", "max_json_kb": 25}).status_code, 422)
        self.assertEqual(self.client.get("/api/images/invalid").status_code, 404)
        with patch.object(images, "get_image", return_value=None):
            self.assertEqual(self.client.get("/api/images/" + "a" * 48 + "/svg").status_code, 404)
        with patch.object(api, "RATE_LIMIT_PER_MINUTE", 0):
            self.assertEqual(self.client.post("/api/images", json={"prompt": "mèo"}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
