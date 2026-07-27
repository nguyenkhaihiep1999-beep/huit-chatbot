#!/usr/bin/env python3
"""Deterministic RAG benchmark for retrieval and answer grounding."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import rag_core


def load_cases():
    return json.loads((HERE / "rag_benchmark.json").read_text(encoding="utf-8"))


def contains_all(text, values):
    normalized = rag_core._normalize(text)
    return all(rag_core._normalize(value) in normalized for value in values)


def evaluate_case(case, retrieval_only=False):
    started = time.perf_counter()
    docs = rag_core.retrieve(case["query"], top_k=5)
    retrieval_text = " ".join(
        f"{doc.get('title', '')} {doc.get('text', '')}" for doc in docs
    )
    retrieval_hit = contains_all(retrieval_text, case["retrieval_must_include"])
    top1_text = (
        f"{docs[0].get('title', '')} {docs[0].get('text', '')}"
        if docs else ""
    )
    top1_hit = contains_all(top1_text, case.get("top1_should_include", []))

    result = {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "retrieval_hit": retrieval_hit,
        "top1_hit": top1_hit,
        "source_count": len(docs),
    }
    if not retrieval_only:
        response = rag_core.answer(case["query"])
        answer = response.get("answer", "")
        result.update({
            "answer_hit": contains_all(answer, case["answer_must_include"]),
            "answer_forbidden": any(
                rag_core._normalize(value) in rag_core._normalize(answer)
                for value in case.get("answer_must_not_include", [])
            ),
            "fallback": bool(response.get("meta", {}).get("fallback")),
            "answer_length": len(answer),
        })
    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--output", default="rag_evaluation_results.json")
    args = parser.parse_args()

    results = [
        evaluate_case(case, retrieval_only=args.retrieval_only)
        for case in load_cases()
    ]
    total = len(results)
    summary = {
        "total": total,
        "retrieval_hit_rate": round(
            sum(item["retrieval_hit"] for item in results) / total, 3
        ),
        "top1_hit_rate": round(
            sum(item["top1_hit"] for item in results) / total, 3
        ),
        "average_seconds": round(
            sum(item["elapsed_seconds"] for item in results) / total, 2
        ),
    }
    if not args.retrieval_only:
        summary.update({
            "answer_hit_rate": round(
                sum(item["answer_hit"] for item in results) / total, 3
            ),
            "forbidden_answer_rate": round(
                sum(item["answer_forbidden"] for item in results) / total, 3
            ),
            "fallback_rate": round(
                sum(item["fallback"] for item in results) / total, 3
            ),
        })

    payload = {"summary": summary, "results": results}
    output = HERE / args.output
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")
    return 0 if summary["retrieval_hit_rate"] >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
