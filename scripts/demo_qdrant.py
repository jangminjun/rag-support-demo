"""③ Qdrant 데모: RHOAI 3.4 신규 — 하이브리드(vector+keyword) 검색 및 키워드 전용 검색."""
from __future__ import annotations

from common import client_for, ensure_vector_store, print_header, print_search_results

VECTOR_STORE_NAME = "support-docs-ko"

# "배송"이라는 키워드는 공유하지만 의미(주제)는 서로 다른 두 문서를 의도적으로 준비했다:
# shipping-tracking.md(배송 조회) vs shipping-fee-refund.md(배송비 환불).
# 키워드 검색은 두 문서를 동등하게 매칭시키는 반면, 순수 의미 검색은 질문 의도에 더 가까운
# 문서에 높은 점수를 주는 경향이 있다 — 이 차이를 통해 세 가지 검색 모드의 특성을 보여준다.
QUERY = "배송비 환불 규정이 궁금해요"


def run_mode(client, vector_store_id: str, search_mode: str) -> None:
    print(f"\n--- search_mode={search_mode!r} ---")
    results = client.vector_stores.search(
        vector_store_id=vector_store_id, query=QUERY, search_mode=search_mode
    )
    print_search_results(results)


def main() -> None:
    client = client_for("QDRANT_LLS_URL")
    vs = ensure_vector_store(client, VECTOR_STORE_NAME)

    print_header("③ Qdrant — 검색 모드 3종 비교 (RHOAI 3.4 신규: 하이브리드 + 키워드 전용)")
    print(f"질의: {QUERY!r}")

    for mode in ("vector", "keyword", "hybrid"):
        try:
            run_mode(client, vs.id, mode)
        except Exception as e:  # noqa: BLE001
            print(f"  [실패] search_mode={mode!r}: {type(e).__name__}: {e}")

    print(
        "\n[비교 포인트] pgvector/FAISS 트랙은 search_mode='vector'만 지원한다(다른 모드를 요청하면\n"
        "서버가 지원하지 않거나 무시/에러를 반환한다). Qdrant 트랙만 'keyword'(어휘 일치, BM25 계열)와\n"
        "'hybrid'(벡터+키워드 점수를 RRF/가중합으로 결합)를 추가로 지원한다 — 이것이 RHOAI 3.4에서\n"
        "신규로 추가된 기능이다."
    )


if __name__ == "__main__":
    main()
