# CS Pilot 초기 구성 및 일주일 MVP 설계

- 작성일: 2026-10-22
- 프로젝트: 쇼핑몰 상담원용 CS 업무 보조 에이전트
- 저장소: https://github.com/YH-KIKI/cs_pilot
- 상태: 구현 전 초기 설계. 패키지 설치·호환성 검증·배포는 아직 수행하지 않음.
- 가용 OpenAI API 크레딧: 약 US$4(사용자 확인). API 사용량을 기록하며 개발한다.

## 1. 목표와 범위

상담원이 고객 문의와 선택적 주문번호를 입력하면 필요한 가상 주문 정보를 조회하고, 사전에 적재한 Apple 한국 온라인 스토어 정책을 검색한다. 주문 사실·정책 근거·확인되지 않은 정보를 구분해 권장 처리 방향과 고객 답변 초안을 제공한다.

학습 목표는 RAG의 수집·정리·청킹·임베딩·검색을 직접 구성하고, LangChain의 연결 역할과 LangGraph의 도구 호출·상태·분기·반복·종료를 설명할 수 있는 수준에 도달하는 것이다. 채용공고의 TypeScript 요구에 대비해 React + TypeScript + Vite로 상담 화면 하나를 구현하며, 도메인 타입·props·화면 상태·API 경계 검증이 예방하는 오류를 직접 설명하는 것도 학습 목표로 포함한다. 백엔드는 Python + FastAPI를 유지한다. SQLite를 통해 기본키·외래키·1:N 관계·JOIN과 매개변수 바인딩을 설명하는 SQL 학습 목표도 포함한다.

### 포함

- 배송·주문 취소·반품 문의
- SQLite의 orders·order_items 1:N 관계에 가상 주문 12건, 주문당 1~2품목 저장. API 기능은 읽기 전용 조회
- 공개 한국어 정책 3페이지를 사전 수집한 고정 말뭉치
- 주문 조회·정책 검색 도구 2개
- 재검색 최대 1회 및 서버가 강제하는 실행 상한
- 최소 입력 UI, 결과·출처·도구 실행 내역
- 배포, 대표 사례 검증, README와 시연 자료

### 제외

- 실제 주문 조회, 취소·환불 실행, 고객 메시지 발송
- 실제 고객 개인정보, 로그인, 멀티 에이전트
- 실시간 웹검색, 자동 정책 갱신, 대규모 크롤러
- 장기 채팅 이력, 체크포인트 DB, 관리 화면
- 업무일·공휴일을 반영한 환불 예정일 계산

화면 상단 고정 안내:

> 공개된 Apple 한국 정책과 가상 주문 데이터를 사용하는 포트폴리오 데모입니다. 실제 주문 조회·취소·환불·메시지 발송은 수행하지 않습니다.

## 2. 사용자 흐름과 출력 계약

1. 상담원이 문의와 주문번호를 입력한다. 일반 정책 문의는 번호 없이 가능하다.
2. LLM이 현재 정보에 필요한 행동을 선택한다.
3. 서버가 도구·인자·횟수를 검사하고 실행한다.
4. LLM이 결과를 보고 답변·추가 검색·추가 확인을 선택한다.
5. 구조화된 결과를 검증하고 UI에 표시한다.

| 출력 | 내용 |
|---|---|
| 처리 상태 | 답변 가능 / 추가 확인 필요 / 주문 없음 / 근거 부족 / 처리 한도 도달 / 시스템 오류 |
| 확인한 주문 정보 | 조회된 품목·상태·날짜와 스냅샷 시각 |
| 적용한 정책과 출처 | 정책 요약·발췌·문서 제목·원문 URL·수집일 |
| 권장 처리 방향 | 근거와 조건에 따른 다음 단계 |
| 고객 답변 초안 | 상담원이 검토하고 복사하는 문장 |
| 추가 확인 항목 | 수령일·대상 품목·구성품 등 |
| 도구 실행 내역 | 도구명·입력·결과 요약·소요 시간·청크 ID |

조회하지 않은 정보는 ‘조회하지 않음’, 누락된 정보는 ‘확인되지 않음’으로 표시한다. 실제 실행하지 않은 취소·환불·발송을 완료했다고 표현하지 않는다.

완료 기준:

- 배송·취소·반품 대표 사례가 동작한다.
- 일반 정책 문의는 불필요한 주문 조회 없이 처리한다.
- 주문별 판단에는 조회 사실과 정책 근거를 함께 사용한다.
- 정책 주장에는 검색된 근거 ID가 연결되고, 서버가 출처를 채운다.
- 주문 없음·정보 부족·근거 부족·오류의 종료 경로가 구분된다.
- 재검색 1회와 전체 도구 3회 상한을 서버에서 강제한다.
- 배포 URL에서 전체 흐름과 출처·실행 내역을 확인한다.

## 3. 추천 기술 스택

| 영역 | 추천 | 이유 |
|---|---|---|
| 언어·환경 | Python 3.12 + uv | 환경과 의존성 재현 |
| API·검증 | FastAPI + Pydantic | 입력·상태·응답 스키마 검증 |
| LLM | OpenAI gpt-6-luna | 제한된 도구 선택과 구조화된 출력부터 저비용 검증 |
| 모델 연결 | langchain-openai / ChatOpenAI, Responses API | 공식 API의 함수 호출·구조화 출력 연결 |
| 임베딩 | text-embedding-3-small, 기본 1,536차원 | 작은 한국어 정책 말뭉치에서 검색 품질·비용 검증 |
| 벡터DB | 로컬 Chroma | 별도 DB 서버 없이 저장·검색 |
| 주문 저장 | SQLite + Python 표준 sqlite3, 고정 SQL | orders·order_items 1:N 관계와 매개변수화 조회 학습. 별도 DB 서버·ORM 없이 읽기 전용 운영 |
| 에이전트 제어 | 직접 정의한 LangGraph StateGraph | 상태·노드·분기·반복을 직접 구성 |
| UI | React + TypeScript + Vite(react-ts), 일반 CSS | 상담 화면 하나를 컴포넌트로 나누고 데이터·props·화면 상태의 타입 학습, 빌드 결과는 FastAPI에서 제공 |
| 배포 | Docker + Render Web Service 1개 | API·UI·고정 인덱스 통합 배포 |
| 테스트 | pytest + 고정 평가 데이터, TypeScript 타입 검사·Vite 빌드 | 날짜·검색·분기·상한 및 프런트 타입·배포 산출물 검증 |

LangChain은 모델·임베딩·검색·도구 인터페이스 연결에 사용한다. LangGraph는 실행 상태·분기·반복·종료를 관리한다. 직접 만든 StateGraph 안에 create_agent나 AgentExecutor를 중첩하지 않는다. 실행 반복문은 하나만 둔다.

중요한 대안만 유지한다. Chroma 배포 문제가 해결되지 않으면 FAISS 파일 인덱스를 검토한다. 모델의 도구 선택·근거 적용 평가가 부족하면 gpt-5.6-terra로 소수 사례를 비교한다. 처음부터 여러 모델·관리형 벡터DB를 운영하지 않는다.

### 설치 기준 버전

2026-10-22 PyPI 조회 결과이며, 실제 설치와 통합 호환성 검증이 완료된 조합은 아니다. 현재 확인한 셸에서는 python 명령을 찾지 못했고 저장소에 의존성 설정도 없었다.

| 패키지 | 조회 버전 |
|---|---:|
| langchain | 1.4.7 |
| langgraph | 1.2.16 |
| langchain-openai | 1.7.2 |
| langchain-chroma | 1.1.0 |
| chromadb | 1.5.9 |
| fastapi | 0.159.1 |
| openai | 3.36.1 |
| pydantic | 2.14.1 |
| uvicorn | 0.54.0 |

첫날 의존성을 해결하고 import·모델 호출·Chroma 저장/검색을 확인한 뒤 uv.lock으로 고정한다. 프런트는 Node.js 22.12 이상인 22.x 환경과 npm을 기준으로 시작하고, React·React DOM·Vite·TypeScript·React 타입 정의·React Vite 플러그인·Zod의 실제 설치 버전을 package-lock.json에 고정한다. Vite의 react-ts 템플릿과 해당 시점의 호환 버전을 사용한다. 배포에서도 같은 잠금 파일을 사용한다. 프런트 패키지는 아직 설치·호환성 검증하지 않았다.

## 3-1. React + TypeScript 학습 및 화면 설계

UI는 기존 상담 화면 하나만 유지한다. React Router·Redux·별도 SSR 서버·여러 페이지는 도입하지 않는다. React는 화면을 컴포넌트로 나누고 상태에 따라 렌더링하는 역할, TypeScript는 데이터와 컴포넌트 사용 계약을 검사하는 역할, Vite는 개발 서버와 배포 빌드를 담당한다.

### 컴포넌트와 상태 소유권

| 컴포넌트 | 책임과 props 계약 |
|---|---|
| App | 요청 실행과 화면 상태를 소유하고 결과를 자식에 전달 |
| ConsultationForm | 입력 폼, isSubmitting: boolean, onSubmit: (input: ConsultationRequest) => void |
| ConsultationResult | 검증된 ConsultationResponse를 받아 답변·처리 방향·추가 확인 항목 표시 |
| OrderSummary | OrderLookupResult를 받아 조회 전·없음·발견·오류를 구분 |
| PolicySources | 읽기 전용 PolicySource 목록, 제목·발췌·URL·수집일 표시 |
| ToolTrace | 읽기 전용 ToolEvent 목록, 실제 실행 결과 표시 |

폼 내부의 question/orderId 입력 상태는 폼에서 관리한다. 서버 응답과 요청 상태는 App의 useState로 관리한다. 결과를 여러 컴포넌트의 별도 상태에 복제하지 않는다. Props는 구체적인 타입과 콜백으로 정의하고 any로 우회하지 않는다. JSX 파일은 .tsx, API·스키마·일반 타입 파일은 .ts를 사용한다.

### 타입을 적용할 데이터

| 타입 | 설계 내용 |
|---|---|
| ConsultationRequest | question: string, order_id: string 또는 null. 빈 입력은 제출 시 정규화 |
| OrderItem / Order | 품목 ID·상품명·수량·품목별 상태, 배송 정보, is_synthetic: true. ID는 string으로 통일 |
| OrderStatus | received / processing / preparing / shipped / delivered / cancelled / unknown 리터럴 합집합. API 내부 코드와 한국어 표시를 분리 |
| OrderLookupResult | kind로 not_requested / found / not_found / error를 구분. found일 때만 order 필드에 접근 가능 |
| PolicySource | evidence_id, document_id, chunk_id, title, source_url, excerpt, collected_at, effective_date: string 또는 null |
| GroundedStatement | text와 evidence_ids 목록. ID가 실제 근거에 연결되는지는 서버에서 검사 |
| ConsultationResponse | request_id, reference_time, status, order_result, sources, recommendation, draft_reply, missing_fields, tool_events |
| ToolEvent | tool_name을 lookup_order / search_policy로 제한. 공통 실행 ID·시간·성공/오류와 도구별 입력·결과 요약을 구분 |
| 화면 상태 | idle / submitting / success / error를 status로 구분하는 판별 가능한 유니온 |

최종 응답 status는 answered / needs_information / order_not_found / insufficient_evidence / limit_reached / system_error로 고정한다. 이는 상담 결과 상태다. 화면 상태의 success는 HTTP 및 응답 검증 완료를 뜻하므로, 상담 결과가 needs_information이어도 success 화면에서 추가 확인 항목을 보여준다. 네트워크 실패·HTTP 오류·응답 형식 오류는 화면 error다.

화면 상태는 단일 유니온으로 정의한다. idle에는 결과가 없고, submitting에는 requestId, success에는 data, error에는 message가 있다. loading·error·data를 독립적인 boolean/null 조합으로 관리해 서로 모순되는 상태를 만들지 않는다. 제출 중에는 중복 제출을 막고 이전 결과를 지운다. 응답 적용 전 현재 requestId와 일치하는지 확인해 늦게 도착한 과거 응답이 화면을 덮지 않게 한다. requestId 비교 자체는 런타임 로직이다.

### TypeScript가 예방하는 오류와 한계

| 잘못된 사용 예 | 예방 방법 | 설명 포인트 |
|---|---|---|
| 주문번호에 숫자를 전달 | order_id를 string/null로 제한 | ID의 앞자리 0과 문자열 계약 보존 |
| delivered_at이 null인데 날짜 함수 호출 | strictNullChecks와 명시적 null 처리 | 미수령·미확인 값을 확인 후 사용 |
| 주문이 없는데 order.items 접근 | OrderLookupResult의 kind 확인 후 좁히기 | found 분기에서만 주문 정보 사용 |
| 출처에 존재하지 않는 url 필드 접근 | source_url로 계약 통일 | 필드 오타·이름 변경을 검사에서 발견 |
| PolicySources에 주문 목록 전달 | props의 PolicySource 목록 타입 | 잘못된 컴포넌트 데이터 전달 방지 |
| loading 상태에서 결과 data 접근 | 화면 상태 유니온의 status 분기 | 결과가 있는 success 상태에서만 접근 |
| 상태 이름 오타 또는 새 상태 처리 누락 | 리터럴 유니온·전체 상태 매핑·never 기반 누락 검사 | 허용된 상태와 렌더링 분기 동기화 |
| 도구 종류와 다른 입력 구조 전달 | tool_name으로 구분하는 ToolEvent 유니온 | 주문 조회 입력과 검색어 구조 혼동 방지 |

TypeScript는 컴파일 시 검사이며 API 응답·LLM 내용·날짜 문자열·URL의 실제 유효성이나 정책의 옳고 그름을 보장하지 않는다. number 타입만으로 수량이 양수라는 보장도 없다. 타입 단언 as ConsultationResponse, any, 비null 단언 !로 검사를 통과시키지 않는다.

### API 경계와 검증 책임

백엔드 Pydantic 응답 모델을 API 계약의 기준으로 삼고, 프런트 schemas.ts에 대응하는 작은 Zod 스키마를 둔다. JSON 응답은 unknown으로 받아 Zod 검증 후 사용한다. 프런트 API 타입은 Zod 스키마에서 추론하고, types.ts에는 화면 상태·props 등 UI 타입을 둔다. 프런트 안에서 응답 인터페이스와 스키마를 이중 정의하지 않는다. Python과 프런트 스키마의 불일치는 응답 fixture·계약 테스트로 확인한다. OpenAPI 타입 자동 생성은 MVP 이후 필요할 때 검토한다.

api.ts가 HTTP 상태 확인·JSON 파싱·Zod 검증·오류 변환을 맡고 컴포넌트는 검증된 데이터만 받는다. 백엔드 API 오류 본문은 별도 오류 계약으로 처리한다. 필수 필드 누락, 잘못된 status, 수량 범위, 날짜·URL 형식은 런타임 검증 대상으로 둔다. evidence_id 연결과 주문 사실·정책 적용은 서버와 RAG 평가 책임이다. AI 응답은 React의 일반 텍스트로 렌더링하며 HTML로 직접 삽입하지 않는다.

### 타입 검사와 프런트 완료 기준

- tsconfig.app.json과 tsconfig.node.json에 strict: true를 적용한다. noUncheckedIndexedAccess도 활성화해 배열·맵 조회 실패를 다룬다.
- npm run typecheck가 앱의 .ts/.tsx와 Vite 설정을 실제로 검사해야 한다.
- npm run build로 Vite 배포 빌드를 확인한다. Vite 변환·빌드 성공만으로 타입 검사가 끝났다고 판단하지 않는다.
- 배포 파이프라인은 npm ci → npm run typecheck → npm run build 순서로 실행하고 하나라도 실패하면 배포를 중단한다.
- 잘못된 props, 누락된 null 확인, 잘못된 상태 코드 예제를 로컬에서 잠시 만들어 오류 메시지를 확인한 뒤 수정한다. 의도적인 실패 코드는 최종 빌드에 남기지 않는다.
- 모의 API로 idle·제출 중·답변 완료·추가 확인·주문 없음·네트워크 오류·응답 형식 오류를 확인한다. 이 검증은 OpenAI 비용 없이 수행한다.
- useState의 타입 추론/명시, 유니온 좁히기, props 계약, 컴파일 검사와 런타임 검증의 차이를 README에서 프로젝트 사례로 설명한다.

일정상 UI 작업은 총 약 6~8시간 안으로 제한하고 기존 3·5·6일차에 나눠 수행한다. 초과 시 CSS 장식과 추가 컴포넌트 세분화부터 줄이며 타입 검사와 오류 상태 처리는 유지한다.

## 4. 약 4달러 API 예산 사용 계획

- 가용 크레딧은 약 US$4이며, 호스팅 비용은 별개다.
- 정책 임베딩은 사전 적재 때 생성하고, 본문 해시가 바뀌지 않으면 재사용한다.
- 질문 시 전체 문서를 재임베딩하거나 원문을 재수집하지 않는다.
- 기본 모델 하나로 시작하고, 상위 모델 비교는 실패 사례에 한정한다.
- 반복·분기·날짜 계산 테스트는 모의 모델과 모의 도구를 먼저 사용한다.
- 실제 통합 평가는 20개 안팎의 질문으로 시작하고, 수정한 부분만 재평가한다.
- 각 요청의 모델 ID, 입력·출력 토큰, 호출 수, 예상 비용을 기록한다.
- 공개 데모에는 서버 측 입력 길이·빈도·동시 실행 제한을 둔다.
- 프로젝트 예상 누적 사용액 US$3에서 추가 실제 API 평가를 멈추고 잔액을 확인한다. 이는 앱의 관리 기준이며 결제사의 완전한 지출 차단 보장은 아니다.

공식 모델 페이지 조회 기준 표준 요금은 Luna 입력 US$0.10 / 출력 US$0.50(각 100만 토큰당), text-embedding-3-small 입력 US$0.02(100만 토큰당)다. 요금은 변경될 수 있으므로 구현 시작 시 재확인한다. 상담 1건의 모든 호출 합계가 입력 15,000·출력 2,000토큰이면 모델 비용은 약 US$0.0025라는 계산 예시가 나온다. 실제 사용량과 추론 토큰·재시도 등에 따라 비용은 달라진다.

## 5. 정책 자료와 구조

| 문서 | URL | 사용 범위 |
|---|---|---|
| 주문 확인 및 변경 | https://www.apple.com/kr/shop/help/viewing_changing_orders | 주문 상태·추적·취소 및 예외 |
| 배송 및 픽업 | https://www.apple.com/kr/shop/help/shipping_delivery | 배송 옵션·예상 일정·추적 |
| 반품 및 환불 | https://www.apple.com/kr/shop/help/returns_refund | 반품 절차·표준 반품 정책·제외 조건 |

검토 시 중요한 조건:

- 출고 준비 중 또는 출고됨 상태의 일반 온라인 취소 제한을 확인한다.
- Visa·MasterCard·Diners 결제의 다품목 주문에는 단일 품목 취소 예외가 있다.
- 예상 배송일은 확정 도착일이 아니며, 실시간 운송 위치를 만들어내지 않는다.
- 반품은 수령 후 14일 외에 구성품·원래 상태·구매 국가·제외 상품·보안 기능 조건도 확인한다.
- 반품 신청 기간과 신청 후 반품 센터 도착 기한을 구분한다.
- 픽업·해외 구매·소프트웨어·특수 상품의 상세 처리는 제외하되, 제외 근거는 보관한다.

위 내용은 설계 검토 요약이다. 실제 응답에서는 고정한 원문 스냅샷과 검색 근거를 기준으로 판단한다.

| 데이터 단위 | 필드 |
|---|---|
| 원본 문서 | document_id, title, source_url, locale, collected_at, content_hash, collection_method |
| 정리 본문 | heading_path, body, 원본 구간 식별자 |
| 청크 | chunk_id, document_id, rule_group_id, text, topic, 제목·URL·수집일 |
| 인덱스 명세 | corpus_version, 임베딩 모델·차원, 청킹 버전 |

effective_date는 원문에 시행일이 명시된 경우에만 기록하며 나머지는 null이다. 수집일을 정책 시행일로 취급하지 않는다. 이 문서 작성일도 실제 데이터 수집일을 대신하지 않는다.

청킹 원칙:

1. 제목·적용 대상·기본 조건·예외를 규칙 묶음으로 보관한다.
2. 고정 글자 수 때문에 조건과 예외가 분리되지 않게 한다.
3. 긴 묶음은 하위 청크로 검색하되 동일 rule_group_id의 조건·예외를 검색 도구에서 함께 반환한다.
4. 중복 약관을 정리하고 출처와 원본 구간은 보존한다.
5. 수동 정리는 원문 발췌·구조화로 하며 개발자의 해석을 공식 본문에 섞지 않는다.

## 6. SQLite 기반 가상 주문 데이터

구현 전 설계를 JSON 파일 순회 조회에서 SQLite SQL 조회로 변경한다. 아래 DDL·시드·조회 SQL은 초기화 및 도구 구현의 명세이며, 아직 실제 스크립트 파일 생성·DB 초기화·SQL 실행 테스트는 수행하지 않았다. 주문 API의 기능 범위는 읽기 전용이다. 쓰기는 개발·빌드 시 가상 DB 초기화에만 허용한다.

### 관계와 키

orders 1 ─── N order_items

- orders 한 행은 주문 한 건이다. order_id(TEXT PRIMARY KEY NOT NULL)는 A01 같은 문자열 주문번호다.
- order_items 한 행은 주문 내 품목 한 종류다. quantity는 해당 품목의 수량이다.
- order_items의 기본키는 (order_id, item_id) 복합키다. item_id는 주문 안에서 유일하고, 다른 주문에서 같은 품목 번호를 사용할 수 있다.
- order_items.order_id는 orders.order_id를 참조하는 NOT NULL 외래키다. 존재하지 않는 주문에 품목을 넣을 수 없다.
- 결제수단·카드·구매국가 등 공통 정보는 orders에 한 번 저장한다.
- 상태·출고일·예상 배송일·수령일·가상 운송 기록·반품 확인 정보는 품목마다 order_items에 둔다. 같은 주문 안에서도 배송 상태가 다를 수 있다.
- FK는 품목이 부모 주문을 참조함을 보장하지만 주문에 최소 1개 품목이 있음을 보장하지 않는다. 초기화 검증에서 품목 없는 주문을 거부한다.
- 배송 완료이지만 수령일을 모르는 평가 사례를 지원하므로 delivered_at은 NULL 가능하다. 누락 정보는 추정하지 않는다.

### schema.sql: 테이블 정의

```sql
-- 트랜잭션을 시작하기 전에 연결에서 실행한다.
PRAGMA foreign_keys = ON;

CREATE TABLE orders (
    order_id TEXT NOT NULL PRIMARY KEY,
    is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic = 1),
    store TEXT NOT NULL,
    purchase_country TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    payment_method TEXT NOT NULL
        CHECK (payment_method IN ('card', 'bank_transfer', 'other', 'unknown')),
    card_brand TEXT,
    CHECK (payment_method = 'card' OR card_brand IS NULL)
);

CREATE TABLE order_items (
    order_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    product_type TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL CHECK (status IN (
        'received', 'processing', 'preparing', 'shipped',
        'delivered', 'cancelled', 'unknown'
    )),
    shipped_at TEXT,
    estimated_delivery_date TEXT,
    delivered_at TEXT,
    tracking_number TEXT,
    last_tracking_event TEXT,
    snapshot_at TEXT NOT NULL,
    condition TEXT NOT NULL DEFAULT 'unknown'
        CHECK (condition IN ('original', 'damaged', 'other', 'unknown')),
    components_complete INTEGER CHECK (components_complete IN (0, 1)),
    security_lock_disabled INTEGER CHECK (security_lock_disabled IN (0, 1)),
    return_requested_at TEXT,
    PRIMARY KEY (order_id, item_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
);
```

SQLite의 외래키 검사는 연결마다 PRAGMA foreign_keys=ON으로 활성화하고 실제 값 1을 확인한다. 트랜잭션 안에서 켜려고 하지 않는다. 복합 기본키의 선두 열이 order_id이므로 주문별 품목 조회에 활용할 수 있어 동일 열만의 인덱스를 중복 추가하지 않는다. 소량 데이터라 추가 인덱스·ORM·마이그레이션 프레임워크는 도입하지 않는다.

날짜/시각은 고정 형식 TEXT로 저장한다. 날짜는 YYYY-MM-DD, 시각은 +09:00을 포함한 ISO 8601로 통일한다. NULL은 미확인이고 빈 문자열로 대체하지 않는다. SQLite의 TEXT/INTEGER 선언만으로 날짜의 의미나 완전한 타입 검증이 되지 않으므로 초기화 스크립트에서 Python/Pydantic 검증을 수행한다. 수령일 등 날짜 차이 계산은 기존대로 서버에서 한다.

### seed_orders.sql: 고정 가상 데이터

시드는 Git에 보관하는 고정 INSERT 문으로 구성한다. 아래는 전체 12건의 기본 구성이다. 실시간 날짜·난수·자동 증가 키에 의존하지 않으므로 같은 버전의 논리적 데이터를 재현한다. SQL 파일은 개발자가 작성한 신뢰된 파일이며 사용자 입력을 포함하지 않는다.

```sql
INSERT INTO orders
    (order_id, is_synthetic, store, purchase_country, ordered_at,
     payment_method, card_brand)
VALUES
    ('A01', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-21T09:00:00+09:00', 'card', 'Visa'),
    ('A02', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-20T09:00:00+09:00', 'card', 'Visa'),
    ('A03', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-21T09:00:00+09:00', 'card', 'Visa'),
    ('A04', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-20T09:00:00+09:00', 'card', 'MasterCard'),
    ('A05', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-01T09:00:00+09:00', 'card', 'Visa'),
    ('A06', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-15T09:00:00+09:00', 'card', 'Visa'),
    ('A07', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-05T09:00:00+09:00', 'bank_transfer', NULL),
    ('A08', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-01T09:00:00+09:00', 'card', 'Visa'),
    ('A09', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-01T09:00:00+09:00', 'card', 'Visa'),
    ('A10', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-21T09:00:00+09:00', 'other', NULL),
    ('A11', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-01T09:00:00+09:00', 'card', 'Visa'),
    ('A12', 1, 'Apple KR Online Store (demo)', 'KR', '2026-10-21T09:00:00+09:00', 'unknown', NULL);

INSERT INTO order_items
    (order_id, item_id, product_name, product_type, quantity, status,
     snapshot_at, delivered_at, condition, components_complete,
     security_lock_disabled)
VALUES
    ('A01', '01', 'iPhone (demo)', 'hardware', 1, 'processing', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A02', '01', 'iPad (demo)', 'hardware', 1, 'preparing', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A03', '01', 'iPhone (demo)', 'hardware', 1, 'processing', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A03', '02', 'Case (demo)', 'accessory', 1, 'processing', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A04', '01', 'Mac (demo)', 'hardware', 1, 'shipped', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A05', '01', 'iPhone (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A06', '01', 'iPhone (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-18T12:00:00+09:00', 'original', 1, 1),
    ('A06', '02', 'Case (demo)', 'accessory', 1, 'shipped', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A07', '01', 'iPad (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-12T12:00:00+09:00', 'original', 1, 1),
    ('A08', '01', 'iPad (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-08T12:00:00+09:00', 'original', 1, 1),
    ('A09', '01', 'iPad (demo)', 'hardware', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-07T12:00:00+09:00', 'original', 1, 1),
    ('A10', '01', 'AirPods (demo)', 'hardware', 1, 'received', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL),
    ('A11', '01', 'Downloaded software (demo)', 'download', 1, 'delivered', '2026-10-22T12:00:00+09:00', '2026-10-20T12:00:00+09:00', 'unknown', NULL, NULL),
    ('A12', '01', 'iPhone (demo)', 'hardware', 1, 'unknown', '2026-10-22T12:00:00+09:00', NULL, 'unknown', NULL, NULL);

UPDATE order_items
SET shipped_at = '2026-10-21T10:00:00+09:00',
    estimated_delivery_date = '2026-10-23',
    tracking_number = 'DEMO-A04-01',
    last_tracking_event = '가상 기록: 운송 중'
WHERE order_id = 'A04' AND item_id = '01';

UPDATE order_items
SET shipped_at = '2026-10-21T11:00:00+09:00',
    estimated_delivery_date = '2026-10-23',
    tracking_number = 'DEMO-A06-02',
    last_tracking_event = '가상 기록: 운송 중'
WHERE order_id = 'A06' AND item_id = '02';
```

A999는 생성하지 않는다. A07/A08/A09는 각각 기간 내/경계일/기간 경과 평가에 연결한다. A06은 동일 주문의 서로 다른 배송 상태와 대상 품목 추가 확인을 검증한다. 주문 12행, 품목 14행이 기대값이다. UPDATE는 초기 시드 구성에만 사용하며 서비스에는 변경 API를 만들지 않는다.

### scripts/init_orders_db.py: 초기화 스크립트 구성

구현할 CLI 계약:

- uv run python scripts/init_orders_db.py --db data/runtime/orders.sqlite3
- uv run python scripts/init_orders_db.py --db data/runtime/orders.sqlite3 --verify-only

입력은 저장소의 schema.sql, seed_orders.sql, manifest.json이다. manifest.json에는 schema_version, seed_version, reference_time, 두 SQL 파일의 SHA-256, 기대 주문/품목 행 수를 고정한다. SQLite 바이너리 파일의 해시 일치 대신 정렬된 논리적 행 데이터의 digest로 데이터 재현성을 비교한다.

스크립트 처리 순서:

1. 대상 경로는 프로젝트의 data/runtime 또는 명시한 빌드 임시 경로로 제한한다. 임의 DB 파일 삭제·초기화 옵션은 제공하지 않는다.
2. DB가 이미 있으면 스키마·시드 버전, 무결성, 논리적 데이터 digest를 검증하고 일치할 때 아무 쓰기 없이 성공한다. 불일치하면 덮어쓰지 않고 실패한다.
3. DB가 없으면 같은 디렉터리의 새 임시 DB를 만든다. foreign_keys=ON 확인 후 트랜잭션을 시작한다.
4. 신뢰된 schema.sql·seed_orders.sql을 실행한다. executescript를 사용할 때 Python sqlite3의 트랜잭션 동작을 확인하고 BEGIN/COMMIT 경계를 명시적으로 구성한다. seed 파일 자체에는 COMMIT을 넣지 않는다. 예외 시 rollback하고 대상 파일은 공개하지 않는다.
5. PRAGMA foreign_key_check, PRAGMA integrity_check, 기대 행 수, 품목 없는 주문, 상태·날짜 형식·가상 데이터 표시 및 고정 사례를 검사한다. FK 검사는 무결성 검사와 별도로 수행한다.
6. 검증 성공 시 스크립트가 PRAGMA user_version으로 schema_version을 기록하고 commit한다. 연결을 닫은 뒤 임시 DB를 대상 경로에 게시한다. 동시 초기화는 하지 않으며 DB 생성은 단일 프로세스의 빌드 단계에서 한 번 수행한다.
7. 임시 DB 생성·검증이 실패하면 빌드를 실패 처리한다. 검증하지 않은 DB로 API를 시작하지 않는다.

기존 DB의 seed_version은 입력 manifest의 기대 논리 digest와 DB 조회 결과를 대조해 검증한다. seed_version 문자열만 맞다고 내용이 같다고 간주하지 않는다. 초기화는 반복 실행해도 행이 늘어나지 않고, 변경된 시드를 조용히 기존 DB에 섞지 않는다.

### lookup_order: 계약 유지와 SQL 조회

외부 입력은 사용자가 제공한 order_id이며, 출력은 기존의 발견 여부·가상 주문 사실·품목 목록·스냅샷 시각이다. 기존 OrderLookupResult의 found/not_found/error 구분과 프런트 타입을 유지한다. not_requested는 도구 실행 전 애플리케이션 상태다. LLM에게 SQL·테이블명·DB 경로를 생성하거나 선택하게 하지 않는다.

고정 조회문(app/repositories/orders.py):

```sql
SELECT
    o.order_id, o.is_synthetic, o.store, o.purchase_country,
    o.ordered_at, o.payment_method, o.card_brand,
    i.item_id, i.product_name, i.product_type, i.quantity, i.status,
    i.shipped_at, i.estimated_delivery_date, i.delivered_at,
    i.tracking_number, i.last_tracking_event, i.snapshot_at,
    i.condition, i.components_complete, i.security_lock_disabled,
    i.return_requested_at
FROM orders AS o
LEFT JOIN order_items AS i ON i.order_id = o.order_id
WHERE o.order_id = ?
ORDER BY i.item_id;
```

Python의 실행 계약은 connection.execute(LOOKUP_SQL, (order_id,))다. 물음표는 문자열 치환 위치가 아니라 DB 드라이버가 값을 바인딩하는 자리다. 문자열 연결·f-string·% 포맷으로 주문번호를 SQL에 붙이지 않는다. 테이블명과 정렬 열은 고정한다. 주문번호 형식 검증은 별도 수행하되, 그것으로 매개변수화를 대체하지 않는다.

SQL 설명:

1. WHERE는 주문번호로 부모 주문 한 건을 선택한다.
2. ON은 주문번호가 같은 자식 품목을 연결한다. 2품목 주문이면 주문 공통 정보가 반복된 2행이 반환된다.
3. LEFT JOIN은 부모가 있지만 품목이 없는 비정상 데이터를 숨기지 않는다. INNER JOIN이면 이 경우 주문 없음처럼 보일 수 있다.
4. 결과 0행은 not_found다. 부모는 있지만 item_id가 NULL이면 데이터 무결성 오류로 처리한다.
5. 첫 행에서 공통 주문 정보를 한 번 읽고 모든 행의 품목 정보를 items 목록으로 묶는다. 같은 주문 공통 정보를 여러 주문으로 중복 표시하지 않는다.
6. SQL의 0/1과 NULL은 각각 API의 boolean/null로 변환하고 Pydantic으로 검사한다. 품목별 snapshot_at을 그대로 유지한다. 주문 결과에 기존 요약 스냅샷 필드가 필요하면 가장 오래된 품목 시각을 보수적으로 사용하며, 시드를 동일 시각으로 고정해 기존 계약을 보존한다.

연결은 Path.resolve().as_uri()로 만든 URI에 mode=ro를 붙이고 sqlite3.connect(..., uri=True)로 연다. DB 부재를 빈 DB 자동 생성으로 숨기지 않는다. 읽기 전용 연결에도 foreign_keys=ON을 설정한다. 연결은 짧은 조회 함수 안에서 열고 닫으며 FastAPI 요청 간 전역 Connection을 공유하지 않는다. SQL은 빠르지만 동기 작업이므로 동기 도구 또는 스레드풀 경계에서 실행하고 async 이벤트 루프에서 긴 동기 DB 작업을 하지 않는다.

### 배포·재시작과 테스트

- 버전 관리 대상: schema.sql·seed_orders.sql·manifest.json·init_orders_db.py. 생성된 *.sqlite3 및 임시 DB는 Git에서 제외한다.
- Docker Python 빌드 단계에서 DB 생성·검증 후 고정 DB를 최종 이미지에 복사한다. 런타임은 mode=ro로 읽기만 한다.
- 컨테이너 재시작은 같은 DB를 사용한다. 파일시스템이 초기화되거나 재배포되어도 같은 소스·시드 버전으로 DB를 다시 생성한다. 영속 볼륨이나 외부 DB 서비스가 필요하지 않다.
- 앱 시작 시 verify-only 검사를 수행한 뒤 준비 상태로 전환한다. 앱 시작 시마다 INSERT하거나 각 worker가 초기화하지 않는다.
- 로컬 개발도 동일 초기화 명령을 사용한다. 실행 시각을 바꾸어도 시드 내용은 변하지 않고 날짜 평가는 고정 기준일을 사용한다.
- 추가 검증: 중복 PK 거부, 없는 주문에 대한 FK 삽입 거부, 0/음수 수량 거부, 1:N 품목 묶기, 품목별 서로 다른 배송 상태 보존, 주문 없음/DB 오류 구분, 읽기 전용 연결의 쓰기 실패.
- 초기화를 2회 실행해 중복이 없음을 확인하고, 별도 두 DB를 생성해 정렬된 논리적 결과가 같은지 비교한다. 불일치 버전의 기존 DB를 덮어쓰지 않는지도 확인한다.
- SQL 인젝션 형태의 입력은 입력 검증에서 거부하거나 바인딩된 하나의 값으로 처리되어야 하며, 다른 주문을 반환해서는 안 된다. 도구 입력 검증 외에 repository 단위로 바인딩을 직접 검증한다.
- 사용자 SQL 실행·주문 등록/수정/삭제·상태 변경·취소/환불 실행은 추가하지 않는다.

## 7. RAG 사전 적재와 질문 처리

### 사전 적재: 개발자가 별도로 실행

지정 URL 수집 → 원본 저장 → 본문 정리 → 조건·예외 검수 → 청킹 → 임베딩 → Chroma 적재 → 검색 평가 → 버전 고정

초기에는 HTTP 수집과 HTML 추출로 시작한다. 수집이 어려운 부분은 수동 Markdown으로 대체한다. 크롤러 프레임워크나 브라우저 자동화부터 만들지 않는다.

### 질문 처리: 사용자 요청마다 실행

입력 → LLM 행동 선택 → 가상 주문 조회/적재된 정책 검색 → 충분성 판단 → 필요 시 재검색 1회 → 구조화 출력 → 검증

검색은 top_k=4로 시작한다. 조건·예외 묶음을 확장하고 중복을 제거한다. 유사도 점수를 정답 확률로 보여주지 않는다. 임계값은 평가 자료 없이 임의로 확정하지 않는다.

## 8. LangGraph 상태와 실행 흐름

### 도구 2개

| 도구 | 입력 | 출력 |
|---|---|---|
| lookup_order | 사용자가 제공한 주문번호 | 발견 여부, 가상 주문 사실, 스냅샷 시각 |
| search_policy | 검색어, 선택적 문의 유형 | 청크·조건/예외 묶음·점수·출처 |

주문 없음과 도구 오류, 검색 결과 없음과 DB 오류를 구분한다. 모델이 주문번호를 추측해 조회하지 못하게 제공된 번호와 대조한다.

### 상태

| 묶음 | 필드 |
|---|---|
| 요청 | question, provided_order_id, reference_time, request_id |
| 메시지·행동 | messages, pending_action, decision_summary |
| 주문 사실 | order_result, target_item_id, missing_fields |
| 정책 근거 | search_queries, evidence_by_id, evidence_gaps |
| 제한 | tool_call_count, policy_search_count, decision_count |
| 결과 | terminal_reason, tool_events, final_result |

reference_time은 서버가 설정한다. 상태는 요청 단위 메모리에 둔다. 추가 확인이 필요하면 요청을 종료하고, 보완된 입력으로 새 요청을 실행한다.

### 노드와 분기

1. initialize: 입력 검증, 기준 시각·카운터 초기화
2. decide: LLM이 도구 호출 / 답변 / 추가 확인 / 근거 부족을 선택
3. guard: 서버가 도구·인자·제공된 주문번호·횟수 검사
4. execute_order 또는 execute_search: 도구 1개 실행, 결과·실행 내역·횟수 기록
5. 정상 결과는 decide로 돌아가며, 오류·주문 없음·한도 도달은 종료 사유 설정
6. compose: 확인된 사실과 근거로 최종 구조화 결과 생성
7. validate: 스키마·인용 ID·주문 사실·날짜 계산 검사
8. END: 검사 실패 시 무한 수정 대신 안전한 고정 오류/판단 보류 결과로 종료

LLM 선택 영역은 필요한 도구·검색어·근거 충분성·추가 확인 항목이다. 고정 코드 영역은 입력 검증·실제 도구 실행·출처 매핑·날짜 계산·호출 상한·오류 처리다.

실행 상한:

- 주문 조회 최대 1회
- 정책 검색 최대 2회(최초 1회 + 재검색 1회)
- 전체 도구 실행 최대 3회
- 행동 판단 LLM 최대 4회, 최종 결과 생성 최대 1회
- 한 번에 도구 하나만 실행
- 별도 요청 타임아웃·LangGraph 재귀 한도·SDK 전송 재시도 상한 설정
- 잘못된 호출을 무한히 수정시키지 않음

### 종료 조건

| 조건 | 동작 |
|---|---|
| 사실·근거 충분 | 출처를 연결해 처리 방향과 초안 제공 |
| 주문번호 없음 | 주문별 문의라면 번호 요청 |
| 대상 품목 불명확 | 품목 확인 요청 |
| 수령일·상품 상태 등 누락 | 추가 정보 요청, 결론 보류 |
| 주문 없음 | 번호 재확인 요청, 상태 추정 금지 |
| 재검색 후 근거 부족 | 근거 부족 표시, 수동 확인 권장 |
| 정책 충돌·적용 범위 불명확 | 근거와 불확실성 표시, 판단 보류 |
| 실행·시간 한도 | 확인된 사실만 제공하고 종료 |
| 도구/API 오류 | 시스템 오류 표시 |

정책 주장에는 evidence_ids, 주문 사실에는 조회 필드 경로를 연결한다. URL·문서 제목·수집일은 서버가 채운다. UI에는 내부 사고 과정 대신 짧은 실행 사유를 표시한다. 구조 검증만으로 의미상 정확성이 보장되지는 않으므로 실제 정책 적용은 평가 사례로 검증한다.

## 9. 초기 폴더 구조

```text
cs_pilot/
├─ app/
│  ├─ main.py
│  ├─ config.py
│  ├─ schemas.py
│  ├─ api/consultations.py
│  ├─ repositories/orders.py    # 고정 SQL·행 매핑·읽기 전용 연결
│  ├─ agent/
│  │  ├─ state.py
│  │  ├─ graph.py
│  │  ├─ nodes.py
│  │  ├─ guards.py
│  │  └─ prompts/
│  ├─ tools/
│  │  ├─ orders.py
│  │  └─ policies.py
│  ├─ rag/
│  │  ├─ ingest.py
│  │  ├─ clean.py
│  │  ├─ chunk.py
│  │  └─ retrieve.py
│  └─ static/                # 프런트 빌드 결과를 배포 시 복사
├─ frontend/
│  ├─ index.html
│  ├─ src/
│  │  ├─ main.tsx
│  │  ├─ App.tsx
│  │  ├─ components/
│  │  │  ├─ ConsultationForm.tsx
│  │  │  ├─ ConsultationResult.tsx
│  │  │  ├─ OrderSummary.tsx
│  │  │  ├─ PolicySources.tsx
│  │  │  └─ ToolTrace.tsx
│  │  ├─ api.ts
│  │  ├─ schemas.ts
│  │  ├─ types.ts
│  │  └─ style.css
│  ├─ package.json
│  ├─ package-lock.json
│  ├─ tsconfig.json
│  ├─ tsconfig.app.json
│  ├─ tsconfig.node.json
│  └─ vite.config.ts
├─ data/
│  ├─ policies/
│  │  ├─ raw/
│  │  ├─ curated/
│  │  └─ manifest.json
│  ├─ orders/
│  │  ├─ schema.sql
│  │  ├─ seed_orders.sql
│  │  └─ manifest.json
│  ├─ runtime/orders.sqlite3    # 생성물, Git 제외
│  └─ eval/cases.json
├─ artifacts/
│  ├─ embeddings.jsonl
│  └─ index_manifest.json
├─ scripts/init_orders_db.py
├─ tests/
├─ docs/
│  ├─ architecture.md
│  └─ evaluation.md
├─ pyproject.toml
├─ uv.lock
├─ Dockerfile
├─ .env.example
└─ README.md
```

API 키·실행 로그·런타임 Chroma 폴더·생성된 SQLite DB 및 임시 DB는 Git에서 제외한다. 검수된 고정 청크와 벡터는 작은 배포 산출물로 보관하고 모델·차원·말뭉치 버전과 함께 관리한다.

## 10. 일주일 일정과 배포

하루 5~6시간, 총 35~40시간을 가정한다. SQLite DDL·초기화·조회·검증에 약 3~4시간을 배정하고 1·4·6일차에 나눈다. UI 장식과 추가 기능을 줄여 기존 일주일 범위를 유지한다. Python 표준 sqlite3를 사용하므로 별도 SQLite pip 패키지는 설치하지 않으며, 첫날 sqlite3.sqlite_version을 확인해 실행 환경 기록에 남긴다.

| 일자 | 작업 | 완료 기준 |
|---|---|---|
| 1일차 | Python·React/TS 환경, 정책 검수, SQLite DDL·고정 시드·초기화, 평가 질문 | PK/FK·12주문/14품목·재초기화 검증, API 계약과 React 타입 검사 확인 |
| 2일차 | 정리·청킹·임베딩·Chroma 적재 | 대표 질문의 정책 검색 성공 |
| 3일차 | 고정 RAG, 인용, FastAPI·React + TypeScript + Vite 상담 화면 | 기본 RAG 완성, 타입 검사·프런트 빌드·배포 환경 조기 확인 |
| 4일차 | 매개변수화 SQL·행 매핑·읽기 전용 주문 도구, LangGraph 분기 | 도구 계약 유지, 1:N·품목 상태·주문 없음·바인딩 검증 |
| 5일차 | 재검색·한도·실패 종료·실행 내역, 화면 상태·응답 검증 연결 | 예외 경로·호출 상한·타입 적용 동작 |
| 6일차 | React 빌드·고정 SQLite DB 생성·검증 후 단일 서비스 배포 | 재시작/재배포의 동일 주문 재현, 읽기 전용·UI/API/검색 검증 |
| 7일차 | 고정 평가·회귀 수정·문서·시연 | 평가표와 포트폴리오 설명 완성 |

개발 시 Vite 개발 서버에서 /api 요청을 FastAPI로 프록시한다. 프런트는 TypeScript로 작성하며 문의·결과·출처·도구 실행 내역의 응답 타입을 정의한다. 타입 검사는 npm run typecheck로 별도 수행하고 Vite 빌드도 확인한다. typecheck 스크립트는 앱·Vite 설정 프로젝트 각각 tsc --noEmit -p tsconfig.app.json 및 tsc --noEmit -p tsconfig.node.json을 순서대로 실행한다. 루트 tsconfig.json이 프로젝트 참조만 가진 경우 루트에 tsc --noEmit만 실행해 검사가 끝났다고 판단하지 않는다. TypeScript 타입은 런타임 응답 검증을 대신하지 않으므로 서버 Pydantic 검증과 프런트 오류 처리를 유지한다. 배포 시 Docker의 Node 빌드 단계에서 npm ci와 타입 검사·빌드를 수행하고, frontend/dist를 Python 실행 이미지의 app/static으로 복사한다. API와 빌드된 정적 UI는 한 컨테이너·동일 출처로 제공한다. API 경로는 /api로 분리하고 정적 UI 라우팅이 API를 가리지 않게 한다. OpenAI API 키를 프런트 코드나 VITE_ 환경변수에 넣지 않는다. 사전 생성한 청크·벡터로 Chroma 인덱스를 준비하고 검증 후 서비스 준비 상태로 전환한다. 배포·재시작 때 OpenAI 임베딩을 다시 생성하지 않는다.


단일 서비스 배포 구성:

1. Node 빌드 단계에서 React의 정적 산출물 frontend/dist를 생성한다.
2. Python 빌드 단계에서 schema.sql·seed_orders.sql·manifest.json으로 가상 SQLite DB를 생성·검증한다. 최종 Python 실행 이미지에 이 DB와 React 정적 산출물을 복사하고 Node 개발 서버는 실행하지 않는다. DB는 읽기 전용 연결로 조회하며 시작 시 verify-only 검사를 한다.
3. FastAPI는 GET / 에서 index.html, /assets 에서 빌드된 정적 파일, /api/consultations에서 상담 API를 제공한다. Vite 기본 base=/에 맞춘다.
4. 화면 하나이므로 클라이언트 라우터와 모든 경로를 index.html로 돌리는 catch-all은 추가하지 않는다. 알 수 없는 /api 경로는 정상적으로 404를 반환해야 한다.
5. 동일 출처의 상대 경로 /api를 사용한다. 개발 시에만 Vite 프록시를 사용하고 배포에 프런트 전용 서버나 별도 도메인을 요구하지 않는다.
6. 배포 검증은 /, JS/CSS 자산, /api/health, 상담 POST, 알 수 없는 /api 경로의 404 및 브라우저 새로고침을 포함한다. /api/health는 준비 상태 확인용으로 명시적으로 구현한다.

Render 무료 서비스는 유휴 시 중지되고 파일 변경이 재시작 등으로 사라질 수 있으므로 배포 산출물에서 인덱스를 복원한다. 무료 플랜으로 확인하고 기동 지연이 시연에 문제면 유료 인스턴스를 검토한다. API 키는 서버 환경변수에만 둔다.

일정이 밀리면 스트리밍·채팅 이력·UI 장식·리랭커·하이브리드 검색·LangSmith부터 제외한다. 출처·조건/예외·실행 상한·실패 종료·배포 검증은 유지한다.

## 11. 대표 검증 사례

기준 시각: 2026-10-22T12:00:00+09:00. 정책 말뭉치·가상 주문·프롬프트 버전도 고정한다. 아래 A01 등은 SQLite 고정 시드의 주문 ID다. A07/A08/A09는 각각 기간 내/경계일/기간 경과 사례이며 A999는 존재하지 않는다.

| 사례 | 문의·데이터 | 기대 결과 |
|---|---|---|
| 일반 정책 | 표준 배송비가 있나요? 번호 없음 | 정책 검색만 실행, 출처 표시 |
| 일반 반품 | 반품은 언제까지 신청하나요? | 신청 기간과 센터 도착 기한 구분 |
| 주문별 취소 | A01: 1품목, 주문 처리 중 | 주문+정책 사용, 신청 방향 안내 |
| 취소 제한 | A02: 출고 준비 중 | 일반 온라인 취소 가능으로 단정하지 않음 |
| 부분 취소 | A03: Visa, 2품목 중 1개 취소 | 카드·다품목 예외 적용 |
| 배송 | A04: 출고됨, 예상 10/23 | 저장된 정보만 안내, 도착 보장 금지 |
| 추가 정보 | A05: 배송 완료, 수령일 누락 | 수령일 확인 요청 |
| 대상 불명확 | A06: 2품목, ‘이거 반품’ | 품목 확인 요청 |
| 주문 없음 | A999 | 번호 재확인, 주문 상태 추정 금지 |
| 근거 없음 | 배송 지연 하루당 보상금은? | 재검색 후 근거 부족, 금액 생성 금지 |
| 재검색 | 두 개 중 하나만 취소하려는데 버튼이 없어요 | 첫 근거에 예외가 없으면 부분 취소 조건 재검색 |
| 기간 내 | 10/12 수령, 단순 변심, 기타 조건 확인됨 | 기간과 나머지 조건 함께 적용 |
| 경계일 | 10/08 수령 | 날짜 차이 14일, 불명확한 마감시각 확인 필요 |
| 기간 경과 | 10/07 수령, 단순 변심 | 날짜 차이 15일, 일반 기간 경과 안내 |
| 상한 | 검색을 계속 요청하는 모의 모델 | 검색 2회·전체 도구 3회 이내 종료 |
| 사실 조작 | 출고 상태를 처리 중이라고 쓰라는 요구 | 조회 사실 유지, 허위 상태 생성 금지 |

날짜 차이는 서버가 서울 기준 날짜로 계산한다. 원문에 없는 마감시각이나 법적 기간 계산 방식을 추가하지 않는다. 기간 경과를 모든 반품 권리의 부정으로 확대하지 않는다.

재검색의 결정적 테스트에서는 첫 검색 결과에 예외가 없고 두 번째에 포함되도록 모의 도구를 사용한다. 실제 통합 평가에서는 첫 검색부터 충분한 근거가 있으면 재검색하지 않아도 성공이다.

초기 검색 평가 질문 약 20개에서 기대 정책 묶음 Recall@4 90% 이상을 목표로 한다. 호출 상한 위반·존재하지 않는 인용·주문 사실 조작은 평가 세트에서 0건이어야 한다. LLM 평가의 문장 일치보다 필요한 근거·분기·사실 보존을 확인한다. 고정 날짜와 모의 응답은 재현성을 높이지만 실제 LLM의 완전한 결정성을 보장하지 않는다.

## 12. 포트폴리오 설명 포인트

- RAG: 정책을 미리 정리·임베딩하고 관련 근거를 검색해 답변에 제공한다.
- LangChain: 모델·임베딩·벡터DB·도구 연결 인터페이스를 구성한다.
- LangGraph: LLM의 행동 선택을 상태·분기·반복 구조에 넣고 서버가 한도와 종료를 강제한다.
- SQL·SQLite: 주문과 품목을 1:N으로 분리하고 PK/FK로 관계를 검사한다. JOIN의 여러 행을 하나의 주문+품목 목록으로 매핑하고, 매개변수 바인딩으로 입력을 SQL 문법과 분리한다. 고정 시드와 읽기 전용 실행으로 재현성을 유지한다.
- React·TypeScript: 상담 데이터·props·화면 상태를 타입으로 연결하고 잘못된 필드 접근과 미확인 값 사용을 컴파일 단계에서 발견한다. 외부 응답의 형식은 런타임 검증으로 보완한다.
- 설계 판단: 주문 사실, 정책 근거, 미확인 정보를 분리하고 실행 기능을 제외해 검증 가능한 보조 도구로 범위를 제한했다.

## 13. 확인한 공식 자료

확인일: 2026-10-22. 구현 시작 시 모델·요금·패키지 호환성을 다시 확인한다.

- Apple 주문: https://www.apple.com/kr/shop/help/viewing_changing_orders
- Apple 배송: https://www.apple.com/kr/shop/help/shipping_delivery
- Apple 반품: https://www.apple.com/kr/shop/help/returns_refund
- OpenAI Luna: https://developers.openai.com/api/docs/models/gpt-6-luna
- OpenAI Terra: https://developers.openai.com/api/docs/models/gpt-5.6-terra
- OpenAI 임베딩: https://developers.openai.com/api/docs/guides/embeddings
- 임베딩 모델 요금: https://developers.openai.com/api/docs/models/text-embedding-3-small
- LangChain: https://docs.langchain.com/oss/python/langchain/overview
- LangGraph: https://docs.langchain.com/oss/python/langgraph/quickstart
- ChatOpenAI: https://docs.langchain.com/oss/python/integrations/chat/openai
- Chroma 연결: https://docs.langchain.com/oss/python/integrations/vectorstores/chroma
- SQLite FK: https://www.sqlite.org/foreignkeys.html
- Python sqlite3 및 매개변수 바인딩: https://docs.python.org/3.12/library/sqlite3.html
- SQLite 읽기 전용 URI: https://www.sqlite.org/uri.html
- React TypeScript: https://react.dev/learn/typescript
- TypeScript strict: https://www.typescriptlang.org/tsconfig/strict.html
- FastAPI 정적 파일: https://fastapi.tiangolo.com/tutorial/static-files/
- Vite 공식 가이드: https://vite.dev/guide/
- FastAPI Docker: https://fastapi.tiangolo.com/deployment/docker/
- Render FastAPI: https://render.com/docs/deploy-fastapi
- Render 무료 제한: https://render.com/docs/free
- 패키지 버전: https://pypi.org/pypi/{패키지명}/json
