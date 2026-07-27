import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_core


class RagCoreUnitTests(unittest.TestCase):
    def test_intent_classification_priority(self):
        self.assertEqual(
            rag_core.classify_intent("Học bổng giảm 50% học phí"),
            "scholarship",
        )
        self.assertEqual(
            rag_core.classify_intent("Học phí một học kỳ"),
            "tuition",
        )
        self.assertEqual(
            rag_core.classify_intent("Điểm sàn xét tuyển năm 2025"),
            "cutoff",
        )
        self.assertEqual(
            rag_core.classify_intent("Thông tin ngành Logistics"),
            "major",
        )

    def test_metadata_prefers_major_title(self):
        metadata = rag_core.infer_metadata({
            "title": "Ngành Trí tuệ nhân tạo (Mã ngành: 7480107)",
            "text": "Học phí tham khảo và điểm sàn năm 2025",
        })
        self.assertEqual(metadata["category"], "major")
        self.assertEqual(metadata["major_code"], "7480107")
        self.assertEqual(metadata["year"], 2025)

    def test_cache_key_changes_with_context_and_version(self):
        first = rag_core._cache_key("Mã ngành?", [])
        second = rag_core._cache_key(
            "Mã ngành?",
            [{"role": "user", "content": "Ngành AI"}],
        )
        self.assertNotEqual(first, second)

    def test_fallback_filters_percentage_as_cutoff(self):
        answer = rag_core._fallback_answer(
            "Điểm sàn HUIT năm 2025?",
            [{
                "text": (
                    "Điểm sàn xét tuyển THPT 2025: 16.00. "
                    "Học bổng giảm 60% học phí."
                )
            }],
        )
        self.assertIn("16", answer)
        self.assertNotIn("60 điểm", answer)

    def test_tuition_fallback_is_concise(self):
        answer = rag_core._fallback_answer("Học phí HUIT?", [{}])
        self.assertIn("1.100.000", answer)
        self.assertIn("1.350.000", answer)
        self.assertLess(len(answer), 550)

    def test_query_alias_expansion(self):
        self.assertIn(
            "an toàn thông tin",
            rag_core.expand_query("Tra cứu ngành ATTT của HUIT"),
        )
        self.assertIn(
            "marketing",
            rag_core.expand_query("Ngành tiếp thị của HUIT"),
        )

    def test_out_of_scope_guardrail_is_broad(self):
        for question in [
            "Ai là tổng thống Hoa Kỳ?",
            "Giá Bitcoin hôm nay?",
            "Viết JavaScript tạo máy tính",
            "Cách nấu phở bò?",
        ]:
            self.assertTrue(rag_core.check_intent_guardrail(question)["is_handled"])
        self.assertFalse(
            rag_core.check_intent_guardrail(
                "Mã ngành Công nghệ thông tin HUIT?"
            )["is_handled"]
        )


if __name__ == "__main__":
    unittest.main()
