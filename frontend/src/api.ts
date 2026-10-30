import { consultationRequestSchema, consultationResponseSchema, healthSchema, orderLookupSchema } from './schemas';
import type { ConsultationRequest } from './schemas';

async function getJson(path: string): Promise<unknown> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`서버 요청 실패 (${response.status})`);
  return response.json() as Promise<unknown>;
}

export async function getHealth() {
  return healthSchema.parse(await getJson('/api/health'));
}

export async function getOrder(orderId: string) {
  return orderLookupSchema.parse(await getJson(`/api/orders/${encodeURIComponent(orderId)}`));
}

export async function createConsultation(input: ConsultationRequest) {
  const payload = consultationRequestSchema.parse(input);
  const response = await fetch('/api/consultations', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`상담 요청 실패 (${response.status})`);
  const data: unknown = await response.json();
  return consultationResponseSchema.parse(data);
}
