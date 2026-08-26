#!/usr/bin/env bash
# rag-support-demo 네임스페이스에 3개 벡터 저장소 트랙(pgvector/faiss/qdrant)을 배포한다.
# 사전조건: oc login 상태일 것 (AGENT.md 참고, git-ignored).
set -euo pipefail
cd "$(dirname "$0")"

echo "==> namespace"
oc apply -f 00-namespace.yaml

echo "==> inference placeholder secret (실제 LLM 추론 없이 vector_io만 검증)"
oc apply -f 01-inference-placeholder-secret.yaml

echo "==> pgvector track"
oc apply -f 10-pgvector-postgres.yaml
echo "==> faiss track"
oc apply -f 20-faiss-postgres.yaml
echo "==> qdrant track"
oc apply -f 30-qdrant.yaml
oc apply -f 31-qdrant-postgres.yaml

echo "==> Postgres/Qdrant 준비 대기"
oc rollout status deployment/pgvector-postgres -n rag-support-demo --timeout=180s
oc rollout status deployment/faiss-postgres -n rag-support-demo --timeout=180s
oc rollout status deployment/qdrant-postgres -n rag-support-demo --timeout=180s
oc rollout status deployment/qdrant -n rag-support-demo --timeout=180s

echo "==> LlamaStackDistribution 3종 배포"
oc apply -f 11-pgvector-llamastack.yaml
oc apply -f 21-faiss-llamastack.yaml
oc apply -f 32-qdrant-llamastack.yaml

echo "==> Ready 대기 (모델 다운로드 등으로 수 분 소요될 수 있음)"
for name in vs-pgvector vs-faiss vs-qdrant; do
  echo "--- $name ---"
  oc wait --for=condition=DeploymentReady "llamastackdistribution/$name" -n rag-support-demo --timeout=600s || true
done

echo "==> 상태 확인"
oc get llamastackdistribution -n rag-support-demo
