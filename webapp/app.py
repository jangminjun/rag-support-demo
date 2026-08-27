"""OpenShift AI 3.4 벡터 저장소 3종 비교 챗 UI.

브라우저에서 질의를 입력하면 pgvector / FAISS / Qdrant 3개 트랙에 동시에 검색을 날리고,
각 트랙의 검색 결과를 근거로 Qwen2.5-3B-Instruct(vLLM)가 실제 답변까지 생성하는 RAG 데모.
문서 적재는 scripts/ingest.py로 이미 끝난 상태를 전제로 같은 이름("support-docs-ko")의
vector store를 찾아 재사용한다.
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from llama_stack_client import LlamaStackClient

VECTOR_STORE_NAME = "support-docs-ko"
# llama-stack은 /v1/chat/completions에서 provider_id로 접두된 전체 id를 요구한다
# (짧은 이름 "qwen2.5-3b"만 넣으면 404 Model not found).
MODEL_NAME = "vllm-inference/qwen2.5-3b"

TRACKS = {
    "pgvector": {"env": "PGVECTOR_LLS_URL", "label": "① pgvector", "modes": ["vector"]},
    "faiss": {"env": "FAISS_LLS_URL", "label": "② FAISS", "modes": ["vector"]},
    "qdrant": {"env": "QDRANT_LLS_URL", "label": "③ Qdrant", "modes": ["vector", "keyword", "hybrid"]},
}

# 답변 생성에 사용할 검색 모드 - Qdrant는 하이브리드가 가장 완전한 신호이므로 이걸 근거로 쓴다.
PRIMARY_MODE = {"pgvector": "vector", "faiss": "vector", "qdrant": "hybrid"}

app = FastAPI()

_clients: dict[str, LlamaStackClient] = {}
_vector_store_ids: dict[str, str] = {}


def client_for(track: str) -> LlamaStackClient:
    if track not in _clients:
        base_url = os.environ[TRACKS[track]["env"]]
        _clients[track] = LlamaStackClient(base_url=base_url)
    return _clients[track]


def default_embedding_model(client: LlamaStackClient) -> str:
    for m in client.models.list():
        if m.model_type == "embedding":
            return m.id
    raise RuntimeError("임베딩 모델을 찾을 수 없습니다")


def vector_store_id_for(track: str) -> str:
    if track not in _vector_store_ids:
        client = client_for(track)
        for vs in client.vector_stores.list():
            if vs.name == VECTOR_STORE_NAME:
                _vector_store_ids[track] = vs.id
                break
        else:
            embedding_model = default_embedding_model(client)
            vs = client.vector_stores.create(
                name=VECTOR_STORE_NAME, extra_body={"embedding_model": embedding_model}
            )
            _vector_store_ids[track] = vs.id
    return _vector_store_ids[track]


def format_results(results) -> list[dict]:
    out = []
    for item in results.data:
        text = ""
        for c in item.content:
            text += c.text
        out.append(
            {
                "filename": item.filename,
                "score": round(item.score, 4),
                "text": text.strip().replace("\n", " ")[:200],
            }
        )
    return out


def generate_answer(client: LlamaStackClient, query: str, results: list[dict]) -> tuple[str, float]:
    """검색 결과 상위 몇 건을 근거로 Qwen2.5-3B-Instruct에게 답변을 생성시킨다."""
    context = "\n\n".join(f"[{r['filename']}] {r['text']}" for r in results[:3])
    prompt = (
        "다음은 고객지원 문서에서 검색된 내용입니다.\n\n"
        f"{context}\n\n"
        "위 내용만 근거로 삼아 아래 질문에 한국어로 간결하게 답변하세요. "
        "문서에 없는 내용은 모른다고 답하세요.\n\n"
        f"질문: {query}"
    )
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.2,
    )
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    return response.choices[0].message.content.strip(), elapsed_ms


class SearchRequest(BaseModel):
    query: str


@app.post("/api/search")
def search(req: SearchRequest) -> JSONResponse:
    query = req.query.strip()
    if not query:
        return JSONResponse({"error": "질의를 입력해 주세요."}, status_code=400)

    response: dict = {}
    for track, meta in TRACKS.items():
        try:
            client = client_for(track)
            vs_id = vector_store_id_for(track)
        except Exception as e:  # noqa: BLE001
            response[track] = {"error": f"{type(e).__name__}: {e}"}
            continue

        response[track] = {"label": meta["label"], "modes": {}}
        for mode in meta["modes"]:
            start = time.perf_counter()
            try:
                results = client.vector_stores.search(
                    vector_store_id=vs_id, query=query, search_mode=mode
                )
                elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
                response[track]["modes"][mode] = {
                    "elapsed_ms": elapsed_ms,
                    "results": format_results(results),
                }
            except Exception as e:  # noqa: BLE001
                response[track]["modes"][mode] = {"error": f"{type(e).__name__}: {e}"}

        primary = response[track]["modes"].get(PRIMARY_MODE[track])
        if primary and "results" in primary:
            try:
                answer, gen_ms = generate_answer(client, query, primary["results"])
                response[track]["answer"] = {"text": answer, "elapsed_ms": gen_ms}
            except Exception as e:  # noqa: BLE001
                response[track]["answer"] = {"error": f"{type(e).__name__}: {e}"}

    return JSONResponse(response)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


INDEX_HTML = r"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>벡터 저장소 3종 비교 데모</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px; background: #f4f5f7; color: #1a1a1a;
    font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 20px; }
  .search-bar { display: flex; gap: 8px; margin-bottom: 24px; max-width: 720px; }
  .search-bar input {
    flex: 1; padding: 12px 14px; font-size: 15px; border: 1px solid #ccc;
    border-radius: 8px; outline: none;
  }
  .search-bar input:focus { border-color: #6366f1; }
  .search-bar button {
    padding: 12px 20px; font-size: 15px; border: none; border-radius: 8px;
    background: #6366f1; color: white; cursor: pointer;
  }
  .search-bar button:disabled { background: #aaa; cursor: default; }
  .columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
  .card {
    background: white; border-radius: 10px; padding: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); min-height: 120px;
  }
  .card h2 { font-size: 15px; margin: 0 0 4px; }
  .card .meta { font-size: 12px; color: #888; margin-bottom: 10px; }
  .tabs { display: flex; gap: 4px; margin-bottom: 10px; }
  .tab {
    padding: 4px 10px; font-size: 12px; border-radius: 6px; cursor: pointer;
    background: #eee; color: #555;
  }
  .tab.active { background: #6366f1; color: white; }
  .result { padding: 8px 0; border-bottom: 1px solid #eee; font-size: 13px; }
  .result:last-child { border-bottom: none; }
  .result .rank { color: #999; margin-right: 4px; }
  .result .fname { font-weight: 600; color: #333; }
  .result .score { color: #6366f1; font-family: monospace; margin-left: 6px; }
  .result .snippet { color: #666; margin-top: 2px; }
  .error { color: #d33; font-size: 13px; }
  .empty { color: #999; font-size: 13px; }
  .answer {
    background: #f0f0fb; border: 1px solid #dcdcf5; border-radius: 8px;
    padding: 10px 12px; margin-bottom: 12px;
  }
  .answer-label { font-size: 11px; color: #6366f1; font-weight: 600; margin-bottom: 4px; }
  .answer-text { font-size: 13.5px; color: #333; line-height: 1.5; }
  .answer-error { color: #d33; font-size: 12.5px; }
</style>
</head>
<body>
  <h1>벡터 저장소 3종 비교 — pgvector / FAISS / Qdrant</h1>
  <div class="subtitle">같은 질의를 동시에 던져 검색 결과를 비교하고, 각 트랙이 검색된 문서를 근거로 Qwen2.5-3B가 생성한 실제 답변까지 보여줍니다 (생성 포함, 응답까지 최대 30초 정도 걸릴 수 있습니다).</div>

  <div class="search-bar">
    <input id="query" type="text" placeholder="예: 배송비 환불 규정이 궁금해요" />
    <button id="searchBtn" onclick="runSearch()">검색</button>
  </div>

  <div class="columns" id="columns">
    <div class="card"><h2>① pgvector</h2><div class="empty">질의를 입력하고 검색을 눌러보세요.</div></div>
    <div class="card"><h2>② FAISS</h2><div class="empty">질의를 입력하고 검색을 눌러보세요.</div></div>
    <div class="card"><h2>③ Qdrant</h2><div class="empty">질의를 입력하고 검색을 눌러보세요.</div></div>
  </div>

<script>
let lastData = null;
let qdrantMode = "vector";

document.getElementById("query").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});

async function runSearch() {
  const query = document.getElementById("query").value.trim();
  if (!query) return;
  const btn = document.getElementById("searchBtn");
  btn.disabled = true;
  btn.textContent = "검색 중...";
  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    lastData = data;
    render();
  } catch (e) {
    document.getElementById("columns").innerHTML =
      '<div class="card"><div class="error">요청 실패: ' + e + "</div></div>";
  } finally {
    btn.disabled = false;
    btn.textContent = "검색";
  }
}

function renderResults(list) {
  if (!list || list.length === 0) return '<div class="empty">결과 없음</div>';
  return list
    .map(
      (r, i) =>
        '<div class="result"><span class="rank">' + (i + 1) + ".</span>" +
        '<span class="fname">' + r.filename + "</span>" +
        '<span class="score">' + r.score.toFixed(4) + "</span>" +
        '<div class="snippet">' + r.text + "...</div></div>"
    )
    .join("");
}

function renderAnswer(meta, note) {
  if (!meta.answer) return "";
  if (meta.answer.error) {
    return '<div class="answer answer-error">답변 생성 실패: ' + meta.answer.error + "</div>";
  }
  const label = "생성된 답변" + (note ? " (" + note + " 근거)" : "") + " · " + meta.answer.elapsed_ms + "ms";
  return (
    '<div class="answer"><div class="answer-label">' + label + "</div>" +
    '<div class="answer-text">' + meta.answer.text + "</div></div>"
  );
}

function renderTrackCard(key, data) {
  const meta = data[key];
  if (!meta) return '<div class="card"><h2>' + key + '</h2><div class="empty">-</div></div>';
  if (meta.error) {
    return '<div class="card"><h2>' + meta.label + '</h2><div class="error">' + meta.error + "</div></div>";
  }
  if (key !== "qdrant") {
    const mode = meta.modes["vector"];
    if (mode.error) return '<div class="card"><h2>' + meta.label + '</h2><div class="error">' + mode.error + "</div></div>";
    return (
      '<div class="card"><h2>' + meta.label + "</h2>" +
      renderAnswer(meta) +
      '<div class="meta">search_mode=vector · ' + mode.elapsed_ms + "ms</div>" +
      renderResults(mode.results) +
      "</div>"
    );
  }
  const tabs = ["vector", "keyword", "hybrid"]
    .map(
      (m) =>
        '<div class="tab' + (m === qdrantMode ? " active" : "") + '" onclick="setQdrantMode(\'' + m + "')\">" + m + "</div>"
    )
    .join("");
  const mode = meta.modes[qdrantMode];
  const body = mode.error
    ? '<div class="error">' + mode.error + "</div>"
    : '<div class="meta">' + mode.elapsed_ms + "ms</div>" + renderResults(mode.results);
  return (
    '<div class="card"><h2>' + meta.label + "</h2>" +
    renderAnswer(meta, "hybrid") +
    '<div class="tabs">' + tabs + "</div>" + body + "</div>"
  );
}

function setQdrantMode(m) {
  qdrantMode = m;
  render();
}

function render() {
  if (!lastData) return;
  document.getElementById("columns").innerHTML =
    renderTrackCard("pgvector", lastData) +
    renderTrackCard("faiss", lastData) +
    renderTrackCard("qdrant", lastData);
}
</script>
</body>
</html>
"""
