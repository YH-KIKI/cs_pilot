import fs from 'node:fs';
import { test, expect } from '@playwright/test';
import type { Page, Route } from '@playwright/test';
import { consultationResponseSchema } from '../src/schemas';
import type { ConsultationResponse } from '../src/schemas';

const fixtures: { fixture_only: boolean; responses: unknown[] } = JSON.parse(
  fs.readFileSync(new URL('../../data/contracts/examples.json', import.meta.url), 'utf8'),
);
if (!fixtures.fixture_only) throw new Error('UI tests require fixture-only responses');
const responses = fixtures.responses.map((value) => consultationResponseSchema.parse(value));
function fixture(status: ConsultationResponse['status']) {
  const response = responses.find((value) => value.status === status);
  if (!response) throw new Error(`Missing fixture: ${status}`);
  return structuredClone(response);
}
function savedResponse(caseId: string) {
  const report: { cases: { case_id: string; response: unknown }[] } = JSON.parse(fs.readFileSync(
    new URL('../../docs/agent-evaluation-v9-2026-10-31.json', import.meta.url), 'utf8',
  ));
  return consultationResponseSchema.parse(report.cases.find((value) => value.case_id === caseId)?.response);
}
const labels = {
  answered: '답변 초안 준비', needs_information: '추가 확인 필요', order_not_found: '주문 없음',
  insufficient_evidence: '정책 근거 부족', limit_reached: '실행 상한 도달', system_error: '실행 오류',
};
const json = (route: Route, value: unknown) => route.fulfill({ json: value });
const submit = (page: Page) => page.getByRole('button', { name: '상담 검토 요청' }).click();

test.beforeEach(async ({ page }) => {
  // Block unknown APIs: these tests must never fall through to a real backend/model.
  await page.route('**/api/**', (route) => route.abort());
  await page.route('**/api/health', (route) => json(route, {
    status: 'ok', database: 'ready', ai_enabled: false, message: 'UI fixture only',
  }));
});

test('initial screen and health connection failure', async ({ page }) => {
  await page.route('**/api/health', (route) => route.abort());
  await page.goto('/');
  await expect(page.getByText('API 연결을 확인해 주세요.')).toBeVisible();
  await expect(page.getByText('문의를 입력하면 확인한 주문·정책·답변 초안을 표시합니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: '상담 검토 요청' })).toBeEnabled();
});

for (const response of responses) {
  test(`renders ${response.status} without inventing absent fields`, async ({ page }) => {
    await page.route('**/api/consultations', (route) => json(route, response));
    await page.goto('/');
    await submit(page);
    await expect(page.getByRole('heading', { name: labels[response.status], exact: true })).toBeVisible();
    await expect(page.getByText(`판단 기준: ${response.reference_time}`, { exact: false })).toBeVisible();
    await expect(page.getByRole('heading', { name: '고객 답변 초안' })).toHaveCount(response.draft_reply ? 1 : 0);
    if (response.draft_reply) await expect(page.locator('blockquote')).toHaveText(response.draft_reply);
    for (const field of response.missing_fields) await expect(page.getByText(field.question, { exact: true })).toBeVisible();
    if (response.order_result.kind === 'not_found') {
      await expect(page.getByRole('status')).toContainText(response.order_result.order_id);
    }
    if (response.order_result.kind === 'found') {
      await expect(page.getByRole('heading', { name: response.order_result.order.order_id, exact: true })).toBeVisible();
      for (const item of response.order_result.order.items) {
        const article = page.getByRole('article').filter({ hasText: item.product_name });
        await expect(article).toContainText(`품목 ${item.item_id} · 수량 ${item.quantity}`);
        await expect(article).toContainText(item.estimated_delivery_date ?? '확인되지 않음');
        await expect(article).toContainText(item.delivered_at ?? '확인되지 않음');
        await expect(article).toContainText(item.snapshot_at);
      }
    }
    await page.getByText(`도구 실행 내역 (${response.tool_events.length})`, { exact: true }).click();
    const events = page.locator('.consultation-result ol > li');
    await expect(events).toHaveCount(response.tool_events.length);
    for (const [index, event] of response.tool_events.entries()) {
      await expect(events.nth(index)).toContainText(event.tool_name);
      await expect(events.nth(index)).toContainText(event.result_summary);
      await expect(events.nth(index)).toContainText(event.status);
    }
    await expect(page.getByLabel('고객 문의')).toBeEnabled();
  });
}

test('pending request blocks rapid clicks, Enter, and repeated form submissions; success allows retry', async ({ page }) => {
  let count = 0;
  const payloads: unknown[] = [];
  let complete!: () => void;
  const gate = new Promise<void>((resolve) => { complete = resolve; });
  await page.route('**/api/consultations', async (route) => {
    count += 1;
    payloads.push(route.request().postDataJSON());
    await gate;
    await json(route, fixture('answered'));
  });
  await page.goto('/');
  await page.getByLabel('대상 가상 주문번호 (선택)').fill('a04');
  await page.getByLabel('품목번호 (선택)').fill('01');
  const question = await page.getByLabel('고객 문의').inputValue();
  // Same-turn submits exercise the ref guard before React's disabled render.
  await page.locator('form').evaluate((form: HTMLFormElement) => {
    form.requestSubmit(); form.requestSubmit(); form.requestSubmit();
  });
  await expect.poll(() => count).toBe(1);
  await expect(page.getByRole('button')).toBeDisabled();
  for (const label of ['고객 문의', '대상 가상 주문번호 (선택)', '품목번호 (선택)']) {
    await expect(page.getByLabel(label)).toBeDisabled();
  }
  await expect(page.locator('[aria-busy="true"]')).toContainText('필요한 정보를 확인하고 있습니다.');
  await page.getByRole('button').evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await page.keyboard.press('Enter');
  complete();
  await expect(page.getByRole('heading', { name: '답변 초안 준비' })).toBeVisible();
  expect(count).toBe(1);
  expect(payloads).toEqual([{ question, order_id: 'A04', target_item_id: '01' }]);
  await expect(page.getByLabel('고객 문의')).toHaveValue(question);
  await expect(page.getByLabel('대상 가상 주문번호 (선택)')).toHaveValue('a04');
  await expect(page.getByLabel('품목번호 (선택)')).toHaveValue('01');
  await page.getByLabel('대상 가상 주문번호 (선택)').press('Enter');
  await expect.poll(() => count).toBe(2);
  await expect(page.getByRole('button')).toBeEnabled();
});

const failures: { name: string; respond: (route: Route) => Promise<void> }[] = [
  { name: 'network failure', respond: (route) => route.abort('failed') },
  { name: 'HTTP 500', respond: (route) => route.fulfill({ status: 500, body: 'error' }) },
  { name: 'invalid JSON', respond: (route) => route.fulfill({ contentType: 'application/json', body: '{broken' }) },
  { name: 'invalid response contract', respond: (route) => json(route, { status: 'answered', draft_reply: 'unvalidated' }) },
  { name: 'unknown evidence reference', respond: (route) => {
    const response = fixture('answered');
    response.recommendation.evidence_ids = ['nonexistent'];
    return json(route, response);
  } },
];
for (const failure of failures) {
  test(`${failure.name}: clears stale result, preserves input and supports retry`, async ({ page }) => {
    let count = 0;
    await page.route('**/api/consultations', (route) => {
      count += 1;
      return count === 2 ? failure.respond(route) : json(route, fixture('answered'));
    });
    await page.goto('/');
    await page.getByLabel('대상 가상 주문번호 (선택)').fill('A04');
    await page.getByLabel('품목번호 (선택)').fill('01');
    await submit(page);
    await expect(page.getByRole('heading', { name: '답변 초안 준비' })).toBeVisible();
    await submit(page);
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.locator('.consultation-result')).toHaveCount(0);
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    await expect(page.getByRole('button')).toBeEnabled();
    await expect(page.getByLabel('대상 가상 주문번호 (선택)')).toHaveValue('A04');
    await expect(page.getByLabel('품목번호 (선택)')).toHaveValue('01');
    await expect(page.getByLabel('고객 문의')).toHaveValue('한국 온라인 스토어의 표준 배송은 유료인가요?');
    await submit(page);
    await expect(page.getByRole('heading', { name: '답변 초안 준비' })).toBeVisible();
    expect(count).toBe(3);
  });
}

test('invalid local input sends no consultation request and can be corrected', async ({ page }) => {
  let count = 0;
  await page.route('**/api/consultations', (route) => { count += 1; return json(route, fixture('answered')); });
  await page.goto('/');
  await page.getByLabel('고객 문의').fill('   ');
  await submit(page);
  await expect(page.getByRole('alert')).toBeVisible();
  expect(count).toBe(0);
  await page.getByLabel('고객 문의').fill('반품 문의입니다.');
  await page.getByLabel('품목번호 (선택)').fill('01');
  await submit(page);
  await expect(page.getByRole('alert')).toBeVisible();
  expect(count).toBe(0);
  await page.getByLabel('대상 가상 주문번호 (선택)').fill('A05');
  await submit(page);
  await expect(page.getByRole('heading', { name: '답변 초안 준비' })).toBeVisible();
  expect(count).toBe(1);
});

test('citation reveals the correct source, focuses it, and preserves date provenance', async ({ page }) => {
  const response = fixture('answered');
  await page.route('**/api/consultations', (route) => json(route, response));
  await page.goto('/');
  await submit(page);
  const source = response.sources[0];
  if (!source) throw new Error('Answered fixture requires a source');
  const details = page.locator(`[id="${source.evidence_id}"]`);
  await expect(details).not.toHaveAttribute('open', '');
  const citation = page.getByRole('link', { name: '[근거 1]', exact: true }).first();
  await citation.focus();
  await page.keyboard.press('Enter');
  await expect(details).toHaveAttribute('open', '');
  await expect(details).toBeFocused();
  await expect(details.getByText(source.excerpt, { exact: true })).toBeVisible();
  await expect(details.getByRole('link', { name: '공식 정책 원문' })).toHaveAttribute('href', source.source_url);
  await expect(details).toContainText(`수집일: ${source.collected_at} · 시행일: 확인되지 않음`);
});

test('saved O06 renders distinct item statuses and dates', async ({ page }) => {
  // Replay a historical output; no new model, SQL, or vector search is executed.
  const response = savedResponse('O06');
  if (response.order_result.kind !== 'found') throw new Error('O06 requires a found order');
  await page.route('**/api/consultations', (route) => json(route, response));
  await page.goto('/');
  await submit(page);
  const items = page.getByRole('article');
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toContainText('배송 완료');
  await expect(items.nth(0)).toContainText('2026-10-18T12:00:00+09:00');
  await expect(items.nth(1)).toContainText('출고됨');
  await expect(items.nth(1)).toContainText('2026-10-23');
  await page.screenshot({ path: '../data/runtime/day05-o06-ui.png', fullPage: true });
});

test('saved P03 links each applied citation to its own source', async ({ page }) => {
  const response = savedResponse('P03');
  const appliedIds = new Set(response.applied_policies.flatMap((policy) => policy.evidence_ids));
  expect(appliedIds.size).toBeGreaterThanOrEqual(2);
  await page.route('**/api/consultations', (route) => json(route, response));
  await page.goto('/');
  await page.getByLabel('고객 문의').fill('반품 조건을 알려주세요.');
  await submit(page);
  for (const id of appliedIds) {
    const source = response.sources.find((value) => value.evidence_id === id);
    if (!source) throw new Error(`Missing applied source: ${id}`);
    const citation = page.locator(`.consultation-result a[href="#${source.evidence_id}"]`).first();
    await citation.click();
    const details = page.locator(`[id="${source.evidence_id}"]`);
    await expect(details).toHaveAttribute('open', '');
    await expect(details).toBeFocused();
    await expect(details.locator('pre')).toHaveText(source.excerpt);
    await expect(details.getByRole('link', { name: '공식 정책 원문' })).toHaveAttribute('href', source.source_url);
  }
  await page.screenshot({ path: '../data/runtime/day05-p03-ui.png', fullPage: true });
});
