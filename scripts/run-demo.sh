#!/usr/bin/env bash
# 3개 LlamaStackDistribution이 Ready인 상태에서, 클러스터 내부 Job으로 데모 스크립트를 실행한다.
# 클러스터 밖(Windows 워크스테이션 등)에서는 ClusterIP/Postgres에 직접 접근할 수 없으므로
# Route/port-forward 대신 in-cluster Job으로 실행해 oc logs로 결과를 확인하는 방식을 쓴다.
set -euo pipefail
NS=rag-support-demo
cd "$(dirname "$0")"

echo "==> ConfigMap: 데모 스크립트"
oc create configmap demo-scripts -n "$NS" \
  --from-file=common.py --from-file=ingest.py --from-file=demo_pgvector.py \
  --from-file=demo_faiss.py --from-file=demo_qdrant.py --from-file=compare_report.py \
  --from-file=requirements.txt \
  --dry-run=client -o yaml | oc apply -f -

echo "==> ConfigMap: 샘플 문서"
oc create configmap demo-docs -n "$NS" \
  --from-file=../data/docs \
  --dry-run=client -o yaml | oc apply -f -

echo "==> 서비스 URL 조회"
PGVECTOR_URL=$(oc get llamastackdistribution vs-pgvector -n "$NS" -o jsonpath='{.status.serviceURL}')
FAISS_URL=$(oc get llamastackdistribution vs-faiss -n "$NS" -o jsonpath='{.status.serviceURL}')
QDRANT_URL=$(oc get llamastackdistribution vs-qdrant -n "$NS" -o jsonpath='{.status.serviceURL}')
echo "  pgvector: $PGVECTOR_URL"
echo "  faiss:    $FAISS_URL"
echo "  qdrant:   $QDRANT_URL"

if [[ -z "$PGVECTOR_URL" || -z "$FAISS_URL" || -z "$QDRANT_URL" ]]; then
  echo "serviceURL을 찾을 수 없습니다. 'oc get llamastackdistribution -n $NS'로 Ready 상태를 확인하세요." >&2
  exit 1
fi

echo "==> 이전 Job 정리"
oc delete job demo-runner -n "$NS" --ignore-not-found

echo "==> Job 생성"
cat <<EOF | oc apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: demo-runner
  namespace: $NS
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: demo-runner
          image: registry.access.redhat.com/ubi9/python-312:latest
          command: ["/bin/bash", "-c"]
          args:
            - |
              set -euo pipefail
              cp /scripts-src/*.py /scripts-src/requirements.txt /tmp/
              cd /tmp
              pip install --quiet --no-cache-dir -r requirements.txt
              echo "### ingest ###"; python ingest.py
              echo "### demo_pgvector ###"; python demo_pgvector.py
              echo "### demo_faiss ###"; python demo_faiss.py
              echo "### demo_qdrant ###"; python demo_qdrant.py
              echo "### compare_report ###"; python compare_report.py
          env:
            - {name: DOCS_DIR, value: /data/docs}
            - {name: PGVECTOR_LLS_URL, value: "$PGVECTOR_URL"}
            - {name: FAISS_LLS_URL, value: "$FAISS_URL"}
            - {name: QDRANT_LLS_URL, value: "$QDRANT_URL"}
            - {name: PGVECTOR_PG_HOST, value: "pgvector-postgres.$NS.svc.cluster.local"}
            - name: PGVECTOR_PG_DB
              valueFrom: {secretKeyRef: {name: pgvector-postgres-credentials, key: POSTGRES_DB}}
            - name: PGVECTOR_PG_USER
              valueFrom: {secretKeyRef: {name: pgvector-postgres-credentials, key: POSTGRES_USER}}
            - name: PGVECTOR_PG_PASSWORD
              valueFrom: {secretKeyRef: {name: pgvector-postgres-credentials, key: POSTGRES_PASSWORD}}
          volumeMounts:
            - {name: scripts, mountPath: /scripts-src}
            - {name: docs, mountPath: /data/docs}
          resources:
            requests: {cpu: 100m, memory: 256Mi}
            limits: {cpu: 500m, memory: 1Gi}
      volumes:
        - name: scripts
          configMap: {name: demo-scripts}
        - name: docs
          configMap: {name: demo-docs}
EOF

echo "==> Job 완료 대기"
oc wait --for=condition=complete job/demo-runner -n "$NS" --timeout=900s || true

echo "==> 로그"
oc logs job/demo-runner -n "$NS" --tail=-1
