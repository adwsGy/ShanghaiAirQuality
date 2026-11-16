import { useEffect, useRef, useState } from 'react';
import { ApiError, primeQuery, request } from '../api.ts';
import type { Action, Context, Result, State, View } from './model.ts';
import { defaultContext, initialState, reducer } from './model.ts';

export type Fact = { id: string; text: string; result_id: string; month: number | null; date?: string | null; station_id?: string | null; selection_kind?: 'none' | 'month' | 'day' };
export type Bundle = {
  session_id: string; run_id: string; dataset_version: string; state_revision: number; context: Context;
  view: View; suggested_view?: View | null; result_refs: string[]; results?: Result[];
  view_spec: { task: string; data_ref: string; title: string; selected_month: string | null; secondary_refs?: string[] };
  facts: Fact[]; answer: { text: string; fact_ids: string[]; source: string; sources?: { title: string; url: string; snippet: string; date: string | null }[] };
};
export type RunEvent = { event_id: number; event: string; data: { step?: string }; state_revision?: number };
export type Run = { run_id: string; session_id: string; dataset_version: string; question: string; status: string; result: Bundle | null; error: string | null; error_code?: string | null; expected_revision: number;
  clarification?: { kind?: string; question: string; options: string[]; choices?: string[] }; events?: RunEvent[] };
export type Dialogue = Pick<Run, 'run_id' | 'question' | 'status' | 'result' | 'error' | 'clarification'>;
export type Session = { session_id: string; dataset_version: string; state_revision: number; view: View; history: { view: View; last_result: Bundle | null }[]; last_result: Bundle | null; dialogue?: Dialogue[] };
export type AgentStatus = { configured: boolean; model: string; provider_host: string; used_calls: number; max_calls: number | null; remaining_calls: number | null; web_search?: { default_enabled: boolean; configured: boolean; used_calls: number; max_calls: number | null } };
const bootstraps = new Map<string, Promise<Session>>();
const sessionKey = (version: string) => `shanghai-analysis-session:${version}`;
const runKey = (id: string) => `shanghai-analysis-run:${id}`;
const cursorKey = (id: string) => `shanghai-analysis-cursor:${id}`;
const inFlight = (status: string) => ['queued', 'running', 'cancelling'].includes(status);
const final = (status: string) => !inFlight(status) && status !== 'clarification_required';
const publicView = (s: State): View => ({ task: s.task, context: s.context, month: s.month, detailObject: s.detailObject, detailDay: s.detailDay, detailTab: s.detailTab });
const normalizeView = (view: View): View => ({ ...publicView(initialState), ...view, context: { ...defaultContext, ...view.context } });
export const contextKey = (context: Context) => JSON.stringify(Object.entries({ ...defaultContext, ...context }).sort(([a], [b]) => a.localeCompare(b)));
export function mergeEvents(previous: RunEvent[], incoming: RunEvent[]) {
  const merged = new Map(previous.map(e => [e.event_id, e]));
  for (const event of incoming) merged.set(event.event_id, event);
  return [...merged.values()].sort((a, b) => a.event_id - b.event_id);
}
function bootstrap(version: string) {
  if (!bootstraps.has(version)) {
    const promise = (async () => {
      const id = localStorage.getItem(sessionKey(version));
      if (id) try { return await request<Session>(`analysis/sessions/${id}`); } catch (e) { if (!(e instanceof ApiError) || ![404, 409].includes(e.status)) throw e; }
      const session = await request<Session>('analysis/sessions', { dataset_version: version, view: publicView(initialState) });
      localStorage.setItem(sessionKey(version), session.session_id); return session;
    })();
    bootstraps.set(version, promise); void promise.finally(() => bootstraps.delete(version)).catch(() => {});
  }
  return bootstraps.get(version)!;
}

export function useAnalysisSession(version: string) {
  const [state, setState] = useState(initialState), stateRef = useRef(initialState);
  const [session, setSession] = useState<Session | null>(null), sessionRef = useRef<Session | null>(null);
  const [run, setRun] = useState<Run | null>(null), runRef = useRef<Run | null>(null);
  const [answer, setAnswer] = useState<Bundle | null>(null), [dialogue, setDialogue] = useState<Dialogue[]>([]);
  const [status, setStatus] = useState<AgentStatus | null>(null), [error, setError] = useState(''), [streamError, setStreamError] = useState('');
  const [saving, setSaving] = useState(false), [submitting, setSubmitting] = useState(false), [monitorEpoch, setMonitorEpoch] = useState(0);
  const ready = useRef<Promise<Session> | null>(null), queue = useRef<Promise<unknown>>(Promise.resolve()), active = useRef(true), submittingRef = useRef(false), generation = useRef(0);
  const [webSearchEnabled, setWebSearchEnabled] = useState(() => localStorage.getItem('shanghai-web-search') !== 'false');
  const pending = useRef<{ sessionId: string; body: { client_request_id: string; expected_revision: number; question: string; web_search_enabled: boolean } } | null>(null);
  const pendingResume = useRef<{ runId: string; body: { client_request_id: string; expected_revision: number; choice: string } } | null>(null);
  const cancelIds = useRef(new Map<string, string>());
  const recoveryIds = useRef(new Map<string, string>());

  function hydrate(next: Session, notice = '') {
    if (!active.current || next.dataset_version !== version || next.state_revision < (sessionRef.current?.state_revision ?? -1)) return;
    if (next.last_result) {
      for (const result of next.last_result.results ?? []) primeQuery('workspace/query', { dataset_version: version,
        task: result.task === 'observations' ? 'trend' : result.task,
        context: result.task === 'station_trends' ? result.context : { ...result.context, selected_station_ids: [] },
      }, result);
      setAnswer(next.last_result);
    } else if (next.dialogue) {
      const latest = [...next.dialogue].reverse().find(d => d.status === 'completed' && d.result);
      if (latest?.result) setAnswer(latest.result);
    }
    if (next.dialogue) setDialogue(next.dialogue);
    sessionRef.current = next; setSession(next);
    const updated = { ...normalizeView(next.view), history: next.history.map(h => normalizeView(h.view)), notice };
    stateRef.current = updated; setState(updated);
  }
  async function refreshStatus() {
    try { const next = await request<AgentStatus>('analysis/status'); if (active.current) setStatus(next); } catch { /* Visual controls remain usable. */ }
  }
  async function sync() {
    const id = sessionRef.current?.session_id;
    if (id) hydrate(await request<Session>(`analysis/sessions/${id}`));
  }
  function monitor(next: Run) {
    if (!active.current || next.dataset_version !== version) return;
    generation.current++; runRef.current = next; setRun(next); setMonitorEpoch(v => v + 1);
    localStorage.setItem(runKey(next.session_id), next.run_id);
  }
  useEffect(() => {
    active.current = true; ready.current = bootstrap(version);
    void ready.current.then(next => {
      if (!active.current) return; hydrate(next);
      const saved = localStorage.getItem(runKey(next.session_id));
      const latestDialog = next.dialogue?.at(-1);
      const id = saved ?? latestDialog?.run_id;
      if (id) void request<Run>(`analysis/runs/${id}`).then(r => { if (active.current) monitor(r); }).catch(() => {});
    }).catch(e => { if (active.current) setError(`会话暂不可用：${(e as Error).message} 图形操作可继续。`); });
    void refreshStatus(); return () => { active.current = false; };
  }, [version]);

  function dispatch(action: Action) {
    queue.current = queue.current.then(async () => {
      try { await ready.current; } catch { /* Keep local controls if the session could not initialize. */ }
      const next = reducer(stateRef.current, action);
      if (JSON.stringify(publicView(next)) === JSON.stringify(publicView(stateRef.current))) { stateRef.current = next; setState(next); return; }
      const current = sessionRef.current;
      if (!current) { stateRef.current = next; setState(next); return; }
      setSaving(true); setError('');
      try { hydrate(await request<Session>(`analysis/sessions/${current.session_id}/actions`, {
        client_request_id: crypto.randomUUID(), expected_revision: current.state_revision,
        action: action.type === 'UNDO' ? 'undo' : 'apply', ...(action.type === 'UNDO' ? {} : { view: publicView(next) }),
      }), next.notice); }
      catch (e) { setError((e as Error).message); await sync().catch(() => {}); }
      finally { setSaving(false); }
    }).catch(e => setError((e as Error).message));
  }
  async function submit(question?: string) {
    if (submittingRef.current || runRef.current && inFlight(runRef.current.status)) return false;
    submittingRef.current = true; setSubmitting(true);
    try {
      await queue.current; const current = sessionRef.current;
      if (!current) { setError('分析会话尚未就绪，请稍后重试。'); return false; }
      if (question !== undefined) pending.current = { sessionId: current.session_id, body: { client_request_id: crypto.randomUUID(), expected_revision: current.state_revision, question, web_search_enabled: webSearchEnabled } };
      const submission = pending.current; if (!submission) return false;
      generation.current++; setError(''); setStreamError('');
      const next = await request<Run>(`analysis/sessions/${submission.sessionId}/runs`, submission.body);
      pending.current = null; monitor(next); void refreshStatus(); return true;
    } catch (e) { setError((e as Error).message); return false; }
    finally { submittingRef.current = false; setSubmitting(false); }
  }
  async function recoverRun() {
    const current = runRef.current; if (!current) return;
    try { setError(''); setStreamError(''); monitor(await request<Run>(`analysis/runs/${current.run_id}`)); }
    catch (e) { setError((e as Error).message); }
  }
  async function resume(choice: string) {
    if (submittingRef.current) return;
    submittingRef.current = true; setSubmitting(true);
    try {
      await queue.current; const current = runRef.current, confirmed = sessionRef.current;
      if (!current || !confirmed) return;
      if (pendingResume.current?.runId !== current.run_id || pendingResume.current.body.choice !== choice) pendingResume.current = { runId: current.run_id, body: { client_request_id: crypto.randomUUID(), expected_revision: confirmed.state_revision, choice } };
      const pendingChoice = pendingResume.current; setError('');
      const next = await request<Run>(`analysis/runs/${current.run_id}/resume`, pendingChoice.body);
      pendingResume.current = null; monitor(next);
    } catch (e) { setError((e as Error).message); await sync().catch(() => {}); }
    finally { submittingRef.current = false; setSubmitting(false); }
  }
  async function cancel() {
    const current = runRef.current; if (!current) return;
    if (!cancelIds.current.has(current.run_id)) cancelIds.current.set(current.run_id, crypto.randomUUID());
    try { monitor(await request<Run>(`analysis/runs/${current.run_id}/cancel`, { client_request_id: cancelIds.current.get(current.run_id) })); }
    catch (e) { setError((e as Error).message); }
  }
  async function recoverPlan() {
    const current = runRef.current, confirmed = sessionRef.current;
    if (!current || !confirmed) return;
    if (!recoveryIds.current.has(current.run_id)) recoveryIds.current.set(current.run_id, crypto.randomUUID());
    try { setError(''); monitor(await request<Run>(`analysis/runs/${current.run_id}/recover`, { client_request_id: recoveryIds.current.get(current.run_id), expected_revision: confirmed.state_revision })); }
    catch (e) { setError((e as Error).message); }
  }

  useEffect(() => {
    if (!run) return;
    const id = run.run_id, currentGeneration = generation.current;
    const saved = Number(localStorage.getItem(cursorKey(id)) ?? 0);
    let cursor = Number.isFinite(saved) ? saved : 0, stopped = false, finishing = false, failures = 0;
    const source = new EventSource(`/api/v1/analysis/runs/${id}/events?after=${cursor}`);
    const valid = () => !stopped && active.current && generation.current === currentGeneration && runRef.current?.run_id === id;
    function remember(events: RunEvent[]) { if (events.length) { cursor = Math.max(cursor, ...events.map(e => e.event_id)); localStorage.setItem(cursorKey(id), String(cursor)); } }
    async function finish(next: Run) {
      if (!valid() || finishing) return; finishing = true; source.close();
      runRef.current = next; setRun(next);
      if (final(next.status)) localStorage.removeItem(runKey(next.session_id));
      await queue.current;
      try { if (valid()) { await sync(); if (next.result) setAnswer(next.result); void refreshStatus(); } }
      catch (e) { if (valid()) setError((e as Error).message); }
    }
    async function loadFinal() {
      try { const next = await request<Run>(`analysis/runs/${id}`); if (valid()) await finish(next); }
      catch (e) { if (valid()) setStreamError(`暂时未能读取最终结果：${(e as Error).message}`); }
    }
    source.addEventListener('snapshot', event => {
      if (!valid()) return;
      try {
        const next = JSON.parse((event as MessageEvent).data).run as Run;
        next.events = mergeEvents(runRef.current?.events ?? [], next.events ?? []); remember(next.events);
        if (inFlight(next.status)) { runRef.current = next; setRun(next); } else void finish(next);
      } catch { setStreamError('进度消息格式无效，可继续读取同一次运行。'); }
    });
    for (const name of ['run_started', 'progress', 'tool_completed', 'clarification_required', 'result', 'error', 'cancelled']) source.addEventListener(name, event => {
      if (!valid() || !('data' in event)) return;
      try {
        const item = JSON.parse((event as MessageEvent).data) as RunEvent;
        if (item.event_id <= cursor) return; remember([item]);
        const next = { ...runRef.current!, events: mergeEvents(runRef.current?.events ?? [], [item]) };
        runRef.current = next; setRun(next);
        if (['result', 'error', 'cancelled', 'clarification_required'].includes(name)) void loadFinal();
      } catch { setStreamError('进度消息格式无效，可继续读取同一次运行。'); }
    });
    source.onopen = () => { if (valid()) { failures = 0; setStreamError(''); } };
    source.onerror = event => {
      if (!valid() || 'data' in event) return;
      failures++;
      setStreamError(failures < 3 ? '进度连接中断，正在重新连接同一次运行…' : '进度连接已中断，请继续读取同一次运行。');
      if (failures >= 3) source.close();
    };
    return () => { stopped = true; source.close(); };
  }, [run?.run_id, monitorEpoch]);

  return { state, dispatch, session, run, answer, dialogue, status, error: error || streamError, saving, submitting,
    webSearchEnabled, setWebSearchEnabled: (value: boolean) => { localStorage.setItem('shanghai-web-search', String(value)); setWebSearchEnabled(value); },
    running: submitting || !!run && inFlight(run.status), canRecover: !!pending.current,
    submit, sync, refreshStatus, recoverRun, recoverPlan, resume, cancel, showAnswer: setAnswer,
  };
}
