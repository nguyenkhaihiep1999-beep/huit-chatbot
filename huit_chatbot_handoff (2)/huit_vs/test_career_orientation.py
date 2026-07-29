import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import rag_core

class CareerOrientationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PYTHONIOENCODING"] = "utf-8"
        rag_core._init()

    def test_fashion_design_dress_question(self):
        q = "toi muon hoc thiet ke vay nen hoc ngnah nao?"
        res = rag_core.answer(q, use_cache=False)
        answer_text = res.get("answer", "")
        sources = res.get("sources", [])
        
        # Verify it doesn't return fallback error
        self.assertNotIn("Không tìm thấy dữ liệu liên quan", answer_text)
        
        # Check that fashion / garment majors are recommended
        has_fashion_keywords = any(
            kw in answer_text.lower()
            for kw in ["công nghệ dệt, may", "dệt, may", "thời trang", "7540204", "7340123"]
        )
        self.assertTrue(has_fashion_keywords, f"Answer should mention fashion/garment majors: {answer_text}")

    def test_cutoff_pronoun_question(self):
        q = "diem nay nam bao nhieu"
        res = rag_core.answer(q, use_cache=False)
        answer_text = res.get("answer", "")
        self.assertNotIn("Không tìm thấy dữ liệu liên quan", answer_text)
        self.assertTrue(any(kw in answer_text for kw in ["16", "20", "600", "720", "Điểm sàn"]))

    def test_cosmetics_question(self):
        q = "em thích làm về mỹ phẩm thì học ngành nào tại HUIT"
        res = rag_core.answer(q, use_cache=False)
        answer_text = res.get("answer", "")
        self.assertNotIn("Không tìm thấy dữ liệu liên quan", answer_text)
        self.assertTrue(any(kw in answer_text.lower() for kw in ["hóa học", "hóa mỹ phẩm", "7510401"]))

    def test_cooking_question(self):
        q = "thích nấu ăn và làm bếp thì chọn ngành gì"
        res = rag_core.answer(q, use_cache=False)
        answer_text = res.get("answer", "")
        self.assertNotIn("Không tìm thấy dữ liệu liên quan", answer_text)
        self.assertTrue(any(kw in answer_text.lower() for kw in ["chế biến món ăn", "ăn uống", "7810202"]))

    def test_female_students_career_advice(self):
        q = "con gái nên học ngành nào ở HUIT"
        res = rag_core.answer(q, use_cache=False)
        answer_text = res.get("answer", "")
        self.assertNotIn("Không tìm thấy dữ liệu liên quan", answer_text)
        self.assertTrue(len(answer_text) > 100)

if __name__ == "__main__":
    unittest.main()
