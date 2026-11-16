import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { contextKey } from './session.ts';
import type { Fact, useAnalysisSession } from './session.ts';
import type { Task } from './model.ts';

export function Assistant({ analysis, open, close }: { analysis: ReturnType<typeof useAnalysisSession>; open: boolean; close: () => void }) {
  const [question, setQuestion] = useState('');
  const input = useRef<HTMLTextAreaElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const { status, run, answer } = analysis;
  useEffect(() => { if (body.current) body.current.scrollTop = 0; }, [answer?.run_id]);
  const historicalQuestion = answer && answer.run_id !== run?.run_id
    ? analysis.dialogue.find(item => item.run_id === answer.run_id)?.question : null;
  useEffect(() => { if (!open) return; const previous = document.body.style.overflow; document.body.style.overflow = 'hidden'; return () => { document.body.style.overflow = previous; }; }, [open]);
  useEffect(() => { if (open) input.current?.focus({ preventScroll: true }); }, [open]);
  const oldContext = answer && (contextKey(answer.view.context) !== contextKey(analysis.state.context) || analysis.state.task !== answer.view.task);
  const suggested = answer?.suggested_view;
  const canShowChart = suggested && (contextKey(suggested.context) !== contextKey(analysis.state.context) || suggested.task !== analysis.state.task || suggested.month !== analysis.state.month || suggested.detailDay !== analysis.state.detailDay);
  function reference(id: string) {
    const element = document.getElementById(`wb-ref-${id}`);
    if (!element) return;
    const details = element.closest('details'); if (details) details.open = true;
    element.scrollIntoView({ block: 'nearest' }); element.focus({ preventScroll: true });
  }
  function prose(text: string) {
    return text.split(/(\*\*[^*]+\*\*|\[(?:R\d+_[A-Za-z0-9_]+|来源\d+)\])/g).map((part, i) =>
      part.startsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> :
      /^\[(?:R\d+_|来源)/.test(part) ? <button className="wb-citation" key={i} onClick={() => reference(part.slice(1, -1))}>{part}</button> : part);
  }
  function openFact(fact: Fact) {
    if (!answer) return;
    const result = answer.results?.find(result => result.result_id === fact.result_id);
    const context = result?.context ?? answer.context;
    const task = (result?.task === 'observations' ? 'trend' : result?.task === 'station_trends' ? 'stations' : result?.task ?? answer.view.task) as Task;
    const date = fact.date ?? (fact.month !== null ? `${context.target_year}-${String(fact.month).padStart(2, '0')}-01` : null);
    if (!date) return;
    analysis.dispatch({ type: 'APPLY', task, context, month: date.slice(0, 7),
      detailObject: fact.station_id ?? context.object_id, detailDay: fact.selection_kind === 'day' ? date : null,
      detailTab: answer.view.detailTab ?? 'daily' });
    close();
  }
  const c = analysis.state.context;
  const period = ['compare', 'distribution'].includes(analysis.state.task) || analysis.state.task === 'stations' && c.station_mode === 'compare'
    ? `${c.base_year} → ${c.target_year}` : `${c.start.slice(0, 7)} — ${c.end.slice(0, 7)}`;
  return <motion.aside initial={false} animate={{ x: open || reducedMotion ? 0 : 28, opacity: open ? 1 : 0, scale: open || reducedMotion ? 1 : .98 }} transition={reducedMotion ? { duration: 0 } : { type: 'spring', stiffness: 330, damping: 34, mass: .85, opacity: { duration: .2 } }} id="wb-assistant" className="wb-assistant" data-open={open} role="dialog" aria-modal={open ? true : undefined} aria-label="分析助手" aria-hidden={!open} inert={!open} onKeyDown={e => {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    if (e.key === 'Tab') {
      const controls = [...e.currentTarget.querySelectorAll<HTMLElement>('button, input, textarea, select, a[href], summary')].filter(el => !el.hasAttribute('disabled') && el.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (e.shiftKey && document.activeElement === first && last) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last && first) { e.preventDefault(); first.focus(); }
    }
  }}>
    <div className="wb-assistant-heading"><div className="wb-assistant-identity"><span className="wb-ai-mark" aria-hidden="true">✦</span><div><h2>分析助手</h2><p>结合图表与真实观测回答</p></div></div><button className="wb-close-assistant" aria-label="关闭分析助手" onClick={close}>×</button></div>
    <div className="wb-assistant-scope"><span><i aria-hidden="true" />当前条件</span><strong>{analysis.state.task === 'stations' ? '上海监测站' : c.object_id === 'shanghai' ? '上海全市' : '所选监测站'} · {period} · {c.statistic === 'mean' ? '均值' : 'P90'}</strong></div>
    <div className="wb-assistant-body" ref={body}>
    {!answer && !run && <div className="wb-assistant-empty"><span aria-hidden="true">✦</span><h3>从一个问题开始</h3><p>比较变化、解释现象，或继续追问当前图形。</p><div className="wb-question-ideas">{['比较2023与2022年月均和P90','当前时段有哪些连续高值过程？','P90和均值有什么区别？'].map(text => <button key={text} onClick={() => { setQuestion(text); input.current?.focus(); }}>{text}<span aria-hidden="true">↗</span></button>)}</div></div>}
    {analysis.error && <div className="wb-assistant-error" role="alert"><p>{analysis.error}</p>{analysis.canRecover && <button onClick={() => void analysis.submit()}>查询这次请求</button>}{run && <button onClick={() => void analysis.recoverRun()}>继续读取结果</button>}</div>}
    {historicalQuestion && !analysis.running && <section className="wb-run"><p className="wb-run-question">{historicalQuestion}</p></section>}
    {run && (!historicalQuestion || analysis.running) && <section className="wb-run" aria-live="polite"><p className="wb-run-question">{run.question}</p>
      {analysis.running && <><p className="wb-thinking" role="status"><span aria-hidden="true"><i /><i /><i /></span>{run.events?.filter(e => e.data.step).at(-1)?.data.step ?? '准备分析…'}</p><button disabled={run.status === 'cancelling'} onClick={() => void analysis.cancel()}>{run.status === 'cancelling' ? '正在停止后续分析…' : '取消本次分析'}</button></>}
      {run.error && run.error !== analysis.error && <p>{run.error}</p>}
      {run.status === 'failed' && ['INVALID_QUERY','INVALID_PLAN','WORKFLOW_ERROR'].includes(run.error_code ?? '') && <button onClick={() => void analysis.recoverPlan()}>重新校验已保存计划</button>}
      {run.status === 'clarification_required' && run.clarification && <><p>{run.clarification.question}</p>{run.clarification.kind === 'winter' ? run.clarification.options.map((option, i) => <button key={option} disabled={analysis.submitting || analysis.session?.state_revision !== run.expected_revision} onClick={() => void analysis.resume(run.clarification!.choices![i])}>{option}</button>) : run.clarification.options.map(option => <button key={option} onClick={() => { setQuestion(option); input.current?.focus(); }}>{option}</button>)}{analysis.session?.state_revision !== run.expected_revision && <p>条件已经改变，请基于当前选择重新提问。</p>}<button onClick={() => void analysis.cancel()}>取消本次分析</button></>}
    </section>}
    {answer && <motion.section key={answer.run_id} className="wb-answer" initial={{ opacity: 0, y: reducedMotion ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reducedMotion ? 0 : .26 }}><p className="wb-eyebrow">{oldContext ? '此前的回答' : '助手回答'}</p><h3>{answer.view_spec.title}</h3><div className="wb-answer-text">{answer.answer.text.split(/\n\s*\n/).map((paragraph, i) => <p key={i}>{prose(paragraph)}</p>)}</div>
      {oldContext && <button onClick={() => analysis.dispatch({ type: 'APPLY', ...answer.view })}>还原本次分析</button>}
      {canShowChart && <button onClick={() => { analysis.dispatch({ type: 'APPLY', ...suggested }); close(); }}>展示相关图表</button>}
      <p className="wb-footnote">{answer.answer.source === 'model_explanation' ? '概念与方法说明。' : answer.answer.source === 'computed_fallback' ? '模型分析未完成；此处为程序计算的摘要。' : answer.answer.sources?.length ? '结合观测与外部资料回答，引用可查看原始来源。' : '分析依据本地观测；数值与明细见下方。'}</p>
      {answer.answer.sources?.map((source, index) => <article className="wb-web-source" key={source.url} id={`wb-ref-来源${index + 1}`} tabIndex={-1}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a><p>{source.snippet}</p><small>{new URL(source.url).hostname}{source.date ? ` · ${source.date.slice(0, 10)}` : ''}</small></article>)}
      {answer.facts.length > 0 && <details><summary>结果与依据</summary>{answer.facts.map(fact => <div className="wb-fact" key={fact.id} id={`wb-ref-${fact.id}`} tabIndex={-1}><small>[{fact.id}]</small><p>{fact.text}</p>{(fact.date || fact.month !== null) && <button onClick={() => openFact(fact)}>查看{fact.station_id ? '站点' : ''}{fact.selection_kind === 'day' ? fact.date : fact.date?.slice(0, 7) ?? `${fact.month}月`}明细</button>}</div>)}</details>}
      <small>数据版本 {answer.dataset_version}</small>
    </motion.section>}
    {analysis.dialogue.length > 0 && <details className="wb-dialogue"><summary>对话记录 · {analysis.dialogue.length} 次问题</summary>{analysis.dialogue.map(item => <section key={item.run_id}><p>{item.question}</p>{item.result ? <><p>{item.result.answer.text}</p><button onClick={() => analysis.showAnswer(item.result!)}>查看本次分析依据</button></> : <p>{item.clarification?.question ?? item.error ?? item.status}</p>}</section>)}</details>}
    </div>
    <form className="wb-composer" onSubmit={async e => { e.preventDefault(); if (question.trim() && await analysis.submit(question.trim())) setQuestion(''); }}>
      <label className="wb-sr-only" htmlFor="wb-question">你的问题</label><textarea ref={input} id="wb-question" aria-label="分析问题" rows={2} maxLength={1200} value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} placeholder="提问或继续分析当前图表…" required />
      <div className="wb-composer-actions"><label className="wb-search-toggle"><input type="checkbox" checked={analysis.webSearchEnabled} onChange={e => analysis.setWebSearchEnabled(e.target.checked)} />联网资料</label><span className="wb-composer-hint">Ctrl + Enter</span><button type="submit" aria-label={analysis.running ? '正在回答' : '发送问题'} disabled={analysis.running || !analysis.session || !status?.configured}>{analysis.running ? <span className="wb-send-pulse" aria-hidden="true" /> : <svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none"><path d="M10 16V4M5 9l5-5 5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>}</button></div>
      {!status?.configured && <p className="wb-composer-status">{status ? '请先连接模型服务' : '正在连接分析助手…'}</p>}
    </form>
  </motion.aside>;
}
