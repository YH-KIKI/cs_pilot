import { healthSchema, orderLookupSchema } from './schemas';

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
