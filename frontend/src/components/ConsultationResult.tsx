import type { ConsultationResponse } from '../schemas';
import OrderSummary from './OrderSummary';

const labels = {
  answered: '답변 초안 준비', needs_information: '추가 확인 필요', order_not_found: '주문 없음',
  insufficient_evidence: '정책 근거 부족', limit_reached: '실행 상한 도달', system_error: '실행 오류',
} satisfies Record<ConsultationResponse['status'], string>;

export default function ConsultationResult({ result }: { result: ConsultationResponse }) {
  const evidenceLinks = (ids: string[]) => ids.map((id) => <a key={id} href={`#${id}`}>
    {' '}[근거 {result.sources.findIndex((source) => source.evidence_id === id) + 1}]
  </a>);
  return <div className="consultation-result">
    <h3>{labels[result.status]}</h3>
    <p className="muted">판단 기준: {result.reference_time} · 요청 {result.request_id}</p>
    {result.order_result.kind !== 'not_requested' && <OrderSummary result={result.order_result} />}
    <h3>권장 처리 방향</h3><p>{result.recommendation.text}{evidenceLinks(result.recommendation.evidence_ids)}</p>
    {result.applied_policies.length > 0 && <><h3>적용한 정책</h3><ul>
      {result.applied_policies.map((policy, index) => <li key={index}>{policy.text}{evidenceLinks(policy.evidence_ids)}</li>)}
    </ul></>}
    {result.missing_fields.length > 0 && <><h3>추가 확인 항목</h3><ul>
      {result.missing_fields.map((field, index) => <li key={index}>{field.question}</li>)}
    </ul></>}
    {result.draft_reply && <><h3>고객 답변 초안</h3><blockquote>{result.draft_reply}</blockquote></>}
    <h3>정책 출처 ({result.sources.length})</h3>
    {result.sources.length === 0 && <p className="muted">확인한 정책 근거가 없습니다.</p>}
    {result.sources.map((source, index) => <details key={source.evidence_id} id={source.evidence_id}>
      <summary>근거 {index + 1} · {source.title} · {source.heading}</summary>
      <a href={source.source_url} target="_blank" rel="noreferrer">공식 정책 원문</a>
      <p className="muted">수집일: {source.collected_at} · 시행일: {source.effective_date ?? '확인되지 않음'}</p>
      <pre>{source.excerpt}</pre>
    </details>)}
    <details><summary>도구 실행 내역 ({result.tool_events.length})</summary>
      {result.tool_events.length === 0 && <p>실행된 도구가 없습니다.</p>}
      <ol>{result.tool_events.map((event) => <li key={event.sequence}>
        <strong>{event.tool_name}</strong> · {event.status} · {event.duration_ms}ms
        <p>{event.result_summary}</p><pre>{JSON.stringify(event.input, null, 2)}</pre>
      </li>)}</ol>
    </details>
  </div>;
}
