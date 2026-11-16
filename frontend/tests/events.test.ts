import { test } from 'node:test';
import assert from 'node:assert/strict';
import { contextKey, mergeEvents } from '../src/workbench/session.ts';
import { defaultContext } from '../src/workbench/model.ts';

test('replayed event IDs merge once and remain in chronological order', () => {
  const event = (id: number) => ({ event_id: id, event: 'progress', data: { step: String(id) } });
  const merged = mergeEvents([event(1), event(3)], [event(2), event(3), event(4)]);
  assert.deepEqual(merged.map(e => e.event_id), [1, 2, 3, 4]);
});
test('condition comparison ignores serialization order and fills compatible defaults', () => {
  const reordered = Object.fromEntries(Object.entries(defaultContext).reverse()) as typeof defaultContext;
  assert.equal(contextKey(defaultContext), contextKey(reordered));
  assert.notEqual(contextKey(defaultContext), contextKey({ ...defaultContext, statistic: 'p90' }));
});
