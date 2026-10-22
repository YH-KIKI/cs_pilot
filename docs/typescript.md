# TypeScript로 예방하는 오류

현재 실제로 연결한 타입은 주문·품목·조회 결과·화면 상태·컴포넌트 props입니다.
정책 출처·상담 AI 응답·도구 이벤트의 타입도 Pydantic/Zod 계약으로 추가했습니다.
정책/AI 화면은 해당 기능 구현 시 이 타입을 props로 연결합니다. 계약 정의와 실제 기능 구현은 구분합니다.

| 사례 | 프로젝트 적용 |
|---|---|
| 필드 이름 오타 | API 스키마에서 추론한 타입의 없는 필드 접근을 검사 |
| 주문이 없는데 result.order 접근 | kind === 'found'로 좁힌 뒤에만 접근 |
| 배송 완료지만 수령일 미확인 | delivered_at: string 또는 null로 표시 분기 |
| 주문 데이터 대신 다른 값 전달 | OrderSummary의 OrderLookupResult props 계약 |
| 결과가 없는데 data 접근 | RequestState의 success 상태에서만 접근 |
| 새 배송 상태의 라벨 누락 | satisfies Record<OrderStatus, string> 검사 |
| API가 문자열 수량·잘못된 상태 반환 | TypeScript만으로는 못 막으므로 Zod로 런타임 검사 |

strict와 noUncheckedIndexedAccess를 적용했습니다. any나 비null 단언으로 누락을 숨기지 않습니다.
api.ts에서 JSON을 unknown으로 받고 스키마 검증 후 컴포넌트로 전달합니다.
TypeScript는 정책 판단의 정확성이나 외부 데이터의 진실성을 보장하지 않습니다.
