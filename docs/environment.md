# 기본 환경 구축 및 검증 기록

작업일: 2026-10-22~23 (Asia/Seoul). API 유료 요청은 수행하지 않았다.

## 실제 설치 버전

| 항목 | 버전 |
|---|---|
| Python | 3.12.15, 프로젝트 .tools/python에 uv로 설치 |
| uv | 0.13.5, 프로젝트 .tools/uv.exe |
| SQLite | 3.53.1, Windows Python 표준 sqlite3 |
| Node.js / npm | 기존 설치 24.13.1 / 11.8.0 |
| FastAPI / Uvicorn | 0.159.1 / 0.54.0 |
| Pydantic | 2.14.1 |
| LangChain / LangGraph | 1.4.7 / 1.2.16 |
| langchain-openai / langchain-chroma | 1.7.2 / 1.1.0 |
| Chroma / OpenAI SDK | 1.5.9 / 3.36.1 |
| React / React DOM | 19.3.1 / 19.3.1 |
| TypeScript / Vite | 7.0.2 / 8.3.5 |
| @vitejs/plugin-react / Zod | 6.1.2 / 4.6.7 |

Python 의존성은 uv.lock, 프런트는 frontend/package-lock.json으로 고정한다.
프로젝트 환경을 사용하며 시스템 Python/PATH와 PowerShell 실행 정책은 영구 변경하지 않는다.
설치 스크립트의 메시지는 Windows PowerShell 5.1 인코딩 호환성을 위해 ASCII로 작성했다.

## 통과한 검증

- Python 가상환경 생성 및 의존성 설치
- ruff check: 성공
- pytest: 11개 통과
- TypeScript: 앱·Vite 설정 프로젝트 타입 검사 성공
- Vite: 프로덕션 빌드 성공
- npm 설치 시 감사 결과: 알려진 취약점 0건(해당 시점 조회 결과)
- SQLite: 12주문·14품목, PK/FK·수량 제약·읽기 전용·주문 없음/DB 오류 구분
- 초기화 2회 결과 불변, 별도 DB의 논리적 데이터 동일, 변조된 DB 덮어쓰기 거부
- 매개변수 바인딩: SQL 인젝션 형태 입력으로 다른 주문이 조회되지 않음
- 실제 FastAPI HTTP: /api/health, /api/orders/A06, / 및 빌드 JS 모두 성공
- Vite 개발 서버: / 화면·/api 프록시·가상 주문 조회 성공
- API 계약: A01/A05/A06/A999 실제 JSON을 프런트 Zod가 검증하고 잘못된 문자열 수량은 거부
- LangGraph: 작은 상태 그래프 실행 성공(상담 에이전트 구현은 아님)
- ChatOpenAI·임베딩 객체 생성 및 주문 도구 스키마 바인딩 성공(외부 요청 없음)
- Chroma: 외부 임베딩 모델 없이 작은 명시적 벡터의 저장·검색 성공
- PowerShell setup.ps1·uv.ps1: 구문 검사 성공, 설치 단계별 명령 개별 검증
- Docker: cs-pilot:local 이미지 빌드 성공. 컨테이너 UI/API·시드 검증·재시작 후 주문 결과 동일 확인
- Docker 안에서도 논리적 DB SHA-256이 Windows 결과와 일치

논리적 데이터 digest:

```text
87598fd1f6cb87441b2cc299c46b742eb0727ce0b283772f94fc11993e0c3f87
```

## 아직 수행하지 않은 작업

1일차 추가 작업 결과: 정책 3문서 수집·11규칙 묶음 검수, 평가 정의 24개, Pydantic/Zod 상담 API 계약과 6상태 예시를 추가했다. 테스트는 21개로 늘었으며 타입 검사·계약 검사·프런트 빌드가 통과했다. 실제 상담 요청은 아직 501이다. 기존 Docker 검증은 기본 환경 구축 시점 기록이며 이후 상담 계약 추가분의 이미지를 다시 배포하지 않았다.

- RAG 적재·검색 평가 (정책 수집·검수는 1일차 추가 작업에서 완료)
- 실제 OpenAI 인증·모델 사용 가능 여부·유료 생성/임베딩 호출
- 상담 LangGraph의 행동 선택·반복·조건 분기 구현
- 완성된 AI 응답·정책 출처 UI와 타입 연결
- 브라우저 화면 자동화/시각 검수
- Render 외부 배포와 GitHub CI 실제 실행

Docker 단일 서비스는 로컬에서 검증했다. 현재 개발 화면은 실제 가상 주문 조회를 제공하고,
정책·AI 기능은 준비 중으로 명시한다. 미구현 기능의 성공 결과를 가짜로 표시하지 않는다.

## 참고한 공식 자료

- uv 설치: https://docs.astral.sh/uv/getting-started/installation/
- uv Python 관리: https://docs.astral.sh/uv/concepts/python-versions/
- React TypeScript: https://react.dev/learn/typescript
- Vite: https://vite.dev/guide/
- Python sqlite3: https://docs.python.org/3.12/library/sqlite3.html
- OpenAI 모델: https://developers.openai.com/api/docs/models/gpt-6-luna
- ChatOpenAI: https://docs.langchain.com/oss/python/integrations/chat/openai
