import type { OrderLookupResult, OrderStatus } from '../schemas';

const statusLabels = {
  received: '주문 접수', processing: '주문 처리 중', preparing: '출고 준비 중',
  shipped: '출고됨', delivered: '배송 완료', cancelled: '취소됨', unknown: '확인 필요',
} satisfies Record<OrderStatus, string>;

export default function OrderSummary({ result }: { result: OrderLookupResult }) {
  if (result.kind === 'not_found') {
    return <p role="status">주문 {result.order_id}를 찾지 못했습니다. 번호를 확인해 주세요.</p>;
  }
  if (result.kind === 'error') return <p role="alert">{result.message}</p>;
  return <>
    <div className="section-title"><h3>{result.order.order_id}</h3><span className="tag">가상 주문</span></div>
    <p className="muted">{result.order.payment_method} · {result.order.card_brand ?? '카드 정보 없음'}</p>
    {result.order.items.map((item) => <article className="item" key={item.item_id}>
      <div className="section-title"><strong>{item.product_name}</strong><span>{statusLabels[item.status]}</span></div>
      <p>품목 {item.item_id} · 수량 {item.quantity}</p>
      <dl>
        <dt>예상 배송일</dt><dd>{item.estimated_delivery_date ?? '확인되지 않음'}</dd>
        <dt>수령 시각</dt><dd>{item.delivered_at ?? '확인되지 않음'}</dd>
        <dt>기록 기준</dt><dd>{item.snapshot_at}</dd>
      </dl>
    </article>)}
  </>;
}
