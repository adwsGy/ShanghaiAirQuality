import { useEffect, useRef, useState } from 'react';
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}
export async function requestResponse(path: string, body: unknown = undefined, signal?: AbortSignal, timeoutMs = 15000): Promise<Response> {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`/api/v1/${path}`, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.any(signal ? [signal, timeout.signal] : [timeout.signal]) });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(timeout.signal.aborted ? 408 : 0, timeout.signal.aborted ? '本地服务响应超时，请重试。' : '无法连接本地服务，请确认服务已启动。');
  } finally { clearTimeout(timer); }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(response.status, data?.error?.message ?? `请求失败（${response.status}）`);
  }
  return response;
}
export async function request<T>(path: string, body: unknown = undefined, signal?: AbortSignal, timeoutMs = 15000): Promise<T> {
  const response = await requestResponse(path, body, signal, timeoutMs);
  try { return await response.json() as T; }
  catch { throw new ApiError(500, '服务返回的数据无法读取，请重试。'); }
}
const cache = new Map<string, unknown>();
export function primeQuery(path: string, body: unknown, data: unknown) { cache.set(`${path}:${JSON.stringify(body)}`, data); }
export function useQuery<T>(path: string, body: unknown, enabled = true) {
  const key = `${path}:${JSON.stringify(body)}`;
  const [retryId, setRetryId] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: T; error?: Error }>({ key: '' });
  const requestId = useRef(0);
  useEffect(() => {
    if (!enabled) return;
    const id = ++requestId.current;
    const controller = new AbortController();
    let active = true;
    if (cache.has(key)) { setResult({ key, data: cache.get(key) as T }); return () => { active = false; }; }
    setResult({ key });
    request<T>(path, body, controller.signal).then(data => {
      if (!active || id !== requestId.current) return;
      cache.set(key, data); if (cache.size > 24) cache.delete(cache.keys().next().value!);
      setResult({ key, data });
    }).catch(error => {
      if (active && id === requestId.current && !controller.signal.aborted) setResult({ key, error });
    });
    return () => { active = false; controller.abort(); };
    // The serialized key contains all query dependencies; viewport changes never enter it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, retryId]);
  const current = enabled && result.key === key ? result : undefined;
  return { data: current?.data, error: current?.error, loading: enabled && !current?.data && !current?.error,
    retry: () => { cache.delete(key); setResult({ key: '' }); setRetryId(x => x + 1); } };
}
