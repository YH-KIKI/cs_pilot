# 상담 API 계약 v1.0

기준 모델: `app/consultation_contract.py` (Pydantic).
프런트 대응 모델: `frontend/src/schemas.ts` (Zod + 추론 타입).
OpenAPI 스냅샷: `api-contract.openapi.json`.
예시: `data/contracts/examples.json`, fixture_only=true. 실제 AI 실행 결과가 아니다.

## POST /api/consultations

입력은 `question`(공백 제거 후 1~2000자), `order_id`(문자열 또는 null), `target_item_id`(문자열 또는 null)다. 주문번호·품목을 생략하면 null로 처리한다. 품목을 지정하려면 주문번호가 필요하다. 빈 주문번호는 프런트에서 null로 정규화한다. 정의하지 않은 입력 필드는 거부한다.

order_id를 입력하면 이번 문의의 대상 주문을 선택한 것으로 해석하고 해당 주문을 먼저 조회한다. 번호 없는 일반 정책 문의는 조회하지 않는다. 모델의 일반 정책 분류 때문에 선택한 주문 맥락이 사라지는 것을 방지하며, 질문 문자열에서 번호를 추측해서 채우지 않는다. 응답 필드와 계약 버전 1.0은 그대로다.

일반 정책 질문에는 주문번호가 필요하지 않다. 질문마다 참조 시각은 서버가 정하므로 클라이언트가 reference_time을 보내면 422다. 평가 고정 시각은 ConsultationEngine.run의 내부 인자로 주입한다. 공개 API에 테스트용 시각 변경 기능을 노출하지 않는다.

| HTTP 상태 | 계약 |
|---|---|
| 200 | LangGraph가 반환한 ConsultationResponse. API 비활성·모델/도구 오류도 status=system_error로 구조화 |
| 422 | FastAPI 기본 HTTPValidationError, 입력 형식 오류 |

`answered` 등 여섯 상담 결과는 HTTP 200 안의 업무 상태다. 정상 실행했지만 추가 정보가 필요한 상황과 HTTP/네트워크 장애를 구분한다. `system_error`는 모델·도구·인용 검증 오류를 구조화한 상담 결과다. 처리되지 않은 서버 오류는 HTTP 5xx로 보고 프런트 오류 상태로 처리한다. 3일차에 기존 501을 실제 그래프 실행으로 교체했다. API 허용이 없으면 첫 판단에서 system_error로 종료하고 유료 호출을 하지 않는다. 1일차 fixture의 not_implemented 예시는 당시 계약 기록이며 현재 엔드포인트 동작이 아니다.

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
- 서버의 최종 조립은 insufficient_evidence 제안에 구체적인 missing_fields가 있으면 needs_information으로 맞춘다. 질문이 없는 근거 부족은 그대로 유지한다. 조회 사실·질문·인용은 보존하고 별도 검증한다.
- order_not_found는 order_result.kind=not_found와 함께 사용한다.
- tool_events는 최대 3개, 주문 조회 1개·검색 2개 이하다. 순번은 1부터 연속이다.
- lookup_order와 search_policy는 서로 다른 input 타입을 사용한다.
- 위 조건은 Python·Zod에서 검사한다. LangGraph의 판단 노드는 실행 전에 전체 3회·조회 1회·검색 2회 상한을 검사한다. 모델 판단도 4회, SDK 전송 재시도는 0회, 모델 호출별 timeout은 30초다. 응답 스키마 검사와 실행 전 제한은 별개다.
- ID 연결 검증만으로 정책의 의미·정당성까지 보장하지 않는다. 출처 메타데이터 대조와 실제 내용 검토가 별도로 필요하다.

## 타입 학습 연결

`ConsultationRequest`, `ConsultationResponse`, `PolicySource`, `ToolEvent`를 Zod에서 추론한다. ToolEvent는 tool_name, 주문 결과는 kind로 좁힌다. ConsultationResult의 props는 ConsultationResponse다. 요청·서버 JSON을 Zod로 검증한 뒤 주문·추천·초안·추가 확인·정책 출처·도구 내역을 상담 화면 하나에 표시한다. `/api/health`의 ai_enabled는 false 상수에서 boolean으로 확장했고 프런트도 함께 갱신했다. 활성 표시는 서버 설정 여부이며 모델/네트워크 정상 보장은 아니다.

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
