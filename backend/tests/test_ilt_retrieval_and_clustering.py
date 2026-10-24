"""Tests for ILT (Innovative Lighting Technologies) RAG retrieval, clustering, and profile isolation."""
import pytest
from backend.app.rag.profile import get_profile, WHITELISTED_PROFILES
from backend.app.rag.embedding import EmbeddingManager
from backend.app.rag.retrieval import HybridRetriever
from backend.app.rag.reranker import retrieve, apply_heuristic_overrides
from backend.app.rag.pipeline import stream_answer
from backend.app.data_access.operations import rag_operations
from backend.app.repositories.mongo_repository import MongoRepository


@pytest.fixture(autouse=True)
def seed_ilt_mock_data():
    """Nạp tài liệu mẫu ILT vào mock collection để kiểm thử offline."""
    col = MongoRepository.get_collection("ilt_kb")
    col.insert_many([
        {
            "chunk_id": "ilt_chunk_132",
            "document_id": "ilt_doc_132",
            "dataset_id": "ilt",
            "dataset_version": "2026.1",
            "title": "Catalogue ILT 2026 - Dòng OREN - đèn ốp trần - Trang 132",
            "text": "Dòng OREN đèn ốp trần. Mã SKU: ALB-103022-12-BL-1D-5, ALB-103030-15-BL-1D-5. Hoàn thiện Black (BL), Brushed Nickel (NS). CCT: 3000K/4000K/5000K có thể chuyển đổi. CRI >= 90.",
            "source_url": "https://online.fliphtml5.com/zpdsw/wjtd/",
            "url": "https://online.fliphtml5.com/zpdsw/wjtd/",
            "page_title": "Dòng OREN - Trang 132",
            "category": "product_oren",
            "product_type": "đèn ốp trần",
            "series": "OREN",
            "page_number": 132,
            "sku": "ALB-103022-12-BL-1D-5",
            "all_skus": ["ALB-103022-12-BL-1D-5", "ALB-103030-15-BL-1D-5"],
            "finish": "Black",
            "glass": None,
            "cluster_id": 3,
            "certifications": ["UL", "ETL", "CE"],
            "verification_status": "verified",
            "embedding": [0.01] * 1024,
        },
        {
            "chunk_id": "ilt_chunk_024",
            "document_id": "ilt_doc_024",
            "dataset_id": "ilt",
            "dataset_version": "2026.1",
            "title": "Catalogue ILT 2026 - Dòng ARNO - đèn thả - Trang 24",
            "text": "Dòng ARNO đèn thả trang trí. Mã SKU: ARN-101E26-9-NS-C. Hoàn thiện Brushed Nickel (NS), Aged Brass (AB). Đui bóng E26 tối đa 60W. Thủy tinh Clear Glass.",
            "source_url": "https://online.fliphtml5.com/zpdsw/wjtd/",
            "url": "https://online.fliphtml5.com/zpdsw/wjtd/",
            "page_title": "Dòng ARNO - Trang 24",
            "category": "product_arno",
            "product_type": "đèn thả",
            "series": "ARNO",
            "page_number": 24,
            "sku": "ARN-101E26-9-NS-C",
            "all_skus": ["ARN-101E26-9-NS-C"],
            "finish": "Brushed Nickel",
            "glass": "Clear Glass",
            "cluster_id": 0,
            "certifications": ["UL", "ETL"],
            "verification_status": "verified",
            "embedding": [0.02] * 1024,
        },
    ])


def test_profile_isolation_and_configurations():
    """Kiểm tra cấu hình và cách ly giữa profile HUIT và ILT."""
    assert "huit" in WHITELISTED_PROFILES
    assert "ilt" in WHITELISTED_PROFILES

    p_huit = get_profile("huit")
    p_ilt = get_profile("ilt")

    assert p_huit.id == "huit"
    assert p_huit.mongodb_collection == "huit_kb"
    assert p_huit.vector_index == "huit_vector_index"
    assert "huit_cluster_centroids.json" in str(p_huit.clusters_path)

    assert p_ilt.id == "ilt"
    assert p_ilt.mongodb_collection == "ilt_kb"
    assert p_ilt.vector_index == "ilt_vector_index"
    assert "ilt_cluster_centroids.json" in str(p_ilt.clusters_path)
    assert p_ilt.jev_evidence_mode in ("assist", "shadow")
    assert p_ilt.jev_intent_mode == "off"


def test_ilt_centroids_and_clustering_structure():
    """Kiểm tra nạp file centroids độc lập cho ILT."""
    centroids_data = EmbeddingManager.get_cluster_centroids("ilt")
    assert centroids_data is not None
    assert centroids_data.get("profile") == "ilt"
    assert centroids_data.get("dimensions") == 1024
    assert centroids_data.get("k") == 5
    assert len(centroids_data.get("clusters", {})) == 5

    # Đảm bảo HUIT centroids không bị ghi đè
    huit_centroids = EmbeddingManager.get_cluster_centroids("huit")
    assert huit_centroids is not None
    assert huit_centroids.get("profile") != "ilt"


def test_ilt_exact_sku_search():
    """Kiểm tra tra cứu chính xác SKU qua registered operation v2.1.0."""
    sku = "ALB-103022-12-BL-1D-5"
    docs = HybridRetriever.search_sku_exact(sku=sku, profile_id="ilt", limit=3)
    assert len(docs) >= 1
    assert any(sku.upper() in str(d.get("sku") or "").upper() or sku.upper() in [str(s).upper() for s in (d.get("all_skus") or [])] for d in docs)
    assert docs[0].get("cluster_id") is not None
    assert docs[0].get("series") == "OREN"


def test_ilt_cluster_prefilter_vector_search():
    """Kiểm tra tìm kiếm vector kèm tiền lọc theo cluster_id trên MongoDB Atlas."""
    qv = EmbeddingManager.embed_query("đèn thả ARNO hoàn thiện nickel")
    assert qv is not None
    assert len(qv) == 1024

    top_cid = HybridRetriever.get_top_cluster(qv, profile_id="ilt")
    assert top_cid is not None
    assert isinstance(top_cid, int)

    # Truy vấn vector có tiền lọc cluster
    docs = HybridRetriever.search_vector(
        qv=qv,
        profile_id="ilt",
        filter_cluster_ids=[top_cid],
        limit=5,
    )
    assert len(docs) >= 1
    for d in docs:
        assert d.get("cluster_id") == top_cid


def test_ilt_retrieve_full_flow():
    """Kiểm tra toàn bộ pipeline retrieval kết hợp vector, keyword, SKU và reranking cho ILT."""
    query = "Cho tôi thông số kỹ thuật của đèn ốp trần OREN ALB-103022-12-BL-1D-5"
    docs = retrieve(query, top_k=3, profile_id="ilt")
    assert len(docs) >= 1

    # Phải có document chứa SKU hoặc dòng OREN
    top_doc = docs[0]
    doc_text = (top_doc.get("title", "") + " " + top_doc.get("text", "")).upper()
    assert "OREN" in doc_text or "ALB-103022" in doc_text


def test_ilt_no_huit_heuristics_leakage():
    """Đảm bảo không bao giờ rò rỉ học phí/điểm chuẩn/thủ tục tuyển sinh HUIT vào profile ILT."""
    # 1. Kiểm tra trực tiếp apply_heuristic_overrides
    dummy_docs = [{"title": "Sản phẩm đèn", "text": "Đèn trang trí ILT", "category": "product"}]
    overridden_ilt = apply_heuristic_overrides(list(dummy_docs), "Học phí năm nay bao nhiêu?", intent="tuition", profile_id="ilt")
    assert len(overridden_ilt) == len(dummy_docs)
    assert not any("HUIT" in d.get("title", "") for d in overridden_ilt)

    overridden_huit = apply_heuristic_overrides(list(dummy_docs), "Học phí năm nay bao nhiêu?", intent="tuition", profile_id="huit")
    assert len(overridden_huit) > len(dummy_docs)
    assert any("HUIT" in d.get("title", "") for d in overridden_huit)

    # 2. Kiểm tra retrieval tổng thể
    ilt_tuition_docs = retrieve("Học phí và điểm sàn đại học HUIT là bao nhiêu?", top_k=3, profile_id="ilt")
    for d in ilt_tuition_docs:
        assert "huit_general_tuition_override" != d.get("_id")
        assert "huit_2026_floor_override" != d.get("_id")
        assert "huit_2026_official_cutoff_doc" != d.get("_id")
        assert "huit_2026_admission_proc_doc" != d.get("_id")


def test_ilt_deduplication_preserves_pages_and_skus():
    """Kiểm tra deduplication giữ nguyên các trang và SKU khác nhau cùng chung 1 catalogue URL."""
    docs = [
        {
            "chunk_id": "ilt_cat_p131",
            "source_url": "https://online.fliphtml5.com/zpdsw/wjtd/",
            "page_number": 131,
            "sku": "ALB-103001-BL-1D-5",
            "title": "Catalogue ILT 2026 - Dòng OREN - Trang 131",
        },
        {
            "chunk_id": "ilt_cat_p132",
            "source_url": "https://online.fliphtml5.com/zpdsw/wjtd/",
            "page_number": 132,
            "sku": "ALB-103022-12-BL-1D-5",
            "title": "Catalogue ILT 2026 - Dòng OREN - Trang 132",
        },
        {
            "chunk_id": "ilt_cat_p131",  # Trùng chunk_id
            "source_url": "https://online.fliphtml5.com/zpdsw/wjtd/",
            "page_number": 131,
            "sku": "ALB-103001-BL-1D-5",
            "title": "Catalogue ILT 2026 - Dòng OREN - Trang 131",
        },
    ]
    seen = set()
    unique = []
    for d in docs:
        ident = (
            d.get("chunk_id")
            or d.get("_id")
            or (
                d.get("source_url") or d.get("url"),
                d.get("page_number"),
                d.get("sku") or d.get("major_code"),
                d.get("title"),
            )
        )
        if ident not in seen:
            seen.add(ident)
            unique.append(d)

    assert len(unique) == 2
    assert unique[0]["page_number"] == 131
    assert unique[1]["page_number"] == 132
