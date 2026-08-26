"""① pgvector 데모: 의미 검색 + PostgreSQL 트랜잭션 보장 시연."""
from __future__ import annotations

import os

import psycopg2

from common import client_for, ensure_vector_store, print_header, print_search_results

VECTOR_STORE_NAME = "support-docs-ko"
QUERY = "배송 조회는 어떻게 하나요?"

PG_HOST = os.environ.get("PGVECTOR_PG_HOST", "pgvector-postgres.rag-support-demo.svc.cluster.local")
PG_PORT = int(os.environ.get("PGVECTOR_PG_PORT", "5432"))
PG_DB = os.environ["PGVECTOR_PG_DB"]
PG_USER = os.environ["PGVECTOR_PG_USER"]
PG_PASSWORD = os.environ["PGVECTOR_PG_PASSWORD"]


def semantic_search_demo() -> None:
    print_header("① pgvector — 의미 검색 (search_mode=vector)")
    client = client_for("PGVECTOR_LLS_URL")
    vs = ensure_vector_store(client, VECTOR_STORE_NAME)
    print(f"질의: {QUERY!r}")
    results = client.vector_stores.search(vector_store_id=vs.id, query=QUERY, search_mode="vector")
    print_search_results(results)


def find_vector_table(cur) -> tuple[str, str] | None:
    """llama-stack이 만든, vector 타입 컬럼을 가진 테이블을 찾는다."""
    cur.execute(
        """
        SELECT table_name, column_name FROM information_schema.columns
        WHERE udt_name = 'vector' AND table_schema = 'public'
        LIMIT 1
        """
    )
    return cur.fetchone()


def transaction_demo() -> None:
    print_header("① pgvector — PostgreSQL 트랜잭션 보장 시연")
    conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            print(f"직접 SQL 접속: {PG_HOST}:{PG_PORT}/{PG_DB} (표준 psycopg2, 일반 RDBMS 클라이언트)")
            found = find_vector_table(cur)
            if not found:
                print("  [경고] vector 컬럼을 가진 테이블을 찾지 못했습니다 (아직 ingest 전이거나 스키마 변경됨)")
                return
            table, column = found
            cur.execute(f'SELECT count(*) FROM "{table}"')
            before = cur.fetchone()[0]
            print(f"실제 임베딩이 저장된 테이블: {table} (컬럼 {column}: vector 타입) — 현재 {before}행")

            print("\n트랜잭션 내에서 의도적으로 실패하는 INSERT를 실행해 롤백을 확인합니다...")
            try:
                # 존재하지 않는 컬럼을 참조해 스키마와 무관하게 항상 실패하도록 유도
                cur.execute(f'INSERT INTO "{table}" (__demo_intentionally_bad_column__) VALUES (1)')
            except Exception as e:  # noqa: BLE001 - 데모 목적의 의도된 실패
                print(f"  예상대로 실패: {type(e).__name__}: {str(e).splitlines()[0]}")
                conn.rollback()
            else:
                conn.rollback()
                print("  (예상과 달리 성공했으나 ROLLBACK으로 되돌립니다)")

            with conn.cursor() as cur2:
                cur2.execute(f'SELECT count(*) FROM "{table}"')
                after = cur2.fetchone()[0]
            print(f"롤백 후 행 수: {after} (before={before}) -> {'변화 없음: ACID 트랜잭션 보장 확인' if after == before else '불일치!'}")
    finally:
        conn.close()

    print(
        "\n[HA 참고] 이 데모는 단일 Postgres 인스턴스로 구성했지만, pgvector는 순수 PostgreSQL 확장이므로\n"
        "표준 Postgres HA 구성(스트리밍 복제, Patroni, CloudNativePG, RDS Multi-AZ 등)을 그대로 적용해\n"
        "이중화할 수 있다 — 별도의 벡터 전용 HA 메커니즘이 필요하지 않다는 것이 pgvector의 핵심 이점이다."
    )


if __name__ == "__main__":
    semantic_search_demo()
    transaction_demo()
