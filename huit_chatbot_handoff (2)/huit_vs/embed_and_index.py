#!/usr/bin/env python3
"""HUIT chatbot - Vector Search prototype (Step 7, the 'soul').

1) Build sample Vietnamese HUIT knowledge-base docs (placeholders until we scrape real data).
2) Embed them with fastembed multilingual MiniLM (ONNX, offline, Vietnamese-capable).
3) Insert into MongoDB Atlas  db=huit_chatbot  collection=huit_kb.
4) Create an Atlas Vector Search index (cosine, 384 dims).
Reads MONGODB_PASSWORD from env; builds + URL-encodes the URI itself.
"""
import os
import sys
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB = "huit_chatbot"
COLL = "huit_kb"
INDEX = "huit_vector_index"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"  # 384-dim
DIMS = 384

DOCS = [
    {"title": "Giới thiệu trường",
     "text": "Trường Đại học Công Thương TP.HCM (HUIT), tiền thân là HUFI, là trường đại học công lập trực thuộc Bộ Công Thương, đào tạo đa ngành về kinh tế, kỹ thuật và công nghệ thực phẩm."},
    {"title": "Ngành đào tạo",
     "text": "HUIT đào tạo nhiều ngành: Công nghệ thông tin, Công nghệ thực phẩm, Quản trị kinh doanh, Kế toán, Marketing, Công nghệ sinh học, Ngôn ngữ Anh và nhiều ngành khác."},
    {"title": "Học phí",
     "text": "Học phí năm học được tính theo tín chỉ, dao động tùy theo ngành và chương trình đào tạo. Sinh viên có thể tra cứu học phí chi tiết trên cổng thông tin sinh viên."},
    {"title": "Tuyển sinh",
     "text": "Trường xét tuyển theo nhiều phương thức: xét điểm thi tốt nghiệp THPT, xét học bạ, xét điểm thi đánh giá năng lực và tuyển thẳng theo quy định của Bộ Giáo dục và Đào tạo."},
    {"title": "Học bổng",
     "text": "HUIT có nhiều loại học bổng khuyến khích học tập cho sinh viên có thành tích tốt, học bổng vượt khó và học bổng từ doanh nghiệp tài trợ."},
    {"title": "Ký túc xá",
     "text": "Trường có ký túc xá cho sinh viên với chi phí hợp lý, ưu tiên sinh viên năm nhất, sinh viên ở xa và sinh viên có hoàn cảnh khó khăn."},
    {"title": "Địa chỉ và liên hệ",
     "text": "Cơ sở chính của trường đặt tại quận Tân Phú, TP.HCM. Thông tin liên hệ và tư vấn tuyển sinh được đăng trên website chính thức hufi.edu.vn."},
    {"title": "Thư viện",
     "text": "Thư viện trường cung cấp giáo trình, tài liệu điện tử, phòng đọc và tài khoản truy cập cơ sở dữ liệu học thuật cho sinh viên và giảng viên."},
    {"title": "Việc làm sau tốt nghiệp",
     "text": "Sinh viên tốt nghiệp HUIT có tỷ lệ có việc làm cao, đặc biệt ở nhóm ngành công nghệ thực phẩm và công nghệ thông tin, nhờ hợp tác chặt chẽ với doanh nghiệp."},
    {"title": "Nghiên cứu khoa học",
     "text": "Trường khuyến khích sinh viên tham gia nghiên cứu khoa học, các cuộc thi học thuật, khởi nghiệp và có quỹ hỗ trợ đề tài nghiên cứu sinh viên."},
]


def main():
    pwd = os.environ.get("MONGODB_PASSWORD")
    if not pwd:
        sys.exit("MONGODB_PASSWORD missing")
    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"

    print("Loading embedding model (first run downloads the ONNX model) ...")
    from fastembed import TextEmbedding
    model = TextEmbedding(MODEL)

    texts = [f"{d['title']}. {d['text']}" for d in DOCS]
    print(f"Embedding {len(texts)} documents ...")
    vecs = [v.tolist() for v in model.embed(texts)]
    print(f"  vector dimension = {len(vecs[0])}")

    client = MongoClient(uri, serverSelectionTimeoutMS=12000)
    client.admin.command("ping")
    print("MongoDB connection OK")
    coll = client[DB][COLL]
    coll.drop()
    coll.insert_many([{"title": d["title"], "text": d["text"], "embedding": v}
                      for d, v in zip(DOCS, vecs)])
    print(f"Inserted {coll.count_documents({})} docs into {DB}.{COLL}")

    existing = [ix["name"] for ix in coll.list_search_indexes()]
    if INDEX in existing:
        print(f"Vector index '{INDEX}' already exists.")
    else:
        idx = SearchIndexModel(
            definition={"fields": [{
                "type": "vector", "path": "embedding",
                "numDimensions": DIMS, "similarity": "cosine",
            }]},
            name=INDEX, type="vectorSearch",
        )
        coll.create_search_index(model=idx)
        print(f"Vector index '{INDEX}' creation requested (builds in background).")
    client.close()
    print("DONE_INGEST")


if __name__ == "__main__":
    main()
