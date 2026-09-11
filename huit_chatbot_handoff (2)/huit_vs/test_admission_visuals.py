#!/usr/bin/env python3
"""Unit tests for HUIT Admission Visuals (Visual JSON, Fast Upscaling, API Endpoints)."""
import os
import sys
import time
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
import api
import admission_visuals_service as avs


class AdmissionVisualsTests(unittest.TestCase):
    def setUp(self):
        api._request_windows.clear()
        self.client = TestClient(api.app)

    def test_get_visual_by_id(self):
        v = avs.get_visual_by_id("major_7480201")
        self.assertIsNotNone(v)
        self.assertEqual(v.get("major_code"), "7480201")
        self.assertIn("THÔNG TIN", v.get("title", ""))

    def test_find_visual_by_context(self):
        # 1. By major keyword
        v_cntt = avs.find_visual_by_context("major", "Tổ hợp xét tuyển ngành công nghệ thông tin?")
        self.assertIsNotNone(v_cntt)
        self.assertEqual(v_cntt.get("major_code"), "7480201")

        # 2. By AI major code
        v_ai = avs.find_visual_by_context("major", "Ngành 7480107 có những môn nào?")
        self.assertIsNotNone(v_ai)
        self.assertEqual(v_ai.get("major_code"), "7480107")

        # 3. By Cutoff intent
        v_cutoff = avs.find_visual_by_context("cutoff", "Điểm sàn năm 2026 của trường?")
        self.assertIsNotNone(v_cutoff)
        self.assertEqual(v_cutoff.get("visual_id"), "table_cutoff_2026")

        # 4. By Tuition intent
        v_tuition = avs.find_visual_by_context("tuition", "Học phí một tín chỉ là bao nhiêu?")
        self.assertIsNotNone(v_tuition)
        self.assertEqual(v_tuition.get("visual_id"), "table_tuition_2026")

        # 5. By Admission roadmap intent
        v_road = avs.find_visual_by_context("admission", "Phương thức xét tuyển năm 2026?")
        self.assertIsNotNone(v_road)
        self.assertEqual(v_road.get("visual_id"), "roadmap_admissions_2026")

    def test_svg_rendering_and_upscaling(self):
        v = avs.get_visual_by_id("major_7480201")
        self.assertIsNotNone(v)
        
        # 1x scale
        t0 = time.perf_counter()
        svg_1x = avs.render_svg_visual(v, scale=1)
        dt_1x = (time.perf_counter() - t0) * 1000
        self.assertTrue(svg_1x.startswith("<svg"))
        self.assertIn("viewBox=\"0 0 760 480\"", svg_1x)
        self.assertIn("width=\"760\"", svg_1x)
        self.assertLess(dt_1x, 50.0)  # Must render in < 50ms

        # 2x upscale
        svg_2x = avs.render_svg_visual(v, scale=2)
        self.assertIn("width=\"1520\"", svg_2x)
        self.assertIn("height=\"960\"", svg_2x)

        # 4x upscale (Retina / 4K)
        svg_4x = avs.render_svg_visual(v, scale=4)
        self.assertIn("width=\"3040\"", svg_4x)
        self.assertIn("height=\"1920\"", svg_4x)

    def test_png_fallback_rendering(self):
        v = avs.get_visual_by_id("table_cutoff_2026")
        self.assertIsNotNone(v)
        png_bytes = avs.render_png_visual_fallback(v, scale=2)
        self.assertIsInstance(png_bytes, bytes)
        self.assertTrue(len(png_bytes) > 500)
        self.assertEqual(png_bytes[:8], b"\x89PNG\r\n\x1a\n")

    def test_api_endpoints(self):
        # 1. JSON endpoint
        res_json = self.client.get("/api/admission-visuals/major_7480201")
        self.assertEqual(res_json.status_code, 200)
        data = res_json.json()
        self.assertEqual(data["major_code"], "7480201")

        # 2. SVG Render endpoint
        res_svg = self.client.get("/api/admission-visuals/major_7480201/render?scale=2")
        self.assertEqual(res_svg.status_code, 200)
        self.assertIn("image/svg+xml", res_svg.headers.get("content-type", ""))
        self.assertIn("<svg", res_svg.text)

        # 3. PNG Render endpoint
        res_png = self.client.get("/api/admission-visuals/major_7480201/render?format=png&scale=2")
        self.assertEqual(res_png.status_code, 200)
        self.assertIn("image/png", res_png.headers.get("content-type", ""))
        self.assertEqual(res_png.content[:8], b"\x89PNG\r\n\x1a\n")

        # 4. 404 for unknown visual
        res_404 = self.client.get("/api/admission-visuals/unknown_9999999")
        self.assertEqual(res_404.status_code, 404)


if __name__ == "__main__":
    unittest.main()
