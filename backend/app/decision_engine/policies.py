"""
policies.py
Chính sách định nghĩa câu hỏi và rubric đánh giá cho Decision Engine.
Bao gồm 2 workflow thử nghiệm:
1. Intent Decision (Phân loại ý định kèm needs_clarification)
2. Evidence Sufficiency (Đánh giá tính đầy đủ của minh chứng)
"""
from typing import Dict
from backend.app.decision_engine.contracts import QuestionDefinition

INTENT_CHOICES = {
    "admission_procedure": "Thủ tục nhập học, thời gian nộp hồ sơ nhập học, xác nhận nhập học, rút học phí, sinh hoạt đầu khóa.",
    "cutoff": "Điểm chuẩn trúng tuyển chính thức 2026, điểm trúng tuyển các năm, điểm xét trúng tuyển.",
    "floor_score": "Điểm sàn nhận hồ sơ xét tuyển, ngưỡng đảm bảo chất lượng đầu vào của các phương thức.",
    "tuition": "Học phí theo tín chỉ, mức thu học phí mỗi kỳ, chi phí học tập của từng ngành.",
    "scholarship": "Chính sách học bổng, miễn giảm học phí, học bổng đầu vào, học bổng khuyến khích học tập.",
    "admission": "Phương thức xét tuyển (học bạ THPT, điểm thi tốt nghiệp, ĐGNL), chỉ tiêu, đợt xét tuyển bổ sung.",
    "career": "Tư vấn chọn ngành nghề, định hướng nghề nghiệp, sở thích, cơ hội việc làm sau tốt nghiệp.",
    "major": "Mã ngành tuyển sinh, tên ngành, tổ hợp môn xét tuyển cụ thể của từng ngành.",
    "contact": "Địa chỉ các cơ sở đào tạo, hotline phòng tuyển sinh, thông tin liên hệ hỗ trợ.",
    "general": "Chào hỏi tổng quát, giới thiệu chung về trường HUIT hoặc ý định tuyển sinh cơ bản.",
    "out_of_scope": "Câu hỏi hoàn toàn nằm ngoài phạm vi tuyển sinh, đào tạo và hoạt động của trường HUIT.",
}

SUFFICIENCY_CHOICES = {
    "sufficient": "Các tài liệu minh chứng chứa đầy đủ dữ kiện chính thức, đáng tin cậy để trả lời trọn vẹn câu hỏi.",
    "partial": "Minh chứng có thông tin liên quan nhưng chỉ giải quyết được một phần câu hỏi, còn thiếu một số chi tiết quan trọng.",
    "insufficient": "Minh chứng không chứa dữ liệu liên quan hoặc không đủ căn cứ chính thức để trả lời câu hỏi.",
    "conflicting": "Minh chứng chứa thông tin hoặc số liệu mâu thuẫn nhau, không thể đưa ra kết luận chắc chắn.",
}


def get_intent_decision_questions() -> Dict[str, QuestionDefinition]:
    """Tạo bộ câu hỏi đánh giá Intent cho System One của Jev."""
    return {
        "intent": QuestionDefinition(
            type="choice",
            instructions=(
                "Phân tích câu hỏi tuyển sinh HUIT và chọn đúng 1 danh mục ý định phù hợp nhất. "
                "Tuyệt đối tuân thủ tiêu chí của từng lựa chọn."
            ),
            criteria=INTENT_CHOICES,
        ),
        "needs_clarification": QuestionDefinition(
            type="noul",
            instructions=(
                "Câu hỏi có bị mơ hồ, thiếu thông tin quan trọng (ví dụ chưa nêu rõ ngành học hoặc năm xét tuyển) "
                "đến mức cần yêu cầu người dùng làm rõ thêm không?"
            ),
        ),
    }


def get_evidence_sufficiency_questions() -> Dict[str, QuestionDefinition]:
    """Tạo bộ câu hỏi đánh giá Tính đầy đủ của minh chứng (Evidence Sufficiency)."""
    return {
        "sufficiency": QuestionDefinition(
            type="choice",
            instructions=(
                "Đánh giá xem các đoạn trích minh chứng tuyển sinh HUIT đã lấy về có đủ thông tin "
                "chính xác để trả lời câu hỏi của thí sinh hay không."
            ),
            criteria=SUFFICIENCY_CHOICES,
        ),
        "needs_clarification": QuestionDefinition(
            type="noul",
            instructions=(
                "Nếu minh chứng không đủ hoặc mâu thuẫn, có cần hỏi lại người dùng để làm rõ câu hỏi không?"
            ),
        ),
    }
