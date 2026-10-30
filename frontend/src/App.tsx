import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { createConsultation, getHealth } from './api';
import ConsultationResult from './components/ConsultationResult';
import type { ConsultationResponse, HealthResponse } from './schemas';
import type { RequestState } from './types';

export default function App() {
  const [health, setHealth] = useState<RequestState<HealthResponse>>({ status: 'idle' });
  const [result, setResult] = useState<RequestState<ConsultationResponse>>({ status: 'idle' });
  const [question, setQuestion] = useState('한국 온라인 스토어의 표준 배송은 유료인가요?');
  const [orderId, setOrderId] = useState('');
  const [itemId, setItemId] = useState('');
  const pending = useRef(false);

  useEffect(() => {
    let active = true;
    getHealth().then((data) => { if (active) setHealth({ status: 'success', data }); })
      .catch(() => { if (active) setHealth({ status: 'error', message: 'API 연결을 확인해 주세요.' }); });
    return () => { active = false; };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setResult({ status: 'submitting' });
    try {
      const data = await createConsultation({
        question, order_id: orderId.trim().toUpperCase() || null, target_item_id: itemId.trim() || null,
      });
      setResult({ status: 'success', data });
    } catch {
      setResult({ status: 'error', message: '입력값 또는 응답 검증에 실패했습니다. 주문·품목번호와 서버 연결을 확인해 주세요.' });
    } finally { pending.current = false; }
  }

  const busy = result.status === 'submitting';
  return <main>
    <header><span className="eyebrow">CS WORKSPACE</span><h1>CS Pilot<span>상담을 위한 사실과 근거.</span></h1>
      <p>주문을 확인하고, 정책 근거와 답변을 한곳에서 검토하는 상담 업무 보조 도구입니다.</p></header>
    <aside className="notice">공개 Apple 한국 정책 · 가상 주문 데이터 · AI 답변은 상담원 검토가 필요한 초안입니다. 실제 취소·환불·메시지 발송은 수행하지 않습니다.</aside>
    <div className="statusbar"><span className="dot" />
      {health.status === 'success' ? 'FastAPI 연결됨 · SQLite 준비 완료' :
        health.status === 'error' ? health.message : '연결 확인 중…'}
      <span className="tag">{health.status === 'success' && health.data.ai_enabled ? 'AI 상담 활성' : 'AI 상담 비활성'}</span></div>
    {health.status === 'success' && !health.data.ai_enabled && <p className="muted">서버에서 AI 실행이 비활성입니다. 상담 요청은 실행 오류와 함께 종료됩니다.</p>}
    <div className="workspace"><section className="panel">
      <span className="eyebrow">01 / INPUT</span><h2>문의 입력</h2>
      <form onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="question">고객 문의</label>
        <textarea id="question" value={question} required maxLength={2000} disabled={busy}
          onChange={(event) => setQuestion(event.target.value)} />
        <label htmlFor="order-id">대상 가상 주문번호 (선택)</label>
        <input id="order-id" value={orderId} pattern="[Aa][0-9]{2,6}" maxLength={7}
          disabled={busy} onChange={(event) => setOrderId(event.target.value)} />
        <label htmlFor="item-id">품목번호 (선택)</label>
        <input id="item-id" value={itemId} pattern="[0-9]{2,6}" maxLength={6}
          disabled={busy} onChange={(event) => setItemId(event.target.value)} />
        <p className="muted">주문 A01~A12 · 번호를 입력하면 해당 주문을 먼저 확인합니다. 일반 정책만 문의하려면 비워두세요. 품목번호 입력 시 주문번호도 필요합니다.</p>
        <button disabled={busy}>{busy ? '주문·정책 확인 중…' : '상담 검토 요청'}</button>
      </form>
    </section><section className="panel" aria-live="polite" aria-busy={busy}>
      <span className="eyebrow">02 / REVIEW</span><h2>상담 검토 결과</h2>
      {result.status === 'idle' && <div className="empty">문의를 입력하면 확인한 주문·정책·답변 초안을 표시합니다.</div>}
      {busy && <p>필요한 정보를 확인하고 있습니다.</p>}
      {result.status === 'error' && <p role="alert">{result.message}</p>}
      {result.status === 'success' && <ConsultationResult result={result.data} />}
    </section></div>
    <footer>React + TypeScript + Vite · FastAPI · SQLite · LangGraph</footer>
  </main>;
}
