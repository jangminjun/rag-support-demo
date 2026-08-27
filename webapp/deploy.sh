#!/usr/bin/env bash
# 브라우저용 벡터 저장소 비교 챗 UI를 rag-support-demo 네임스페이스에 배포하고
# Route로 공개한다. 3개 LlamaStackDistribution이 이미 Ready 상태이고
# scripts/ingest.py로 문서 적재가 끝났다고 전제한다.
set -euo pipefail
NS=rag-support-demo
cd "$(dirname "$0")"

echo "==> ConfigMap: 웹앱 코드"
oc create configmap chat-ui-app -n "$NS" \
  --from-file=app.py --from-file=requirements.txt \
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

echo "==> Deployment + Service + Route 적용"
cat <<EOF | oc apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: chat-ui
  namespace: $NS
  labels: {app: chat-ui}
spec:
  replicas: 1
  selector:
    matchLabels: {app: chat-ui}
  template:
    metadata:
      labels: {app: chat-ui}
    spec:
      containers:
        - name: chat-ui
          image: registry.access.redhat.com/ubi9/python-312:latest
          command: ["/bin/bash", "-c"]
          args:
            - |
              set -euo pipefail
              cp /app-src/*.py /app-src/requirements.txt /tmp/
              cd /tmp
              pip install --quiet --no-cache-dir -r requirements.txt
              exec python -m uvicorn app:app --host 0.0.0.0 --port 8080
          env:
            - {name: PGVECTOR_LLS_URL, value: "$PGVECTOR_URL"}
            - {name: FAISS_LLS_URL, value: "$FAISS_URL"}
            - {name: QDRANT_LLS_URL, value: "$QDRANT_URL"}
          ports:
            - {containerPort: 8080}
          volumeMounts:
            - {name: app-src, mountPath: /app-src}
          resources:
            requests: {cpu: 100m, memory: 256Mi}
            limits: {cpu: 500m, memory: 512Mi}
          readinessProbe:
            httpGet: {path: /, port: 8080}
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: app-src
          configMap: {name: chat-ui-app}
---
apiVersion: v1
kind: Service
metadata:
  name: chat-ui
  namespace: $NS
spec:
  selector: {app: chat-ui}
  ports:
    - {port: 8080, targetPort: 8080}
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: chat-ui
  namespace: $NS
spec:
  to: {kind: Service, name: chat-ui}
  port: {targetPort: 8080}
  tls: {termination: edge, insecureEdgeTerminationPolicy: Redirect}
EOF

echo "==> 롤아웃 대기"
oc rollout status deployment/chat-ui -n "$NS" --timeout=180s

HOST=$(oc get route chat-ui -n "$NS" -o jsonpath='{.spec.host}')
echo
echo "==> 완료: https://$HOST"
