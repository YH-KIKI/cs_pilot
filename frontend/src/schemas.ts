import { z } from 'zod';

export const orderStatusSchema = z.enum([
  'received', 'processing', 'preparing', 'shipped', 'delivered', 'cancelled', 'unknown',
]);
const timestamp = z.iso.datetime({ offset: true });
const itemSchema = z.object({
  item_id: z.string(), product_name: z.string(), product_type: z.string(),
  quantity: z.number().int().positive(), status: orderStatusSchema,
  shipped_at: timestamp.nullable(), estimated_delivery_date: z.iso.date().nullable(),
  delivered_at: timestamp.nullable(), tracking_number: z.string().nullable(),
  last_tracking_event: z.string().nullable(), snapshot_at: timestamp,
  condition: z.enum(['original', 'damaged', 'other', 'unknown']),
  components_complete: z.boolean().nullable(), security_lock_disabled: z.boolean().nullable(),
  return_requested_at: timestamp.nullable(),
});
const orderSchema = z.object({
  order_id: z.string(), is_synthetic: z.literal(true), store: z.string(),
  purchase_country: z.string(), ordered_at: timestamp,
  payment_method: z.enum(['card', 'bank_transfer', 'other', 'unknown']),
  card_brand: z.string().nullable(), items: z.array(itemSchema).min(1),
});
export const orderLookupSchema = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('found'), order: orderSchema, snapshot_at: timestamp }),
  z.object({ kind: z.literal('not_found'), order_id: z.string() }),
  z.object({ kind: z.literal('error'), message: z.string() }),
]);
export const healthSchema = z.object({
  status: z.literal('ok'), database: z.literal('ready'),
  ai_enabled: z.literal(false), message: z.string(),
});

export type OrderLookupResult = z.infer<typeof orderLookupSchema>;
export type OrderStatus = z.infer<typeof orderStatusSchema>;
export type HealthResponse = z.infer<typeof healthSchema>;

// Day-1 API contract only. No consultation/AI requests are sent by the UI yet.
export const consultationStatusSchema = z.enum([
  'answered', 'needs_information', 'order_not_found', 'insufficient_evidence',
  'limit_reached', 'system_error',
]);
const orderIdSchema = z.string().regex(/^A[0-9]{2,6}$/);
export const consultationRequestSchema = z.object({
  question: z.string().trim().min(1).max(2000),
  order_id: orderIdSchema.nullable().default(null),
  target_item_id: z.string().regex(/^[0-9]{2,6}$/).nullable().default(null),
}).strict().refine((value) => value.target_item_id === null || value.order_id !== null, {
  message: 'target_item_id requires order_id',
});
export const policySourceSchema = z.object({
  evidence_id: z.string().min(1), document_id: z.string().min(1),
  rule_group_id: z.string().min(1), chunk_id: z.string().nullable(),
  title: z.string().min(1), heading: z.string().min(1), source_url: z.url({ protocol: /^https?$/ }),
  collected_at: timestamp, effective_date: z.iso.date().nullable(), excerpt: z.string().min(1),
}).strict();
const recommendationSchema = z.object({
  text: z.string().min(1), evidence_ids: z.array(z.string()),
}).strict();
const appliedPolicySchema = recommendationSchema.extend({ evidence_ids: z.array(z.string()).min(1) });
const missingFieldSchema = z.object({
  field: z.enum([
    'order_id', 'item_id', 'order_status', 'delivered_at', 'condition',
    'components_complete', 'security_lock_disabled', 'payment_method', 'card_brand',
    'purchase_country', 'current_country', 'receipt_available', 'other',
  ]),
  item_id: z.string().nullable(), question: z.string().min(1),
}).strict();
const eventFields = {
  sequence: z.number().int().min(1).max(3), duration_ms: z.number().int().nonnegative(),
  status: z.enum(['success', 'error']), result_summary: z.string().min(1),
};
export const toolEventSchema = z.discriminatedUnion('tool_name', [
  z.object({
    ...eventFields, tool_name: z.literal('lookup_order'),
    input: z.object({ order_id: orderIdSchema }).strict(),
  }).strict(),
  z.object({
    ...eventFields, tool_name: z.literal('search_policy'),
    input: z.object({
      query: z.string().min(1).max(1000), topic: z.enum(['shipping', 'cancellation', 'returns']).nullable(),
    }).strict(),
    evidence_ids: z.array(z.string()),
  }).strict(),
]);
export const consultationResponseSchema = z.object({
  contract_version: z.literal('1.0').default('1.0'), request_id: z.string().min(1),
  reference_time: timestamp, status: consultationStatusSchema,
  order_result: z.discriminatedUnion('kind', [
    z.object({ kind: z.literal('not_requested') }).strict(), ...orderLookupSchema.options,
  ]),
  sources: z.array(policySourceSchema), applied_policies: z.array(appliedPolicySchema),
  recommendation: recommendationSchema, draft_reply: z.string().nullable(),
  missing_fields: z.array(missingFieldSchema), tool_events: z.array(toolEventSchema).max(3),
}).strict().superRefine((value, ctx) => {
  const reject = (message: string) => ctx.addIssue({ code: 'custom', message });
  const sourceIds = new Set(value.sources.map((source) => source.evidence_id));
  if (sourceIds.size !== value.sources.length) reject('Duplicate evidence IDs');
  const referenced = [...value.recommendation.evidence_ids,
    ...value.applied_policies.flatMap((policy) => policy.evidence_ids),
    ...value.tool_events.flatMap((event) => event.tool_name === 'search_policy' ? event.evidence_ids : []),
  ];
  if (referenced.some((id) => !sourceIds.has(id))) reject('Unknown evidence ID');
  if (value.status === 'answered' && (!value.sources.length || !value.applied_policies.length)) {
    reject('Answered policy questions require policy evidence');
  }
  if (value.status === 'needs_information' && !value.missing_fields.length) reject('Missing fields required');
  if (value.status === 'order_not_found' && value.order_result.kind !== 'not_found') reject('Lookup result mismatch');
  if (value.tool_events.filter((event) => event.tool_name === 'lookup_order').length > 1) reject('Order lookup limit');
  if (value.tool_events.filter((event) => event.tool_name === 'search_policy').length > 2) reject('Policy search limit');
  if (value.tool_events.some((event, index) => event.sequence !== index + 1)) reject('Tool event sequence');
});
export const apiErrorSchema = z.object({
  code: z.literal('not_implemented'), message: z.string(),
}).strict();

export type ConsultationRequest = z.infer<typeof consultationRequestSchema>;
export type ConsultationResponse = z.infer<typeof consultationResponseSchema>;
export type PolicySource = z.infer<typeof policySourceSchema>;
export type ToolEvent = z.infer<typeof toolEventSchema>;
