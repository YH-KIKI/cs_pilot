# TypeScript로 예방하는 오류

현재 실제로 연결한 타입은 주문·품목·조회 결과·화면 상태·컴포넌트 props입니다.
정책 출처·상담 AI 응답·도구 이벤트의 타입도 Pydantic/Zod 계약으로 추가했습니다.
3일차에 ConsultationResponse를 ConsultationResult props로 연결했습니다. Zod 검증을 통과한 실제 응답만 결과 상태에 저장하고, 출처·AI 초안·추가 확인·도구 내역을 표시합니다. RequestState의 success 분기에서만 data를 읽고, not_requested는 OrderSummary에 전달하기 전에 제외합니다.

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

5일차 출처 연결에서는 `Map<string, HTMLDetailsElement>`로 근거 ID와 펼칠 요소를 연결한다.
`get(id)`의 결과는 요소 또는 `undefined`이므로 존재 확인 후에만 `open`과 `focus()`에 접근한다.
잘못된 요소 타입이나 존재하지 않을 수 있는 값의 직접 접근은 타입 검사에서 발견할 수 있다.
실제로 올바른 근거가 펼쳐지는지/키보드 초점이 이동하는지는 Playwright로 별도 확인한다.
`npm run typecheck`는 검사 코드까지 포함하고, `npm run test:ui`는 런타임 응답 거부/화면 동작을 검증한다.
