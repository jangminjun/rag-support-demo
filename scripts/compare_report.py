"""3개 트랙의 vector_io provider 등록 상태를 조회해 최종 비교표를 출력한다."""
from __future__ import annotations

from tabulate import tabulate

from common import client_for, print_header

TRACKS = [
    ("① pgvector", "PGVECTOR_LLS_URL", "vector만"),
    ("② FAISS", "FAISS_LLS_URL", "vector만"),
    ("③ Qdrant", "QDRANT_LLS_URL", "vector / keyword / hybrid"),
]


def find_vector_io_provider(client) -> str:
    for p in client.providers.list():
        if p.api == "vector_io":
            return p.provider_type
    return "(등록되지 않음)"


def main() -> None:
    print_header("최종 비교: OpenShift AI 3.4 벡터 저장소 3종 지원 확인")

    rows = []
    for label, env_var, modes in TRACKS:
        client = client_for(env_var)
        provider_type = find_vector_io_provider(client)
        rows.append([label, provider_type, modes])

    print(tabulate(rows, headers=["트랙", "등록된 provider_type", "지원 search_mode"]))

    print(
        "\n요약:\n"
        "  ① pgvector (remote::pgvector) — 원격 PostgreSQL+pgvector, 표준 RDBMS 트랜잭션/HA 상속\n"
        "  ② FAISS (inline::faiss)      — 파드 내부 메모리 벡터 인덱스, 3.2+부터 메타데이터는 Postgres 필수\n"
        "  ③ Qdrant (remote::qdrant)    — RHOAI 3.4 신규 Technology Preview, 하이브리드+키워드 검색 추가\n"
    )


if __name__ == "__main__":
    main()
