# CS Pilot

쇼핑몰 상담원용 CS 업무 보조 에이전트를 만드는 개인 학습 프로젝트입니다.
React + TypeScript + Vite / Python 3.12 + FastAPI / SQLite / LangChain + LangGraph를 사용합니다.

## 현재 구현 상태

- Python 가상환경, Python/npm 의존성 잠금 파일, 환경변수 예제
- React 상담 화면 하나와 strict TypeScript 검사, Zod 응답 검증
- SQLite `orders` : `order_items` = 1:N, 가상 주문 12건·품목 14건
- 고정 시드 초기화·검증 스크립트와 읽기 전용 매개변수화 SQL 조회
- FastAPI 상태 확인·주문 조회·React 정적 빌드 제공
- LangChain 주문 조회 도구, 테스트·CI 설정, 단일 서비스 Docker 구성
- 정책 원문 3페이지 수집·검수, 조건/예외를 보존한 11규칙 묶음
- 고정 기준일의 평가 질문 24개와 기대 결과
- 상담 API 계약(Pydantic·Zod·OpenAPI), 6상태 예시 및 계약 검사
- 규칙 단위 청킹·임베딩 캐시·Chroma 검색·출처와 관련 조건 반환
- 실제 정책 벡터 11개와 검색 평가, 고정 벡터 내보내기·API 없는 복원

**2일차 RAG 기반을 구현했습니다. LangGraph 상담 흐름·AI 답변·상담 화면 연결은 다음 단계입니다.**
`POST /api/consultations`는 현재 계약만 제공하며 유효 입력에도 명시적으로 501을 반환합니다.
가상 주문만 조회하며 실제 취소·환불·메시지 발송은 하지 않습니다.
기본 실행과 자동 테스트는 API를 호출하지 않습니다. 실제 신규 질문 임베딩은 키와 명시적 API 허용이 필요합니다. 첫 실제 검색 평가는 완료했으며 [결과와 한계](docs/evaluation.md)를 확인하세요.

## Windows 최초 설치

Node.js 22.12 이상이 필요합니다. 프로젝트의 `.tools`에 uv와 Python 3.12를,
`.venv`에 Python 패키지를 설치합니다. 시스템 PATH나 PowerShell 실행 정책을 영구 변경하지 않습니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

`.env`는 없을 때만 `.env.example`에서 복사합니다. API 키는 나중에 로컬 `.env`에 넣으세요.
키는 Git 및 `frontend`/`VITE_` 변수에 넣지 않습니다.
가상환경 활성화 없이 아래 명령을 사용할 수 있습니다.

## 실행

백엔드(프로젝트 루트):

```powershell
.\.venv\Scripts\python.exe -m scripts.init_orders_db
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

프런트 개발 서버(다른 터미널):

```powershell
cd frontend
npm.cmd run dev
```

- 개발 UI: http://127.0.0.1:5173 (`/api`는 8000으로 프록시)
- API 문서: http://127.0.0.1:8000/docs
- 상태: http://127.0.0.1:8000/api/health
- 가상 주문: http://127.0.0.1:8000/api/orders/A06
- 주문 없음: A999. 주문번호 A01~A12를 사용합니다.

프런트 빌드 후 FastAPI만 실행하면 http://127.0.0.1:8000 에서 UI도 제공합니다.
빌드 후에는 백엔드를 재시작하세요. 개발 중에는 5173을 사용합니다.

```powershell
cd frontend
npm.cmd run typecheck
npm.cmd run build
```

## 검증

루트에서:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uv.ps1 run ruff check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m scripts.init_orders_db --verify-only
.\.venv\Scripts\python.exe -X utf8 -m scripts.validate_day1
```

프런트에서 `npm.cmd run typecheck`, `npm.cmd run build`를 모두 실행합니다.
상담 계약은 `npm.cmd run check:contracts`로 서버 예시와 Zod 스키마를 대조합니다.
Vite 빌드 자체는 TypeScript 타입 검사 성공을 뜻하지 않습니다.

## SQLite 관계와 초기화

- `orders.order_id`: 주문 기본키. 주문 공통 결제 정보를 보관합니다.
- `order_items.(order_id, item_id)`: 주문 안의 품목 복합 기본키.
- `order_items.order_id`: 부모 주문을 참조하는 외래키. 연결마다 FK 검사를 켭니다.
- 상태·출고일·예상 배송일·수령일·기록 기준 시각은 품목 단위입니다.
- `LEFT JOIN`으로 주문과 품목을 읽고 여러 행을 `order.items`로 묶습니다.
- `WHERE o.order_id = ?`와 `(order_id,)` 바인딩을 사용하며 입력으로 SQL을 조립하지 않습니다.
- 런타임은 `mode=ro` 연결로 읽습니다. DB 부재와 주문 없음은 구분합니다.

소스는 `data/orders/schema.sql`, `seed_orders.sql`, `lookup_order.sql`, `manifest.json`입니다.
생성물 `data/runtime/orders.sqlite3`는 Git에서 제외합니다. 초기화는 기존 DB가 같으면
검증만 하고, 데이터가 바뀌어 있으면 덮어쓰지 않고 실패합니다.
시드를 의도적으로 변경할 때는 manifest의 해시·버전·기대 행 수도 함께 갱신하고
기존 DB를 별도 보관한 뒤 새 경로에 생성하세요.

재현 기준 시각: `2026-10-22T12:00:00+09:00`.
동일 소스에서 생성한 DB는 정렬된 논리적 행 데이터가 같습니다. 바이너리 해시는 재현 기준이 아닙니다.

## 배포

Docker는 React 타입 검사·빌드와 SQLite 초기화를 먼저 수행합니다.
최종 컨테이너는 FastAPI 한 서비스로 `/`, `/assets`, `/api`를 제공합니다.
Render에서는 Docker 서비스를 선택하고 `OPENAI_API_KEY`는 나중에 서버 환경변수로 지정합니다.
현재 단계에서는 키 없이 동작합니다. 컨테이너 시작 시 DB를 검증하며 매번 시드를 INSERT하지 않습니다.

```powershell
docker build -t cs-pilot .
docker run --rm -p 8000:8000 cs-pilot
```

Docker/원격 배포 검증 여부는 [환경 검증 기록](docs/environment.md)을 확인하세요.

## 학습 자료

- [RAG 구성과 API 없는 검증](docs/rag.md)

- [Git 운영 규칙](docs/git-workflow.md) · [에이전트 작업 지침](AGENTS.md)
- [일차별 개발 기록](docs/devlog/README.md) · [주요 판단·문제 해결](docs/decisions.md)
- [Python 학습 기록과 과제 운영 규칙](docs/learning/README.md)
- [초기 설계](docs/initial-design.md)
- [환경 검증 기록](docs/environment.md)
- [타입과 오류 예방](docs/typescript.md)
- [1일차 완료 기록](docs/day1-completion.md)
- [정책 검수](docs/policy-review.md)
- [평가 질문과 기대 결과](docs/evaluation.md)
- [상담 API 계약](docs/api-contract.md)

`uv.lock`과 `frontend/package-lock.json`은 커밋 대상으로 관리합니다.
이번 환경 구축에서는 Git 커밋·push나 외부 배포를 실행하지 않습니다.
