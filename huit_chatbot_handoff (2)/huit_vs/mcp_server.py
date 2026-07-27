#!/usr/bin/env python3
"""MCP Server cho HUIT Chatbot Tuyển Sinh.

Cung cấp chuẩn Model Context Protocol (MCP) qua Stdio JSON-RPC.
Tương thích với Claude Desktop, Cursor, Antigravity IDE & các MCP Client.

Công cụ (Tools) cung cấp:
1. ask_huit_admission: Hỏi đáp tự động bằng RAG MongoDB Atlas & LLM.
2. search_huit_kb: Tra cứu Vector Search trực tiếp trong kho tri thức HUIT.
3. run_mongo_aggregation: Thực thi 1 trong 10 MongoDB Aggregation Pipelines lưu trong `code_modules`.
4. get_huit_kb_analytics: Lấy báo cáo thống kê danh mục tri thức HUIT real-time.
5. sync_huit_kaggle_dataset: Đào dữ liệu thô & đồng bộ sang Kaggle CSV dataset.
"""
import json
import sys
import os
from urllib.parse import quote_plus
from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rag_core
import kaggle_huit_miner

# Database Credentials
USER = "nguyenkhaihiep1999_db_user"
HOST = "cluster0.hyj8rab.mongodb.net"
DB_NAME = "huit_chatbot"

pwd = os.environ.get("MONGODB_PASSWORD")
if not pwd:
    env_file = os.path.join(HERE, ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("MONGODB_PASSWORD="):
                    pwd = line.split("=", 1)[1].strip().strip('"\'')
if not pwd:
    raise RuntimeError("MONGODB_PASSWORD chưa được cấu hình.")

def get_mongo_db():
    uri = f"mongodb+srv://{USER}:{quote_plus(pwd)}@{HOST}/?appName=Cluster0"
    client = MongoClient(uri, serverSelectionTimeoutMS=12000)
    return client[DB_NAME]

def send_response(response_obj):
    body = json.dumps(response_obj, ensure_ascii=False)
    sys.stdout.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
    sys.stdout.flush()

def handle_request(req):
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "HUIT-Admission-MCP-Server",
                    "version": "1.1.0"
                }
            }
        })

    elif method == "notifications/initialized":
        pass

    elif method == "tools/list":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "ask_huit_admission",
                        "description": "Hỏi đáp thông tin tuyển sinh HUIT bằng AI RAG MongoDB.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "Câu hỏi tuyển sinh HUIT"
                                }
                            },
                            "required": ["question"]
                        }
                    },
                    {
                        "name": "search_huit_kb",
                        "description": "Tìm kiếm Vector Search các đoạn văn bản tri thức HUIT trong MongoDB Atlas.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Từ khóa hoặc câu hỏi"},
                                "top_k": {"type": "integer", "default": 3}
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "run_mongo_aggregation",
                        "description": "Thực thi MongoDB Aggregation Pipeline từ collection code_modules (VD: huit_data_cleaning, huit_agg_categorization, huit_agg_stats, huit_agg_deduplicate, huit_agg_quality_scoring).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "module_id": {
                                    "type": "string",
                                    "description": "Tên ID module trong code_modules"
                                }
                            },
                            "required": ["module_id"]
                        }
                    },
                    {
                        "name": "get_huit_kb_analytics",
                        "description": "Lấy thống kê số liệu tổng quan tri thức HUIT theo từng danh mục trên MongoDB Atlas.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "sync_huit_kaggle_dataset",
                        "description": "Đào dữ liệu thô HUIT, lưu MongoDB và xuất dataset chuẩn Kaggle CSV.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                ]
            }
        })

    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "ask_huit_admission":
            question = args.get("question", "")
            try:
                res = rag_core.answer(question)
                ans = res.get("answer", "")
                sources = res.get("sources", [])
                src_txt = "\n".join([f"- Nguồn #{s['i']}: {s['title']} ({s['url']})" for s in sources])
                full_content = f"{ans}\n\n**Danh sách trích dẫn nguồn:**\n{src_txt}"
                
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": full_content}]}
                })
            except Exception as e:
                send_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}})

        elif tool_name == "search_huit_kb":
            query = args.get("query", "")
            top_k = args.get("top_k", 3)
            try:
                docs = rag_core.retrieve(query, top_k)
                formatted_docs = [
                    f"### Kết quả #{idx}: {doc.get('title', 'HUIT Chunk')}\n- Điểm: {round(doc.get('score', 0), 4)}\n- Nội dung: {doc.get('text')}\n"
                    for idx, doc in enumerate(docs, 1)
                ]
                result_text = "\n\n".join(formatted_docs) if formatted_docs else "Không tìm thấy dữ liệu."
                send_response({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": result_text}]}})
            except Exception as e:
                send_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}})

        elif tool_name == "run_mongo_aggregation":
            module_id = args.get("module_id", "")
            try:
                db = get_mongo_db()
                code_doc = db["code_modules"].find_one({"_id": module_id})
                if not code_doc:
                    res_txt = f"Lỗi: Không tìm thấy module ID '{module_id}' trong code_modules."
                else:
                    pipeline = code_doc["private"]["node_function"]["edge"][0]["pipeline"]
                    # Default target source collection
                    source_coll = "test_clean_data" if "clean" not in module_id else "raw_data"
                    db[source_coll].aggregate(pipeline)
                    res_txt = f"Đã thực thi thành công Aggregation Pipeline '{module_id}' trên collection '{source_coll}'!"
                
                send_response({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": res_txt}]}})
            except Exception as e:
                send_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}})

        elif tool_name == "get_huit_kb_analytics":
            try:
                db = get_mongo_db()
                stats = list(db["test_kb_stats"].find({}, {"_id": 1, "total_chunks": 1, "avg_text_length": 1}))
                lines = ["### Báo Cáo Thống Kê Tri Thức HUIT Trên MongoDB Atlas:"]
                for s in stats:
                    lines.append(f"- **{s['_id']}**: {s['total_chunks']} tài liệu (Độ dài TB: {int(s.get('avg_text_length', 0))} ký tự)")
                
                send_response({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "\n".join(lines)}]}})
            except Exception as e:
                send_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}})

        elif tool_name == "sync_huit_kaggle_dataset":
            try:
                count = kaggle_huit_miner.run_miner()
                msg = f"Đã đồng bộ {count} bản ghi HUIT vào MongoDB Atlas & xuất file dataset Kaggle thành công!"
                send_response({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": msg}]}})
            except Exception as e:
                send_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}})

        else:
            send_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Tool '{tool_name}' không tồn tại."}})
    else:
        if req_id is not None:
            send_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' không được hỗ trợ."}})

def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            if line.startswith("Content-Length:"):
                length = int(line.split(":")[1].strip())
                sys.stdin.readline()
                body = sys.stdin.read(length)
                req = json.loads(body)
                handle_request(req)
            elif line.strip().startswith("{"):
                req = json.loads(line.strip())
                handle_request(req)
        except Exception as e:
            sys.stderr.write(f"MCP Error: {e}\n")
            sys.stderr.flush()

if __name__ == "__main__":
    main()
