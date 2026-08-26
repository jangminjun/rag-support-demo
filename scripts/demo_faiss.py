"""② FAISS 데모: 인라인(파드 내부 메모리) 벡터 검색 지연시간 시연."""
from __future__ import annotations

import statistics
import time

from common import client_for, ensure_vector_store, print_header, print_search_results

VECTOR_STORE_NAME = "support-docs-ko"
QUERIES = [
    "배송 조회는 어떻게 하나요?",
    "환불은 언제 받을 수 있나요?",
    "회원 탈퇴하면 쿠폰은 어떻게 되나요?",
]
REPEATS = 5


def main() -> None:
    client = client_for("FAISS_LLS_URL")
    vs = ensure_vector_store(client, VECTOR_STORE_NAME)

    print_header("② FAISS — 인라인 검색 결과 (search_mode=vector)")
    print(f"질의: {QUERIES[0]!r}")
    results = client.vector_stores.search(vector_store_id=vs.id, query=QUERIES[0], search_mode="vector")
    print_search_results(results)

    print_header("② FAISS — 반복 질의 지연시간(latency) 측정")
    print(f"동일 질의를 각 {REPEATS}회씩 반복 실행 (별도 벡터DB 파드로의 네트워크 홉 없이,")
    print("llama-stack 파드 프로세스 내부 메모리에서 바로 검색)")
    all_latencies = []
    for q in QUERIES:
        latencies = []
        for _ in range(REPEATS):
            start = time.perf_counter()
            client.vector_stores.search(vector_store_id=vs.id, query=q, search_mode="vector")
            latencies.append((time.perf_counter() - start) * 1000)
        all_latencies.extend(latencies)
        print(f"  {q!r}: mean={statistics.mean(latencies):.1f}ms, "
              f"min={min(latencies):.1f}ms, max={max(latencies):.1f}ms")

    print(f"\n전체 평균 지연시간: {statistics.mean(all_latencies):.1f}ms "
          f"(p95={sorted(all_latencies)[int(len(all_latencies) * 0.95) - 1]:.1f}ms)")

    print(
        "\n[정정] 이 데모의 원래 전제였던 '인라인 FAISS = SQLite 임베디드 백엔드(외부 DB 불필요)'는\n"
        "RHOAI 3.1 이하 기준이다. 3.2부터는 인라인 FAISS도 파일/청크 메타데이터 저장에 PostgreSQL이\n"
        "필수로 바뀌었다(SQLite 기반 저장은 더 이상 프로덕션에 권장되지 않음). 이 트랙에서도\n"
        "faiss-postgres를 배포한 이유가 이것이다. FAISS의 진짜 차별점은 '벡터 인덱스(HNSW/Flat) 자체가\n"
        "별도 벡터DB 파드 없이 llama-stack 파드 프로세스 메모리 안에서 동작한다'는 것이며, 이는\n"
        "rag-support-demo 네임스페이스에 pgvector/qdrant 트랙과 달리 이 트랙 전용 벡터DB 파드가\n"
        "존재하지 않는다는 사실로 확인할 수 있다 (manifests/21-faiss-llamastack.yaml에는 벡터 저장소용\n"
        "Deployment가 없고 faiss-postgres만 있음)."
    )


if __name__ == "__main__":
    main()
