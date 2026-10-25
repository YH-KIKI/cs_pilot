import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { getHealth, getOrder } from './api';
import OrderSummary from './components/OrderSummary';
import type { HealthResponse, OrderLookupResult } from './schemas';
import type { RequestState } from './types';

export default function App() {
  const [health, setHealth] = useState<RequestState<HealthResponse>>({ status: 'idle' });
  const [lookup, setLookup] = useState<RequestState<OrderLookupResult>>({ status: 'idle' });
  const [orderId, setOrderId] = useState('A06');
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
    setLookup({ status: 'submitting' });
    try {
      const data = await getOrder(orderId.trim().toUpperCase());
      setLookup({ status: 'success', data });
    } catch {
      setLookup({ status: 'error', message: '조회 요청 또는 응답 검증에 실패했습니다. 서버 상태를 확인해 주세요.' });
    } finally { pending.current = false; }
  }

  return <main>
    <header><span className="eyebrow">CS WORKSPACE / FOUNDATION</span><h1>CS Pilot<span>상담을 위한 사실과 근거.</span></h1>
      <p>주문을 확인하고, 정책 근거와 답변을 한곳에서 검토하는 상담 업무 보조 도구입니다.</p></header>
    <aside className="notice">포트폴리오 데모 · 모든 주문은 가상 데이터입니다. 실제 취소·환불·메시지 발송은 수행하지 않습니다.</aside>
    <div className="statusbar"><span className="dot" />
      {health.status === 'success' ? 'FastAPI 연결됨 · SQLite 준비 완료' :
        health.status === 'error' ? health.message : '개발 환경 연결 확인 중…'}
      <span className="tag">AI 호출 비활성</span></div>
    <div className="workspace"><section className="panel">
      <span className="eyebrow">01 / INPUT</span><h2>문의 입력</h2>
      <label htmlFor="question">고객 문의</label>
      <textarea id="question" placeholder="예: 두 품목 중 하나만 반품할 수 있나요?" aria-describedby="ai-status" />
      <p id="ai-status" className="muted">정책 검색·AI 상담은 다음 구현 단계에서 연결됩니다.</p>
      <form onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="order-id">가상 주문번호</label>
        <input id="order-id" value={orderId} pattern="[Aa][0-9]{2,6}" required maxLength={7}
          disabled={lookup.status === 'submitting'} onChange={(event) => setOrderId(event.target.value)} />
        <p className="muted">A01~A12 · A06은 품목별 배송 상태가 다른 주문입니다.</p>
        <button disabled={lookup.status === 'submitting'}>{lookup.status === 'submitting' ? '조회 중…' : '가상 주문 조회'}</button>
      </form>
    </section><section className="panel" aria-live="polite" aria-busy={lookup.status === 'submitting'}>
      <span className="eyebrow">02 / REVIEW</span><h2>확인한 주문 정보</h2>
      {lookup.status === 'idle' && <div className="empty">주문을 조회하면 품목별 상태와 날짜가 표시됩니다.</div>}
      {lookup.status === 'submitting' && <p>읽기 전용 SQL로 주문을 조회하고 있습니다.</p>}
      {lookup.status === 'error' && <p role="alert">{lookup.message}</p>}
      {lookup.status === 'success' && <OrderSummary result={lookup.data} />}
      <div className="future"><h3>정책 출처 · AI 답변</h3><p>준비 중입니다. 확인하지 않은 정책이나 처리 가능 여부를 생성하지 않습니다.</p></div>
    </section></div>
    <footer>React + TypeScript + Vite · Python + FastAPI · SQLite</footer>
  </main>;
}
