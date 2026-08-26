"""동일한 한국어 고객지원 문서 세트를 pgvector / faiss / qdrant 3개 트랙에 각각 적재한다."""
from __future__ import annotations

from tabulate import tabulate

from common import client_for, ensure_vector_store, ingest_docs, load_docs, print_header

VECTOR_STORE_NAME = "support-docs-ko"

TRACKS = [
    ("pgvector", "PGVECTOR_LLS_URL"),
    ("faiss", "FAISS_LLS_URL"),
    ("qdrant", "QDRANT_LLS_URL"),
]


def main() -> None:
    docs = load_docs()
    print_header(f"문서 {len(docs)}건을 3개 벡터 저장소 트랙에 적재")

    rows = []
    for label, env_var in TRACKS:
        print(f"\n[{label}] 적재 중...")
        client = client_for(env_var)
        vs = ensure_vector_store(client, VECTOR_STORE_NAME)
        elapsed = ingest_docs(client, vs.id, docs)
        vs = client.vector_stores.retrieve(vs.id)
        rows.append([label, vs.id, vs.file_counts.completed, vs.file_counts.failed, f"{elapsed:.2f}s"])
        print(f"  완료: vector_store_id={vs.id}, completed={vs.file_counts.completed}, "
              f"failed={vs.file_counts.failed}, elapsed={elapsed:.2f}s")

    print_header("적재 결과 요약")
    print(tabulate(rows, headers=["track", "vector_store_id", "completed", "failed", "elapsed"]))


if __name__ == "__main__":
    main()
