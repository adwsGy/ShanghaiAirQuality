import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, request, requestResponse } from '../src/api.ts';

test('HTTP errors preserve the API explanation and status', async t => {
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => Response.json({ error: { message: '研究数据尚未就绪。' } }, { status: 503 });
  await assert.rejects(request('metadata'), e => e instanceof ApiError && e.status === 503 && e.message === '研究数据尚未就绪。');
});
test('network failure has an actionable local-service message', async t => {
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(request('metadata'), e => e instanceof ApiError && e.status === 0 && e.message.includes('确认服务已启动'));
});
test('caller cancellation remains cancellation instead of a user-facing network error', async t => {
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original; });
  const controller = new AbortController(); controller.abort();
  globalThis.fetch = async () => { throw new DOMException('cancelled', 'AbortError'); };
  await assert.rejects(request('metadata', undefined, controller.signal), e => e instanceof DOMException && e.name === 'AbortError');
});
test('JSON parsing failure is distinct from network failure', async t => {
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => new Response('<html>error</html>');
  await assert.rejects(request('metadata'), e => e instanceof ApiError && e.status === 500 && e.message.includes('数据无法读取'));
});
test('CSV response keeps the body and result context intact', async t => {
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => new Response('date,value\n2021-01-01,20', { headers: { 'Content-Type': 'text/csv', 'X-Context-ID': 'same-context' } });
  const response = await requestResponse('exports', { context_id: 'same-context' });
  assert.equal(response.headers.get('X-Context-ID'), 'same-context');
  assert.ok((await response.text()).includes('2021-01-01,20'));
});
