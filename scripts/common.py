"""3개 벡터 저장소 트랙 데모 공용 유틸리티."""
from __future__ import annotations

import glob
import os
import time

from llama_stack_client import LlamaStackClient

DOCS_DIR = os.environ.get("DOCS_DIR", "/data/docs")


def load_docs() -> list[tuple[str, str]]:
    """(파일명, 본문) 튜플 리스트로 샘플 한국어 고객지원 문서를 읽어온다."""
    paths = sorted(glob.glob(os.path.join(DOCS_DIR, "*.md")))
    if not paths:
        raise RuntimeError(f"문서를 찾을 수 없습니다: {DOCS_DIR}")
    docs = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            docs.append((os.path.basename(p), f.read()))
    return docs


def client_for(env_var: str) -> LlamaStackClient:
    """환경변수로 전달된 LlamaStackDistribution serviceURL로 클라이언트를 생성한다."""
    base_url = os.environ[env_var]
    return LlamaStackClient(base_url=base_url)


def default_embedding_model(client: LlamaStackClient) -> str:
    """등록된 모델 중 embedding 타입 모델의 id를 찾는다 (ENABLE_SENTENCE_TRANSFORMERS로 자동 등록됨)."""
    for m in client.models.list():
        if m.model_type == "embedding":
            return m.id
    raise RuntimeError("임베딩 모델을 찾을 수 없습니다 (client.models.list() 결과 확인 필요)")


def ensure_vector_store(client: LlamaStackClient, name: str):
    """이름으로 기존 vector store를 찾거나 없으면 새로 만든다(재실행 안전)."""
    for vs in client.vector_stores.list():
        if vs.name == name:
            return vs
    embedding_model = default_embedding_model(client)
    return client.vector_stores.create(name=name, extra_body={"embedding_model": embedding_model})


def ingest_docs(client: LlamaStackClient, vector_store_id: str, docs: list[tuple[str, str]]) -> float:
    """문서들을 업로드하고 vector store에 첨부(자동 청킹+임베딩)한다. 인덱싱 완료까지 대기 후
    총 소요 시간(초)을 반환한다."""
    start = time.time()
    for filename, content in docs:
        file_obj = client.files.create(
            file=(filename, content.encode("utf-8"), "text/markdown"),
            purpose="assistants",
        )
        client.vector_stores.files.create(vector_store_id=vector_store_id, file_id=file_obj.id)

    deadline = time.time() + 300
    while time.time() < deadline:
        vs = client.vector_stores.retrieve(vector_store_id)
        if vs.file_counts.in_progress == 0:
            break
        time.sleep(2)
    else:
        print("  [경고] 인덱싱이 시간 내에 끝나지 않았습니다 (마지막 상태 확인 필요)")
    return time.time() - start


def print_header(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def print_search_results(results) -> None:
    for i, item in enumerate(results.data, start=1):
        score = getattr(item, "score", None)
        filename = getattr(item, "filename", "?")
        text = ""
        for c in getattr(item, "content", []) or []:
            text += getattr(c, "text", "")
        text = text.strip().replace("\n", " ")[:80]
        score_str = f"{score:.4f}" if isinstance(score, (int, float)) else str(score)
        print(f"  {i}. [{score_str}] {filename} :: {text}...")
