// Node 24 strips the .ts schema's type declarations; this never runs a paid API.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  apiErrorSchema, consultationRequestSchema, consultationResponseSchema,
} from '../src/schemas.ts';

const fixtureUrl = new URL('../../data/contracts/examples.json', import.meta.url);
const fixtures = JSON.parse(fs.readFileSync(fixtureUrl, 'utf8'));
assert.equal(fixtures.fixture_only, true);
for (const request of fixtures.requests) consultationRequestSchema.parse(request);
for (const response of fixtures.responses) consultationResponseSchema.parse(response);
apiErrorSchema.parse(fixtures.not_implemented);
assert.equal(consultationRequestSchema.safeParse({ question: '   ' }).success, false);
assert.equal(consultationRequestSchema.safeParse({ question: 'hi', target_item_id: '01' }).success, false);
assert.equal(consultationRequestSchema.safeParse({ question: 'hi', reference_time: '2026-01-01' }).success, false);
const copy = (index) => structuredClone(fixtures.responses[index]);
const unknownSource = copy(0);
unknownSource.applied_policies[0].evidence_ids = ['missing'];
assert.equal(consultationResponseSchema.safeParse(unknownSource).success, false);
const ungrounded = copy(0);
ungrounded.sources = [];
ungrounded.applied_policies = [];
assert.equal(consultationResponseSchema.safeParse(ungrounded).success, false);
const noMissingFields = copy(1);
noMissingFields.missing_fields = [];
assert.equal(consultationResponseSchema.safeParse(noMissingFields).success, false);
const tooMany = copy(4);
tooMany.tool_events.push({ ...tooMany.tool_events[2], sequence: 4 });
assert.equal(consultationResponseSchema.safeParse(tooMany).success, false);
const invalidQuantity = copy(1);
invalidQuantity.order_result.order.items[0].quantity = '1';
assert.equal(consultationResponseSchema.safeParse(invalidQuantity).success, false);
console.log('Consultation contract: 2 requests + 6 statuses accepted; invalid boundaries rejected');
