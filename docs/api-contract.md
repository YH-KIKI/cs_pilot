# 상담 API 계약 v1.0

기준 모델: `app/consultation_contract.py` (Pydantic).
프런트 대응 모델: `frontend/src/schemas.ts` (Zod + 추론 타입).
OpenAPI 스냅샷: `api-contract.openapi.json`.
예시: `data/contracts/examples.json`, fixture_only=true. 실제 AI 실행 결과가 아니다.

## POST /api/consultations

입력은 `question`(공백 제거 후 1~2000자), `order_id`(문자열 또는 null), `target_item_id`(문자열 또는 null)다. 주문번호·품목을 생략하면 null로 처리한다. 품목을 지정하려면 주문번호가 필요하다. 빈 주문번호는 프런트에서 null로 정규화한다. 정의하지 않은 입력 필드는 거부한다.

일반 정책 질문에는 주문번호가 필요하지 않다. 질문마다 참조 시각은 서버가 정하므로 클라이언트가 reference_time을 보내면 422다. 평가의 고정 시각은 서버 내부 주입으로 처리할 계획이며 공개 API에 테스트용 시각 변경 기능을 노출하지 않는다.

| HTTP 상태 | 계약 |
|---|---|
| 200 | 향후 에이전트가 반환할 ConsultationResponse. 현재는 반환하지 않음 |
| 422 | FastAPI 기본 HTTPValidationError, 입력 형식 오류 |
| 501 | 현재 구현의 ApiError: code=not_implemented, message |

`answered` 등 여섯 상담 결과는 실행 완료 시 HTTP 200 안의 업무 상태다. 정상 실행했지만 추가 정보가 필요한 상황과 HTTP/네트워크 장애를 구분한다. `system_error`는 향후 실행 중 도구 오류를 구조화한 상담 결과다. 처리되지 않은 서버 오류는 HTTP 5xx로 보고 프런트 오류 상태로 처리한다. 아직 상담 기능을 연결하지 않았으므로 유효 입력도 501로 종료하며 주문 도구·LLM·정책 검색을 실행하지 않는다.

## 응답 필드

| 필드 | 의미 |
|---|---|
| contract_version | 1.0 |
| request_id / reference_time | 요청 식별자 / 서버 기준 시각(시간대 포함) |
| status | answered / needs_information / order_not_found / insufficient_evidence / limit_reached / system_error |
| order_result | kind=not_requested/found/not_found/error. 조회 도구의 기존 found/not_found/error 계약 유지 |
| sources | 근거 ID·문서/규칙 ID·청크 ID·제목·섹션·URL·수집일·시행일·발췌 |
| applied_policies | 정책 주장 text + 필수 evidence_ids |
| recommendation | 권장 방향 text + evidence_ids. 번호 요청 같은 절차 안내는 빈 목록 가능 |
| draft_reply | 고객에게 전달할 초안 또는 null |
| missing_fields | field·item_id·상담원이 확인할 질문 |
| tool_events | 순번·도구명·실제 입력·실행 시간·성공/오류·요약, 검색은 근거 ID도 포함 |

하루 1일차에는 청크를 생성하지 않았으므로 출처 예시의 chunk_id는 null이다. 실제 검색 기능이 생기면 반환된 청크 ID를 채운다. 임의의 가짜 청크를 발급하지 않는다.

`collected_at`은 수집 시각이고 `effective_date`는 정책 시행일이다. 현재 말뭉치 시행일은 모두 null이다. 출처 메타데이터는 검색/문서 레지스트리에서 서버가 채우며 모델이 URL·수집일을 자유 생성하지 않는다.

## 검사하는 불변 조건

- evidence_id 중복과 존재하지 않는 근거 참조를 거부한다.
- answered에는 sources와 applied_policies가 필요하다.
- needs_information에는 적어도 하나의 missing_fields가 필요하다.
- order_not_found는 order_result.kind=not_found와 함께 사용한다.
- tool_events는 최대 3개, 주문 조회 1개·검색 2개 이하다. 순번은 1부터 연속이다.
- lookup_order와 search_policy는 서로 다른 input 타입을 사용한다.
- 위 조건은 Python·Zod에서 검사한다. 실행 전 도구 호출을 차단하는 guard는 향후 LangGraph 구현 작업이며, 응답 스키마 검사로 실행 상한이 이미 보장된다고 주장하지 않는다.
- ID 연결 검증만으로 정책의 의미·정당성까지 보장하지 않는다. 출처 메타데이터 대조와 실제 내용 검토가 별도로 필요하다.

## 타입 학습 연결

`ConsultationRequest`, `ConsultationResponse`, `PolicySource`, `ToolEvent`를 Zod에서 추론한다. ToolEvent는 tool_name, 주문 결과는 kind로 좁힌다. 프런트에서는 sources를 정책 출처 컴포넌트 props로, ConsultationResponse를 AI 결과 컴포넌트 props로 전달할 계획이다. 현재 화면의 주문 조회 상태/props 타입은 이미 동작하며, 미래 컴포넌트를 빈 구현으로 늘리지는 않았다.

서버 fixture를 프런트에서 읽고 타입만 확인하는 대신 Zod로 실제 JSON을 검사한다. 잘못된 요청·참조 ID·근거 없는 answered·누락된 추가 확인 항목·상한 초과·잘못된 수량을 거부하는지 확인한다.

```powershell
# 루트
.\.venv\Scripts\python.exe -X utf8 -m scripts.export_contracts
.\.venv\Scripts\python.exe -m pytest
# frontend
npm.cmd run typecheck
npm.cmd run check:contracts
npm.cmd run build
```

계약 변경 시 Pydantic·Zod·예시·OpenAPI를 함께 갱신한다. 신규 설치를 요구하는 패키지는 추가하지 않았다.
