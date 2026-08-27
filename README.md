# OpenShift AI 3.4 벡터 저장소 3종 지원 확인 데모

Red Hat OpenShift AI(RHOAI) 3.4의 Llama Stack이 지원하는 벡터 저장소 3종을 실제 클러스터에
배포해 동작을 검증하는 데모입니다.

| # | 벡터 저장소 | provider_type | 특징 |
| - | --- | --- | --- |
| ① | PostgreSQL + pgvector | `remote::pgvector` | 원격 벡터 저장, PostgreSQL의 ACID 트랜잭션/HA 상속 |
| ② | FAISS | `inline::faiss` | llama-stack 파드 프로세스 메모리 내부 인라인 검색 (CPU) |
| ③ | Qdrant | `remote::qdrant` | RHOAI 3.4 신규(Technology Preview), 하이브리드(vector+keyword) 검색 + 키워드 전용 검색 |

## Vector Store 특징

1. RHOAI 3.2부터 FAISS는 메타데이터 저장을 위해 PostgreSQL이 필수입니다. FAISS의 핵심 차별점은 외부 벡터DB 파드 없이 llama-stack 프로세스 메모리 내에서 직접 벡터 인덱스를 처리한다는 점입니다.
2. **Qdrant는 Inline을 지원하지 않습니다.** 반드시 remote(원격) 서비스로 배포해야 하며, RHOAI
   3.4에서 Technology Preview 상태입니다.

## 아키텍처

![벡터 저장소 3종 아키텍처 다이어그램](docs/architecture.svg)

```
rag-support-demo (네임스페이스)
├── inference-model-secret          # INFERENCE_MODEL/VLLM_URL → 아래 qwen-vllm
├── qwen-vllm (Deployment+Service+PVC, GPU 1장) # 공용 추론: Qwen2.5-3B-Instruct
├── ① pgvector 트랙
│   ├── pgvector-postgres (Deployment+Service+PVC+Secret, pgvector 확장 사전 설치)
│   └── LlamaStackDistribution/vs-pgvector  (ENABLE_PGVECTOR=true)
├── ② FAISS 트랙
│   ├── faiss-postgres (메타데이터 전용, 3.2+부터 필수)
│   └── LlamaStackDistribution/vs-faiss     (ENABLE_FAISS=true)
└── ③ Qdrant 트랙
    ├── qdrant (Deployment+Service+PVC, 벡터 저장)
    ├── qdrant-postgres (메타데이터 전용)
    └── LlamaStackDistribution/vs-qdrant    (ENABLE_QDRANT=true)
```

세 트랙 모두 임베딩은 `ENABLE_SENTENCE_TRANSFORMERS=true` (인라인 sentence-transformers,
`nomic-ai/nomic-embed-text-v1.5`)로 동일하게 맞춰서, **벡터 저장소 종류만 변수로 남깁니다.**

추론(생성)도 세 트랙이 공용 `qwen-vllm`(Qwen2.5-3B-Instruct, vLLM, GPU 1장) 하나를 같이 씁니다 —
`manifests/40-qwen-vllm.yaml`로 배포하고, `inference-model-secret`의 `INFERENCE_MODEL`/`VLLM_URL`을
이 서비스로 채워서 세 `LlamaStackDistribution`이 전부 같은 모델로 실제 답변을 생성합니다.

위 다이어그램의 인터랙티브 버전(요청 흐름 설명, 리소스 이름 표 포함)은
[`docs/architecture.html`](docs/architecture.html)에서 브라우저로 열어볼 수 있습니다.

### Llama Stack이 필요한 이유

애플리케이션 코드(`webapp/app.py`, `scripts/*.py`)는 pgvector·FAISS·Qdrant·vLLM을 직접 모릅니다 —
**Llama Stack 하나**가 그 넷을 provider로 숨기고, 코드는 `vector_stores.search(...)`와
`chat.completions.create(...)` 두 호출만 압니다. 애플리케이션 코드는 Llama Stack으로 백엔드를
추상화할 수 있습니다.

### `distribution.name: rh-dev`란?

LlamaStackDistribution CR의 spec.server.distribution.name: rh-dev는 Red Hat이 RHOAI용으로 인증한 배포판 이미지(odh-llama-stack-core-rhel9)를 사용하도록 지정되었습니다. 이 배포판에는 주요 Provider(Inference, Safety, Eval 등)가 미리 정의되어 있어, 트랙별로 필요한 벡터 IO 환경변수만 켜서 구성한 것입니다.

## 배포 방법

사전조건: `oc login` 상태일 것.

```bash
cd manifests
./deploy.sh
```

`deploy.sh`가 하는 일:
1. `rag-support-demo` 네임스페이스 생성
2. 더미 inference secret 생성
3. 3개 트랙의 Postgres/Qdrant Deployment 생성 + Ready 대기
4. 3개 `LlamaStackDistribution` CR 생성 + Ready 대기

배포 후 확인:

```bash
oc get llamastackdistribution -n rag-support-demo
# NAME          PHASE   ...
# vs-faiss      Ready
# vs-pgvector   Ready
# vs-qdrant     Ready
```

각 트랙에 실제로 어떤 vector_io provider가 등록됐는지는 파드 안에서 직접 확인할 수 있습니다:

```bash
oc exec -n rag-support-demo deploy/vs-pgvector -- python -c \
  "import urllib.request,json; r=json.load(urllib.request.urlopen('http://localhost:8321/v1/providers')); \
   print([p for p in r['data'] if p['api']=='vector_io'])"
```

## 데모 실행

Windows 워크스테이션 등 클러스터 밖에서는 각 서비스가 ClusterIP라 직접 접근할 수 없으므로,
클러스터 안에서 실행되는 Job으로 데모 스크립트를 돌립니다(Route/port-forward 불필요).

```bash
cd scripts
./run-demo.sh
```

`run-demo.sh`가 하는 일: 스크립트/샘플 문서를 ConfigMap으로 올리고, 3개 LlamaStackDistribution의
`serviceURL`을 조회해 Job에 주입한 뒤, `oc logs`로 결과를 출력합니다.

### 실행되는 스크립트

| 스크립트 | 내용 |
| --- | --- |
| `ingest.py` | 동일한 한국어 고객지원 문서 10건을 3개 트랙에 각각 적재(업로드→청킹→임베딩) |
| `demo_pgvector.py` | 의미 검색 + **PostgreSQL 트랜잭션 보장 시연**(의도적 실패 INSERT → ROLLBACK → 행 수 불변 확인) |
| `demo_faiss.py` | 반복 질의 지연시간(latency) 측정 — 별도 벡터DB 파드 없이 파드 내부 메모리에서 검색 |
| `demo_qdrant.py` | 동일 질의를 `search_mode="vector"/"keyword"/"hybrid"` 3가지로 비교 |
| `compare_report.py` | 3개 트랙의 등록된 provider_type과 지원 검색모드를 표로 요약 |

### 샘플 데이터

`data/docs/`에 있는 한국어 고객지원 FAQ 10건(배송 조회, 배송비 환불, 반품/환불, 결제 수단,
회원가입, 회원 탈퇴, 쿠폰, AS/수리, 계정 보안, 주문 취소). `shipping-tracking.md`(배송 조회)와
`shipping-fee-refund.md`(배송비 환불)는 "배송"이라는 키워드는 겹치지만 의미가 다르도록 의도적으로
구성해, Qdrant의 키워드 검색과 의미 검색의 차이를 보여줍니다.

## 브라우저 챗 UI

CLI 스크립트 대신 브라우저에서 질의를 직접 입력하고 3개 트랙 결과를 나란히 비교하고 싶다면
`webapp/`의 작은 FastAPI 앱을 배포합니다. `scripts/ingest.py`로 문서 적재가 끝난 상태여야 합니다.

```bash
cd webapp
./deploy.sh
```

`deploy.sh`가 하는 일: 앱 코드를 ConfigMap으로 올리고, 3개 LlamaStackDistribution의 `serviceURL`을
주입한 `Deployment` + `Service` + `Route`를 만듭니다(RHOAI 콘솔/Grafana와 같은 방식으로 공개
URL을 얻습니다 — VPN 불필요, 일반 브라우저로 접속). 배포가 끝나면 URL을 출력합니다:

```
==> 완료: https://chat-ui-rag-support-demo.apps.myocp.sandbox623.opentlc.com
```

페이지에 질의를 입력하면 pgvector(vector 모드), FAISS(vector 모드), Qdrant(vector/keyword/hybrid
탭 전환 가능) 검색 결과를 카드 3개로 동시에 비교해서 보여주고, 각 카드는 검색된 상위 문서를 근거로
공용 `qwen-vllm`이 생성한 실제 답변도 함께 보여줍니다(Qdrant는 hybrid 모드 결과를 근거로 사용) —
즉 세 트랙 모두 완전한 RAG(검색+생성) 파이프라인입니다. 백엔드는 `scripts/common.py`와 동일한
로직(같은 이름 `support-docs-ko`의 vector store를 찾아 재사용, 임베딩 모델 자동 탐지)을
`webapp/app.py`에 자체 포함하고 있습니다.

## 실행 결과 (2026-08-26, myocp 클러스터에서 실측)

### 적재 결과

| track | completed | failed | elapsed |
| --- | --- | --- | --- |
| pgvector | 10 | 0 | 56.4s |
| faiss | 10 | 0 | 51.7s |
| qdrant | 10 | 0 | 44.2s |

### ① pgvector — 트랜잭션 보장

```
실제 임베딩이 저장된 테이블: vs_vs_60728cb5_..._... (컬럼 embedding: vector 타입) — 현재 20행
트랜잭션 내에서 의도적으로 실패하는 INSERT를 실행해 롤백을 확인합니다...
  예상대로 실패: UndefinedColumn: column "__demo_intentionally_bad_column__" of relation "..." does not exist
롤백 후 행 수: 20 (before=20) -> 변화 없음: ACID 트랜잭션 보장 확인
```

일반 `psycopg2` 클라이언트로 직접 접속해, 실패한 트랜잭션이 부분 반영 없이 완전히 롤백됨을
확인했습니다 — pgvector가 "그냥 PostgreSQL"이라는 것의 직접적 증거입니다.

### ② FAISS — 인라인 검색 지연시간

```
'배송 조회는 어떻게 하나요?': mean=207.6ms, min=181.9ms, max=260.7ms
'환불은 언제 받을 수 있나요?': mean=185.6ms, min=169.8ms, max=201.2ms
'회원 탈퇴하면 쿠폰은 어떻게 되나요?': mean=213.4ms, min=189.8ms, max=272.0ms
전체 평균 지연시간: 202.2ms (p95=260.7ms)
```

(이 수치는 클러스터 내부 Job → llama-stack 파드 HTTP 왕복을 포함한 값이라 절대적인 "인라인이라
더 빠르다"는 벤치마크는 아닙니다 — 핵심 증거는 지연시간이 아니라, `oc get deploy -n
rag-support-demo`에 pgvector/qdrant 트랙과 달리 **FAISS 트랙 전용 벡터DB 파드가 존재하지
않는다**는 구조적 사실입니다.)

### ③ Qdrant — 검색모드 3종 비교

질의: `"배송비 환불 규정이 궁금해요"`

| 순위 | vector | keyword | hybrid |
| - | --- | --- | --- |
| 1 | shipping-tracking (0.89) | coupon-usage (1.00) | shipping-fee-refund (0.84) |
| 2 | membership-withdrawal (0.86) | return-refund (1.00) | shipping-fee-refund (0.83) |
| 3 | shipping-fee-refund (0.84) | shipping-fee-refund (1.00) | as-repair (0.79) |
| 4 | shipping-fee-refund (0.83) | order-cancellation (1.00) | order-cancellation (0.79) |

세 모드가 서로 다른 결과를 낸다는 것 자체가 RHOAI 3.4의 "하이브리드 + 키워드 전용 검색"이
실제로 동작함을 보여줍니다. `keyword` 모드는 어휘 일치 문서에 점수 1.0을 균일하게 주는
전형적 BM25 계열 특성을 보였고, `hybrid`는 vector와 다른 순서로 재조합된 결과를 냈습니다.
(참고로 `vector`/`keyword` 단독 결과에는 질의 의도와 거리가 있는 문서도 섞여 있는데, 이는
데모용 소형 임베딩 모델(`nomic-embed-text-v1.5`)과 문서 10건이라는 작은 코퍼스 크기 때문이며
벡터 저장소 자체의 문제가 아닙니다.)

### 최종 비교표 (`compare_report.py` 실제 출력)

```
트랙        등록된 provider_type    지원 search_mode
----------  ----------------------  -------------------------
① pgvector  remote::pgvector        vector만
② FAISS     inline::faiss           vector만
③ Qdrant    remote::qdrant          vector / keyword / hybrid
```

### 참고: 한국어 청킹 아티팩트

검색 결과 미리보기에 간간이 `�` 문자가 보이는데, 이는 서버 쪽 청킹이 토큰(BPE) 단위로 잘라
한글 멀티바이트 UTF-8 시퀀스 중간을 끊는 경우가 있어 생기는 표시상의 문제입니다(`file_ingestion_params.
default_chunk_size_tokens: 512`). 검색 정확도나 벡터 저장소 동작 자체에는 영향이 없습니다.

## 트러블슈팅 메모 (배포 중 실제로 겪은 문제와 해결)

- **Qdrant가 `Permission denied`로 CrashLoop**: OpenShift의 restricted SCC(임의 비루트 UID)에서는
  이미지 내부 `/qdrant/snapshots` 등에 쓰기 권한이 없습니다. `QDRANT__STORAGE__SNAPSHOTS_PATH`를
  PVC가 마운트된 `/qdrant/storage` 아래로 지정해 해결했습니다.
- **`QdrantVectorIOConfig: port ... unable to parse string as an integer`**: 서비스 이름이
  `qdrant`이면 쿠버네티스가 자동으로 `QDRANT_PORT=tcp://<ip>:6333` 형태의 Docker-links 스타일
  환경변수를 주입해, run.yaml의 `${env.QDRANT_PORT}`(정수 기대)와 충돌합니다. `QDRANT_PORT`를
  명시적으로 `"6333"`으로 덮어써서 해결했습니다.
- **`Only one of <location>, <url>, <host> or <path> should be specified`**: `QDRANT_HOST`와
  `QDRANT_URL`을 동시에 넣으면 발생합니다. `QDRANT_URL` 하나만 사용해야 합니다.
- **`Model 'None' not found`**: `vector_stores.create()`는 임베딩 모델을 자동으로 고르지 않습니다.
  `client.models.list()`로 `model_type == "embedding"`인 모델(`nomic-ai/nomic-embed-text-v1.5`)을
  찾아 `extra_body={"embedding_model": ...}`로 명시해야 합니다(`scripts/common.py` 참고).
- **API 서버가 갑자기 통째로 응답 안 함(2026-08-27)**: `myocp`는 OpenTLC 샌드박스라 밤새 EC2
  인스턴스가 전부 자동으로 `stopped` 됩니다(마스터/워커/GPU/bastion 전부). `aws ec2
  describe-instances --profile ocp-sandbox3 --region us-east-1`로 상태 확인 후
  `aws ec2 start-instances`로 재시작하면 되는데, 컨트롤플레인이 완전히 재기동해 `oc login`이
  다시 성공하기까지 10분 넘게 걸릴 수 있습니다(그 사이엔 TLS handshake timeout → EOF → "must
  provide credentials" 순으로 에러가 바뀌며 서서히 살아납니다). PVC 데이터는 EBS라 재시작해도
  보존됩니다 — 실제로 이 데모의 적재된 문서 30건(3트랙×10건)도 그대로 남아 있었습니다.
- **qwen-vllm이 `PermissionError: [Errno 13] Permission denied: '/.cache'`로 크래시**: `HOME`
  환경변수가 없으면(OpenShift 컨테이너 기본값은 `/`) vllm/flashinfer가 `/.cache/...` 아래에
  캐시를 쓰려다 restricted SCC의 임의 비루트 UID 때문에 권한 오류로 죽습니다. `HOME`을 PVC
  마운트 경로(`/data/hf-cache`)로 명시해서 해결했습니다 — Qdrant 때와 같은 종류의 문제입니다.
- **`Model 'qwen2.5-3b' not found`(chat.completions 호출 시)**: llama-stack은 `/v1/models`에
  provider_id를 접두한 전체 id로 모델을 등록합니다(`vllm-inference/qwen2.5-3b`). `INFERENCE_MODEL`
  env var에는 짧은 이름(`qwen2.5-3b`)을 쓰지만, `chat.completions.create(model=...)` 호출에는
  반드시 `client.models.list()`로 확인한 전체 id를 넘겨야 합니다(`webapp/app.py`의
  `MODEL_NAME` 참고).

## 클러스터 정리

이 데모가 만든 리소스를 모두 지우려면:

```bash
oc delete namespace rag-support-demo
```
