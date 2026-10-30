# 단일 서비스 배포 준비

구현/검증일 2026-10-30. 로컬 Docker Linux 이미지에서 확인했다. 원격 서비스 생성·레지스트리 push·실제 배포 URL 검증은 아직 하지 않았다. [검증 원본](deployment-verification-2026-10-30.json)

## 이미지와 시작 흐름

1. Node 단계: npm ci → TypeScript 타입 검사 → Vite 빌드.
2. Python 단계: uv.lock으로 개발 의존성을 제외해 설치 → app/scripts·주문 SQL·artifacts 복사 → `python -m scripts.start --prepare-only`.
3. 준비 함수: 고정 시드로 DB 생성 또는 검증 → 청크/명세 로드 → 기존 벡터를 Chroma에 복원 또는 검증. 문서 임베딩 API는 호출하지 않는다.
4. 최종 이미지: Python 환경·가상 DB/Chroma·원본 고정 아티팩트·React 정적 산출물을 포함한다. Node 개발 서버는 실행하지 않는다.
5. 컨테이너 시작: 포트/UI 확인 → 데이터 준비 재확인 → 현재 프로세스를 단일 Uvicorn 서버로 교체. `/`, `/assets`, `/api`를 한 서비스에서 제공한다.

핵심 코드는 [prepare_runtime](../app/runtime.py)과 [시작 명령](../scripts/start.py)이다. 준비는 Uvicorn 실행 전에 끝나므로 이 배포 명령에서는 데이터 준비 실패 중 HTTP가 먼저 열리지 않는다. 기존 app.main의 직접 uvicorn 개발 실행은 DB 검증만 하므로, 배포 시에는 Dockerfile의 시작 명령을 그대로 사용한다. 공개 API/health 응답 필드는 변경하지 않았다. health는 매 요청마다 정책 벡터 전체를 재검증하거나 OpenAI 연결을 확인하는 기능은 아니다.

DB·정책이 이미 맞으면 재사용하고 기존 DB를 반복 INSERT하지 않는다. 데이터가 없으면 같은 고정 자료에서 복원한다. 잘못된 DB, 다른 모델/차원, 손상된 청크/벡터는 기존 검증에서 실패하며 임의 덮어쓰기/삭제나 유료 재임베딩으로 우회하지 않는다. 주문 API는 계속 매개변수 바인딩과 읽기 전용 연결을 사용한다.

## 로컬 실행

```powershell
docker build -t cs-pilot .
docker run --rm -p 127.0.0.1:8001:8000 cs-pilot
```

http://127.0.0.1:8001 에서 확인한다. 기본 PORT는 8000이며 다른 컨테이너 포트는 예를 들어 `-e PORT=8123 -p 127.0.0.1:8001:8123`로 지정한다. PORT가 정수가 아니거나 1~65535 범위를 벗어나면 서버를 열지 않는다. 설정한 포트와 Docker 포트 매핑은 함께 맞춘다.

기본 컨테이너에는 키를 넣지 않으므로 UI/주문/데이터 준비는 동작하지만 실제 AI 상담은 비활성이다. 로컬 `.env`를 이미지에 포함하지 않는다. 실제 상담을 켤 때만 실행 환경의 OPENAI_API_KEY와 AGENT_ALLOW_API=true, RAG_ALLOW_API=true를 설정한다. 고정 인덱스 복원은 무료지만 신규 질문 임베딩과 답변 생성은 API를 사용한다. 이번 로컬 컨테이너 검증에는 실제 키를 주입하지 않았다.

## 원격 배포 시 사용할 설정

기존 설계의 Render Docker Web Service를 기준으로 다음 값을 사용한다. 이번에는 원격 배포를 실행하지 않았다.

| 설정 | 값 |
|---|---|
| 서비스 유형 | Web Service / Docker |
| Dockerfile / build context | 저장소 루트의 Dockerfile / 루트 |
| Docker Command | 별도 재정의하지 않고 Dockerfile CMD 사용 |
| Health Check Path | /api/health |
| PORT | 플랫폼 제공값 사용. 코드가 0.0.0.0에 바인딩 |
| 워커 | 1. 시작 준비는 워커 실행 전에 한 번 |
| OPENAI_API_KEY | 서버 secret 환경변수. 빌드 인자·프런트 VITE_ 변수에 넣지 않음 |
| AGENT_ALLOW_API / RAG_ALLOW_API | 실제 상담을 허용할 때만 모두 true |
| ORDERS_DB_PATH | 기본 data/runtime/orders.sqlite3 유지 |
| 임베딩 모델 | 고정 아티팩트와 일치하는 text-embedding-3-small / 1536차원 |

Render는 Dockerfile CMD와 PORT 기반 바인딩을 지원한다. [Docker 배포 공식 문서](https://render.com/docs/docker), [포트/health 설정](https://render.com/docs/web-services)

Render의 로컬 파일은 재시작/재배포 때 유지된다고 가정하지 않는다. 이 MVP는 읽기 전용 가상 주문과 고정 정책으로 재구성하므로 별도 영구 디스크를 요구하지 않는다. 질문 임베딩 캐시는 사라질 수 있고 같은 신규 질의의 재임베딩 비용은 별개다. 무료 플랜의 가용 조건·사용량은 배포 시 대시보드에서 확인한다. [파일시스템 관련 공식 문서](https://render.com/docs/free)

## 실제 검증 결과

| 검사 | 2026-10-30 결과 |
|---|---|
| Docker Linux 빌드 | 성공. 잠금 의존성 설치, React typecheck/build, 고정 데이터 생성/복원 포함 |
| 키 없는 시작 | 정상. 주문 12건/14품목, 정책 11개, 임베딩 백엔드 호출 0회 |
| UI/JS/CSS/health | HTTP 200. PORT=8123을 로컬 18080으로 매핑해 확인 |
| 주문/알 수 없는 API | A06의 1:N 조회가 로컬 기준과 일치, A999는 not_found, 없는 /api는 404 |
| 상담 POST | 키 비활성의 200/system_error와 도구 호출 없음, 잘못된 입력 422. 실제 생성 품질 검사와 구분 |
| 재시작 | A06 응답, 논리적 DB 해시, 정책 지문/11개와 고정 벡터 조회가 재시작 전후 동일 |
| 빈 런타임 복원 | --network none + 빈 tmpfs에서 두 번 각각 12/14 및 벡터 11개 복원. 논리적 해시/지문 동일 |
| 오류 시 시작 중단 | 잘못된 PORT, 벡터 체크섬 손상 각각 실제 컨테이너에서 비정상 종료. 준비 완료/HTTP 서버 시작으로 넘어가지 않음 |
| 호스트 비밀값/런타임 제외 | 이미지에 .env·원문 정책 폴더·개인 학습·호스트 node_modules 없음 확인. .dockerignore도 보강 |
| 자동 회귀 | pytest 91개(새 시작 경로 11개 포함), Ruff·별도 npm check:contracts 통과 |

고정 벡터를 질의 벡터로 넣은 조회는 복원/저장 무결성 검사이며 새로운 자연어 질문의 의미 검색 평가가 아니다. 이번에는 OpenAI 유료 API 0회다. 이미지 ID·데이터 해시·실행한 조건은 원본 JSON에 보존했다. 컨테이너 재시작이 이미지 재빌드나 원격 배포까지 검증했다는 뜻은 아니다.

검증 전용 컨테이너는 제거했고 로컬 이미지 cs-pilot:runtime-check는 남겼다. 기존 8000 개발 서버는 변경하지 않았다. Docker 엔진은 CLI로 시작했다. 시스템/의존성 버전이나 Docker Desktop 설정은 변경하지 않았다.

## 남은 단계

- 현재 변경 검토와 커밋/PR 범위 정리, 최신 상담 지침의 전체 평가 결과 구분.
- 배포 대상 계정/설정에서 실제 원격 빌드와 시작, HTTPS URL의 UI/자산/API/health/재시작 확인.
- 브라우저 입력·로딩·오류·출처 이동과 새로고침 확인. 실제 AI 호출은 필요 사례만 따로 수행하고 비용을 기록.

참고한 공식 구현 자료: [FastAPI 컨테이너](https://fastapi.tiangolo.com/deployment/docker/), [uv Docker 통합](https://docs.astral.sh/uv/guides/integration/docker/). 기존 uv 0.13.5와 잠금 파일을 유지했다.
