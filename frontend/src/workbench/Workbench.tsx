import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from 'motion/react';
import { EChart } from '../EChart.tsx';
import { useQuery } from '../api.ts';
import { useGeometry } from '../geometry.ts';
import type { HourlyObservations, Metadata } from '../types.ts';
import type { Context, Result, SiteRow, State, Task } from './model.ts';
import { comparisonTask, endOfMonth, scopeLabel, seasonLabel, signed, stationStyle, trendTask, value } from './model.ts';
import { useAnalysisSession } from './session.ts';
import { TaskControls } from './TaskControls.tsx';
import { Assistant } from './Assistant.tsx';
import { Sidebar, TaskIcon } from './Sidebar.tsx';
import { ChartHelp, MonthPicker, Select } from './Controls.tsx';
import { base, compareOption, distributionOption, episodeOption, mapOption, palette, seasonOption, selectedTrendOption, stationOption, trendOption } from './charts.ts';
import './workbench.css';
import './presentation.css';
import './sidebar.css';

const tasks: [Task, string][] = [['trend', '长期变化'], ['compare', '时段比较'], ['season', '年月矩阵'], ['stations', '站点分析']];
const metricName = (c: Context) => c.statistic === 'mean' ? '均值' : 'P90';
function Problem({ error, retry }: { error: Error; retry: () => void }) { return <div className="wb-error" role="alert"><p>{error.message}</p><button onClick={retry}>重试</button><button onClick={() => window.location.reload()}>重新载入数据</button></div>; }
function csvDownload(result: Result) {
  const rows = result.task === 'distribution' ? (result.data.curves ?? []).flatMap(curve => curve.points.map(([concentration, cumulative_fraction]) => ({ record_kind: 'ecdf', label: curve.label, n: curve.n, concentration, cumulative_fraction })))
    : result.task === 'episodes' ? [...(result.data.daily ?? []).map(row => ({ record_kind: 'daily', ...row })), ...(result.data.episodes ?? []).map(row => ({ record_kind: 'episode', ...row }))]
    : result.data.points ?? result.data.cells ?? result.data.rows ?? [];
  const flatten = (row: Record<string, unknown>, prefix = ''): Record<string, unknown> => Object.fromEntries(Object.entries(row).flatMap(([k, v]) => v !== null && typeof v === 'object' && !Array.isArray(v) ? Object.entries(flatten(v as Record<string, unknown>, `${prefix}${k}_`)) : [[`${prefix}${k}`, v]]));
  const records = rows.map(row => ({ dataset_version: result.dataset_version, result_id: result.result_id, object_id: result.task === 'stations' ? 'station_network' : result.context.object_id, object_name: result.object_name, statistic: result.context.statistic, start: result.context.start, end: result.context.end, base_year: result.context.base_year, target_year: result.context.target_year, months: result.context.months.join('|'), rule_version: result.provenance.rule_version, unit: result.unit, source_level: result.provenance.source_level, ...flatten({ ...row }) }));
  if (!records.length) return;
  const keys = [...new Set(records.flatMap(Object.keys))], quote = (v: unknown) => `"${String(v ?? '').replaceAll('"', '""')}"`;
  const text = '\ufeff' + [keys, ...records.map(row => keys.map(k => (row as Record<string, unknown>)[k]))].map(row => row.map(quote).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8;' }));
  const a = document.createElement('a'); a.href = url; a.download = `上海PM2.5_${result.task}_${result.result_id}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function TimeRange({ context, apply }: { context: Context; apply: (patch: Partial<Context>) => void }) {
  function update(patch: Partial<Context>) { apply({ ...patch, months: Array.from({ length: 12 }, (_, i) => i + 1), season_definition: null }); }
  const fullRange = context.start === '2015-01-01' && context.end === '2025-12-31';
  return <div className="wb-time-range" role="group" aria-label="分析时段"><span className="wb-control-caption">分析时段</span><div className="wb-date-fields"><label>开始<MonthPicker label="开始月份" value={context.start.slice(0, 7)} max={context.end.slice(0, 7)} onChange={month => update({ start: `${month}-01` })} /></label><label>结束<MonthPicker label="结束月份" value={context.end.slice(0, 7)} min={context.start.slice(0, 7)} onChange={month => update({ end: endOfMonth(month) })} /></label></div>{!fullRange && <button type="button" className="wb-range-reset" onClick={() => update({ start: '2015-01-01', end: '2025-12-31' })}>恢复全部时段</button>}</div>;
}

function ReadingHelp({ task, context, compact }: { task: Task; context: Context; compact: boolean }) {
  return <ChartHelp>{task === 'trend' ? <><p>{context.granularity === 'year' ? '点击年份查看月度变化。' : '点击图中日期或月份查看月内记录。'}</p><p>底部滑块用于放大查看，统计范围由分析设置中的时段控制。</p></>
    : task === 'compare' ? <p>上图比较两年的实际浓度，下图突出同历月增减。点击月份可查看对比年该月的日均和小时记录。</p>
    : task === 'season' ? <><p>每格对应一个年月，使用统一色阶比较浓度。点选格子查看该月的日均和小时记录。</p>{compact && <p>窄屏一次显示最多三年，可切换“查看年份”。</p>}</>
    : task === 'distribution' ? <p>同一浓度下，曲线越高，表示不超过该浓度的日期比例越大。两年分别按各自样本数归一化。</p>
    : task === 'episodes' ? <><p>阴影标出满足当前参考值与持续天数的日期区间。点击曲线查看月内记录。</p><p>没有阴影表示未满足当前持续天数，不代表没有单日高值。</p></>
    : <><p>地图用于位置选站，数值图用于比较浓度。点击站点可加入或移出追踪。</p><p>{context.station_mode === 'compare' ? '空心点对应基准年，实心点对应对比年。' : '每个点对应一个站点的时段统计。'}地图支持拖动与滚轮缩放。</p></>}</ChartHelp>;
}

function MonthDetail({ version, objectId, month, close, day, tab, change }: { version: string; objectId: string; month: string; close: () => void; day: string; tab: 'daily' | 'hourly' | 'source'; change: (patch: { detailDay?: string | null; detailTab?: 'daily' | 'hourly' | 'source' }) => void }) {
  const setTab = (detailTab: 'daily' | 'hourly' | 'source') => change({ detailTab });
  const selectDay = (detailDay: string) => change({ detailDay: detailDay || null, detailTab: detailDay ? 'hourly' : tab });
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); heading.current?.scrollIntoView({ block: 'start' }); }, [objectId, month]);
  const query = useMemo(() => ({ dataset_version: version, station_id: objectId, month }), [version, objectId, month]);
  const request = useQuery<HourlyObservations>('observations/month', query), data = request.data;
  const points = data?.points.filter(p => !day || p.date === day) ?? [];
  const option = useMemo(() => ({ ...base, grid: { left: 50, right: 24, top: 34, bottom: 40 },
    xAxis: { type: 'category' as const, boundaryGap: false, data: tab === 'daily' ? data?.daily.map(d => d.date) : points.map(p => p.datetime_local), axisLabel: { fontSize: 12, hideOverlap: true, formatter: (s: string) => tab === 'daily' ? s.slice(8) : day ? s.slice(11, 16) : s.slice(5, 16).replace('T', ' ') } },
    yAxis: { type: 'value' as const, min: 0, name: 'μg/m³', axisLabel: { fontSize: 12 }, splitLine: { lineStyle: { color: palette.grid } } },
    tooltip: { ...base.tooltip, formatter: (params: any) => { const p = params[0]; if (!p) return ''; const record = data?.daily[p.dataIndex]; return tab === 'daily' ? `${record?.date}<br/>日均：${value(record?.daily_mean)} μg/m³<br/>${record?.valid_hours}/24 小时有观测` : `${points[p.dataIndex]?.datetime_local.replace('T', ' ').slice(0, 16)}<br/>${value(points[p.dataIndex]?.value)} μg/m³`; } },
    series: [{ name: tab === 'daily' ? '日均' : '小时浓度', type: 'line' as const, connectNulls: false, showSymbol: tab === 'daily' || !!day, symbolSize: 7, lineStyle: { color: palette.mean, width: 2 }, itemStyle: { color: palette.mean }, data: tab === 'daily' ? data?.daily.map(d => d.daily_mean) : points.map(p => p.value) }] }), [data, tab, day, points]);
  return <section className="wb-detail" aria-label="所选月份明细"><div className="wb-section-heading"><div><p className="wb-eyebrow">当前选择</p><h2 ref={heading} tabIndex={-1}>{data?.label ?? objectId} · {month}</h2></div><button onClick={close}>返回主图 ↑</button></div>
    <div className="wb-detail-tabs" role="group" aria-label="明细类型">{[['daily', '日均'], ['hourly', '小时'], ['source', '数据与来源']].map(([key, label]) => <button key={key} aria-pressed={tab === key} onClick={() => setTab(key as 'daily' | 'hourly' | 'source')}>{label}</button>)}</div>
    {request.loading && <div className="wb-loading" role="status">正在读取月份明细…</div>}{request.error && <Problem error={request.error} retry={request.retry} />}
    {data && <>{tab !== 'source' ? <><div className="wb-detail-controls"><span>{tab === 'daily' ? '日均浓度 · 点击日期查看当天小时' : '小时浓度 · 北京时间'}</span><label>日期<Select label="明细日期" value={day} onChange={selectDay} options={[{ value: '', label: '整月' }, ...data.daily.map(d => ({ value: d.date, label: d.date, description: `${d.valid_hours}/24 小时有观测` }))]} /></label></div><EChart label={`${data.label}${month}${tab === 'daily' ? '日均' : '小时'}浓度，缺测处断开`} option={option} height={280} events={{ click: e => { if (tab === 'daily' && data.daily[e.dataIndex]) { selectDay(data.daily[e.dataIndex].date); } } }} /></> : <><p>{data.method}</p><p>{data.summary.valid_hours} 个小时有观测，{data.summary.expected_hours} 个日历小时。单位 μg/m³，时间为北京时间。</p><div className="wb-table-scroll"><table><thead><tr><th>日期</th><th>日均</th><th>观测小时</th><th>操作</th></tr></thead><tbody>{data.daily.map(d => <tr key={d.date}><td>{d.date}</td><td>{value(d.daily_mean)}</td><td>{d.valid_hours}/24</td><td><button onClick={() => { selectDay(d.date); }}>查看小时</button></td></tr>)}</tbody></table></div><details><summary>小时来源记录</summary><label>筛选日期<Select label="来源日期" value={day} onChange={selectDay} options={[{ value: '', label: '整月' }, ...data.daily.map(d => ({ value: d.date, label: d.date }))]} /></label><div className="wb-table-scroll"><table><thead><tr><th>时间</th><th>浓度</th><th>来源</th></tr></thead><tbody>{points.slice(0, 48).map(p => <tr key={p.datetime_local}><td>{p.datetime_local.slice(0, 16).replace('T', ' ')}</td><td>{value(p.value)}</td><td><details><summary>{data.source_labels[p.kind]}</summary>{p.source_ref || '无记录'}</details></td></tr>)}</tbody></table></div>{points.length > 48 && <p>当前展示前 48 条，选择日期可查看当天全部小时。</p>}</details></>}
      <p className="wb-footnote">日均使用当天全部已有小时；缺测不补零。月份内 {data.daily.filter(d => d.daily_mean !== null).length} 天有观测。</p></>}
  </section>;
}

function StationMap({ rows, metadata, context, select }: { rows: SiteRow[]; metadata: Metadata; context: Context; select: (id: string) => void }) {
  const geometry = useGeometry(metadata);
  const [reset, setReset] = useState(0);
  const mapView = useRef<{ center?: number[]; zoom?: number }>({});
  return <section className="wb-map" id="wb-station-map" tabIndex={-1} aria-label="站点地图"><div className="wb-map-heading"><div><h3>监测站位置示意</h3></div><button onClick={() => { mapView.current = {}; setReset(v => v + 1); }} disabled={!geometry.name}>复位地图</button></div><p className="wb-map-period">{context.station_mode === 'period' ? '当前时段观测' : `${context.target_year} 年观测`}</p>{geometry.name ? <EChart key={reset} label="上海监测站位置示意，点击选择站点" height={380} option={mapOption(rows, context, geometry.name, mapView.current)} events={{ click: e => e.data?.station_id && select(e.data.station_id), georoam: (_, chart) => { const geo = (chart.getOption().geo as { center?: number[]; zoom?: number }[] | undefined)?.[0]; if (geo) mapView.current = { center: geo.center, zoom: geo.zoom }; } }} /> : geometry.error ? <div className="wb-map-message" role="alert"><p>{geometry.error}</p><button onClick={geometry.retry}>重试地图</button></div> : <div className="wb-map-message" role="status">正在读取地图…</div>}</section>;
}

function Analysis({ metadata }: { metadata: Metadata }) {
  const analysis = useAnalysisSession(metadata.dataset_version);
  const { state, dispatch } = analysis, c = state.context;
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [settingsNarrow, setSettingsNarrow] = useState(() => window.matchMedia('(max-width:1050px)').matches);
  const [settingsOpen, setSettingsOpen] = useState(() => !window.matchMedia('(max-width:1050px)').matches && localStorage.getItem('shanghai-settings-open') !== 'false');
  const reducedMotion = useReducedMotion();
  const [overlay, setOverlay] = useState(true), [numbers, setNumbers] = useState(false), [showMap, setShowMap] = useState(true), [showData, setShowData] = useState(false);
  const [zoom, setZoom] = useState<[number, number]>([0, 100]);
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width:600px)').matches);
  const [seasonYear, setSeasonYear] = useState(2025);
  useEffect(() => { const media = window.matchMedia('(max-width:600px)'); const update = () => setCompact(media.matches); media.addEventListener('change', update); return () => media.removeEventListener('change', update); }, []);
  useEffect(() => {
    const media = window.matchMedia('(max-width:1050px)');
    const update = () => {
      const focusWasInSettings = document.activeElement?.closest('#wb-settings');
      setSettingsNarrow(media.matches); setSettingsOpen(!media.matches && localStorage.getItem('shanghai-settings-open') !== 'false');
      if (media.matches && focusWasInSettings) requestAnimationFrame(() => document.getElementById('wb-open-settings')?.focus({ preventScroll: true }));
    };
    media.addEventListener('change', update); return () => media.removeEventListener('change', update);
  }, []);
  const apply = (context: Partial<Context>) => dispatch({ type: 'APPLY', context, month: null });
  const request = useQuery<Result>('workspace/query', { dataset_version: metadata.dataset_version, task: state.task, context: { ...c, selected_station_ids: [] } });
  const trendRequest = useQuery<Result>('workspace/query', { dataset_version: metadata.dataset_version, task: 'station_trends', context: c }, state.task === 'stations' && c.selected_station_ids.length > 0);
  const result = request.data;
  useEffect(() => setShowData(false), [state.task]);
  useEffect(() => setZoom([0, 100]), [c.start, c.end, c.object_id, c.granularity]);
  const seasonYears = [...new Set(result?.data.cells?.map(p => p.year) ?? [])];
  const endYear = seasonYears.includes(seasonYear) ? seasonYear : seasonYears.at(-1) ?? 2025;
  const seasonResult = result && compact && state.task === 'season' ? { ...result, data: { ...result.data, cells: result.data.cells?.filter(p => p.year <= endYear && p.year >= endYear - 2) } } : result;
  const option = useMemo(() => !result ? {} : state.task === 'trend' ? trendOption(result, overlay, zoom) : state.task === 'distribution' ? distributionOption(result) : state.task === 'episodes' ? episodeOption(result) : state.task === 'compare' ? compareOption(result, false, state.month) : state.task === 'season' ? seasonOption(seasonResult!, state.month, numbers, compact) : stationOption({ ...result, context: c }), [result, c, overlay, zoom, state.task, state.month, numbers, compact, endYear]);
  const names = new Map(metadata.stations.map(s => [s.station_id, s.name]));
  const objectName = c.object_id === 'shanghai' ? '上海全市' : names.get(c.object_id) ?? c.object_id;
  const paired = (result?.data.rows ?? []).filter(r => r.base?.[c.statistic] != null && r.target[c.statistic] != null);
  const title = state.task === 'distribution' ? `${objectName} · ${c.target_year} 与 ${c.base_year} 日均分布` : state.task === 'episodes' ? `${objectName} · 连续高值过程` : state.task === 'trend' ? `${objectName} · ${c.granularity === 'year' ? '年度' : c.granularity === 'month' ? '月度' : '每日'}变化` : state.task === 'compare' ? `${objectName} · ${c.target_year} 与 ${c.base_year} 同历月比较` : state.task === 'season' ? `${objectName} · 年月浓度矩阵` : c.station_mode === 'period' ? `上海监测站 · ${c.start}—${c.end}` : `${c.base_year} → ${c.target_year} · 站点变化`;
  function selectMonth(month: string, detailObject: string | null = null) { dispatch({ type: 'APPLY', month, detailObject }); }
  function clickChart(e: any) {
    if (state.task === 'stations' && e.data?.station_id) dispatch({ type: 'SELECT_STATION', id: e.data.station_id });
    else if (state.task === 'season' && e.data?.name) selectMonth(e.data.name);
    else if (state.task === 'compare') { const row = result?.data.rows?.[e.dataIndex]; if (row) selectMonth(row.target_period ?? `${c.target_year}-${String(row.month).padStart(2, '0')}`); }
    else if (state.task === 'episodes') { const date = result?.data.daily?.[e.dataIndex]?.date; if (date) selectMonth(date.slice(0, 7)); }
    else if (state.task === 'trend') {
      const period = result?.data.points?.[e.dataIndex]?.period;
      if (!period) return;
      if (c.granularity === 'year') apply({ start: `${period}-01-01`, end: `${period}-12-31`, granularity: 'month' });
      else selectMonth(period.slice(0, 7));
    }
  }
  const rangeLabel = scopeLabel(c);
  const isComparison = comparisonTask(state.task) || state.task === 'stations' && c.station_mode === 'compare';
  const stationCount = c.station_mode === 'period' ? (result?.data.rows ?? []).filter(r => r.target.n > 0).length : paired.length;
  function closeMonth() { dispatch({ type: 'APPLY', month: null, detailObject: null }); requestAnimationFrame(() => { document.getElementById('wb-primary-heading')?.focus(); }); }
  function closeAssistant() { setAssistantOpen(false); document.getElementById('wb-open-assistant')?.focus({ preventScroll: true }); }
  function closeSettings() { setSettingsOpen(false); if (!settingsNarrow) localStorage.setItem('shanghai-settings-open', 'false'); requestAnimationFrame(() => document.getElementById('wb-open-settings')?.focus({ preventScroll: true })); }
  function toggleSettings() {
    if (settingsOpen) { closeSettings(); return; }
    setAssistantOpen(false); setSettingsOpen(true);
    if (!settingsNarrow) localStorage.setItem('shanghai-settings-open', 'true');
  }
  return <MotionConfig reducedMotion="user"><div className={`wb-shell${assistantOpen ? ' is-assistant-open' : ''}`}><main className="wb"><header className="wb-header" inert={settingsNarrow && settingsOpen}><div className="wb-header-identity"><button id="wb-open-settings" type="button" className="wb-settings-trigger" aria-label="分析设置" aria-controls="wb-settings" aria-expanded={settingsOpen} onClick={toggleSettings}><svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="2.5" y="3" width="15" height="14" rx="2" stroke="currentColor" strokeWidth="1.4"/><path d="M7 3v14m3-10h4m-4 3h4m-4 3h2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg><span>分析设置</span></button><div><p className="wb-eyebrow">上海空气质量 · 历史观测</p><h1>PM2.5 可视分析</h1></div></div><div className="wb-header-actions"><button id="wb-open-assistant" className="wb-assistant-trigger" aria-controls="wb-assistant" aria-expanded={assistantOpen} onClick={() => { if (assistantOpen) closeAssistant(); else { if (settingsNarrow) setSettingsOpen(false); setAssistantOpen(true); } }}><svg aria-hidden="true" viewBox="0 0 20 20" width="17" height="17" fill="none"><path d="m10 2 2.1 5.9L18 10l-5.9 2.1L10 18l-2.1-5.9L2 10l5.9-2.1L10 2Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>分析助手</button><button disabled={!state.history.length} onClick={() => dispatch({ type: 'UNDO' })}>↶ 撤销</button><button onClick={() => dispatch({ type: 'RESET' })}>重置</button><button disabled={!result} onClick={() => result && csvDownload(result)}>导出当前数据</button></div></header>
    <div className={`wb-layout${settingsOpen ? ' has-settings' : ''}`}><Sidebar open={settingsOpen} modal={settingsNarrow} close={closeSettings}>
    <nav className="wb-tasks" aria-label="分析任务">{tasks.map(([task, label]) => <button key={task} aria-current={(state.task === task || task === 'trend' && trendTask(state.task) || task === 'compare' && comparisonTask(state.task)) ? 'page' : undefined} onClick={() => { dispatch({ type: 'APPLY', task, month: null }); if (settingsNarrow) closeSettings(); }}>{(state.task === task || task === 'trend' && trendTask(state.task) || task === 'compare' && comparisonTask(state.task)) && <motion.span className="wb-task-indicator" layoutId="wb-task-indicator" transition={reducedMotion ? { duration: 0 } : { type: 'spring', stiffness: 430, damping: 36 }} />}<TaskIcon task={task} /><span className="wb-task-label">{label}</span></button>)}</nav>
    <section className="wb-context" aria-label="当前分析条件">{state.task === 'stations' ? <div className="wb-fixed-metric"><span>分析对象</span><strong>上海监测站 <small>{metadata.stations.length} 站</small></strong></div> : <label>分析对象<Select label="分析对象" value={c.object_id} searchable onChange={value => apply({ object_id: value })} options={[{ value: 'shanghai', label: '上海全市', description: '城市观测序列' }, ...metadata.stations.map(s => ({ value: s.station_id, label: s.name, description: `监测站 · ${s.station_id}` }))]} /></label>}<label>统计量<Select label="统计量" value={c.statistic} onChange={value => apply({ statistic: value as Context['statistic'] })} options={[{ value: 'mean', label: '均值', description: '已有日均浓度的平均水平' }, { value: 'p90', label: 'P90', description: '90%的日均浓度不超过此值' }]} /></label></section>
    <div className="wb-controls">{isComparison ? <div className="wb-year-controls"><label>基准年<Select label="基准年" value={c.base_year} onChange={value => apply({ base_year: Number(value) })} options={Array.from({ length: 11 }, (_, i) => 2015 + i).map(y => ({ value: String(y), label: String(y), disabled: y === c.target_year || c.season_definition === 'cross_year_winter' && y === 2015 }))} /></label><span>→</span><label>对比年<Select label="对比年" value={c.target_year} onChange={value => apply({ target_year: Number(value) })} options={Array.from({ length: 11 }, (_, i) => 2015 + i).map(y => ({ value: String(y), label: String(y), disabled: y === c.base_year || c.season_definition === 'cross_year_winter' && y === 2015 }))} /></label><button onClick={() => apply({ base_year: c.target_year, target_year: c.base_year })}>交换年份</button></div> : <TimeRange context={c} apply={apply} />}
      {state.task === 'trend' && <div className="wb-chart-controls"><label>时间尺度<Select label="时间尺度" value={c.granularity} onChange={value => apply({ granularity: value as Context['granularity'] })} options={[{ value: 'year', label: '按年' }, { value: 'month', label: '按月' }, { value: 'day', label: '按日' }]} /></label><label className="wb-check"><input type="checkbox" checked={overlay} onChange={e => setOverlay(e.target.checked)} />同时显示均值与 P90</label></div>}
      {state.task === 'season' && <div className="wb-chart-controls">{compact && <label>查看年份<Select label="矩阵截至年份" value={endYear} onChange={value => setSeasonYear(Number(value))} options={seasonYears.map(y => ({ value: String(y), label: String(y) }))} /></label>}<label className="wb-check"><input type="checkbox" checked={numbers} onChange={e => setNumbers(e.target.checked)} />显示格内数值{compact && '（取整）'}</label></div>}
      </div>
    <TaskControls state={state} dispatch={dispatch} />
    </Sidebar><div className="wb-canvas" inert={settingsNarrow && settingsOpen}>
    {analysis.error && !assistantOpen && <p className="wb-notice" role="alert">{analysis.error}</p>}{analysis.saving && <p className="wb-saving" role="status">正在更新条件…</p>}{state.notice && <p className="wb-notice" role="status">{state.notice}</p>}
    <AnimatePresence initial={false} mode="wait"><motion.section key={state.task} className="wb-analysis" aria-busy={request.loading} initial={{ opacity: 0, y: reducedMotion ? 0 : 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: reducedMotion ? 0 : -6 }} transition={{ duration: reducedMotion ? 0 : .2 }}><div className="wb-section-heading"><div><div className="wb-title-line"><h2 id="wb-primary-heading" tabIndex={-1}>{title}</h2><ReadingHelp key={state.task} task={state.task} context={c} compact={compact} /></div><p>{isComparison ? `比较月份：${seasonLabel(c)} · ${metricName(c)}` : `${rangeLabel} · ${c.granularity === 'day' && state.task === 'trend' ? '日均浓度' : metricName(c)}`}</p></div>{result && <div className="wb-summary" key={result.result_id}>{comparisonTask(state.task) ? <><span>{c.base_year}<b>{value(result.data.base?.[c.statistic])}</b></span><span>{c.target_year}<b>{value(result.data.target?.[c.statistic])}</b></span><span>差值<b>{signed(result.data.delta)}</b></span></> : state.task === 'stations' ? <><span>{c.station_mode === 'period' ? '有观测' : '两期均有观测'}<b>{stationCount} <small>站</small></b></span><label className="wb-check wb-map-visibility"><input type="checkbox" checked={showMap} aria-controls="wb-station-map" onChange={e => setShowMap(e.target.checked)} />显示地图</label></> : <><span>均值<b>{value(result.summary?.mean)}</b></span><span>P90<b>{value(result.summary?.p90)}</b></span><span>观测日<b>{result.summary?.n} <small>天</small></b></span></>}</div>}</div>
      {request.loading && <div className="wb-loading wb-chart-loading" role="status"><div className="wb-skeleton-grid" aria-hidden="true"><i /><i /><i /><i /></div><span>正在读取当前条件的数据…</span></div>}{request.error && <Problem error={request.error} retry={request.retry} />}
      {result && <><div className={state.task === 'stations' ? `wb-station-overview${showMap ? ' has-map' : ''}` : undefined}>{state.task === 'stations' && showMap && <StationMap metadata={metadata} rows={result.data.rows ?? []} context={c} select={id => dispatch({ type: 'SELECT_STATION', id })} />}<div className={state.task === 'stations' ? 'wb-station-comparison' : undefined}>{state.task === 'stations' && <h3>{c.station_mode === 'period' ? '站点浓度对比' : '两期浓度与差异'}</h3>}<div className={state.task === 'stations' ? 'wb-station-plot' : undefined} tabIndex={state.task === 'stations' ? 0 : undefined} role={state.task === 'stations' ? 'region' : undefined} aria-label={state.task === 'stations' ? '站点数值对比，可滚动查看全部站点' : undefined}><EChart animated animationKey={result.result_id} option={option} label={title + '，单位微克每立方米'} height={state.task === 'stations' ? Math.max(280, (c.station_mode === 'period' ? result.data.rows?.length ?? 0 : paired.length) * 30 + 80) : state.task === 'season' ? Math.max(280, new Set(seasonResult?.data.cells?.map(p => p.year)).size * (compact ? 50 : 32) + 95) : 340} events={{ click: clickChart, plotclick: clickChart, datazoom: (e: any) => { const z = e.batch?.[0] ?? e; if (typeof z.start === 'number' && typeof z.end === 'number') setZoom([z.start, z.end]); } }} /></div></div></div>
        {state.task === 'season' && result.data.cells?.some(cell => cell.n === 0) && <div className="wb-matrix-key"><i aria-hidden="true" />无观测</div>}
        {state.task === 'distribution' && <div className="wb-table-scroll"><table><thead><tr><th>年份</th><th>日均样本</th><th>均值</th><th>P90</th></tr></thead><tbody>{[[c.base_year, result.data.base], [c.target_year, result.data.target]].map(([year, stats]) => { const summary = stats as import('./model.ts').Summary | undefined; return <tr key={String(year)}><td>{String(year)}</td><td>{summary?.n}</td><td>{value(summary?.mean)}</td><td>{value(summary?.p90)}</td></tr>; })}</tbody></table></div>}
        {state.task === 'episodes' && <div className="wb-table-scroll"><table><thead><tr><th>过程</th><th>连续日</th><th>平均日均</th><th>最高日均</th></tr></thead><tbody>{result.data.episodes?.map(e => <tr key={e.start}><td><button onClick={() => dispatch({ type: 'APPLY', month: e.start.slice(0, 7), detailDay: e.start, detailTab: 'daily' })}>{e.start}—{e.end}</button></td><td>{e.days}</td><td>{value(e.mean)}</td><td>{value(e.maximum)}</td></tr>)}</tbody></table>{!result.data.episodes?.length && <p>当前条件下未找到满足定义的过程。</p>}</div>}
        {state.task === 'compare' && <div className="wb-difference"><h3>各月差值 · {c.target_year} − {c.base_year}</h3><EChart label="各月差值，零线上方为增加，下方为减少" option={compareOption(result, true)} height={195} events={{ click: clickChart, plotclick: clickChart }} /><div className="wb-difference-key"><span>＋ 增加</span><span>− 减少</span></div></div>}
        {state.task !== 'stations' && <form className="wb-open-month" onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); const month = String(data.get('month')); if (month) selectMonth(month); }}><label>直接查看月份<MonthPicker label="直接查看月份" name="month" key={state.month ?? `direct-${comparisonTask(state.task) ? c.target_year : c.end.slice(0, 4)}`} defaultValue={state.month ?? `${comparisonTask(state.task) ? c.target_year : c.end.slice(0, 4)}-01`} hint="选好月份后，点击查看日均 / 小时" /></label><button type="submit">查看日均 / 小时</button>{state.month && <span>已选 {state.month}</span>}</form>}
        {state.task === 'stations' && <><div className="wb-selected" aria-label="已选站点"><span>{c.selected_station_ids.length ? '已追踪' : '点选站点开始追踪'}</span>{c.selected_station_ids.map(id => <button key={id} style={{ borderLeft: `4px solid ${stationStyle(id, metadata.stations.map(s => s.station_id)).color}` }} onClick={() => dispatch({ type: 'SELECT_STATION', id })}>{names.get(id)} ×</button>)}</div>
          {c.selected_station_ids.length > 0 && <section className="wb-station-follow"><h3>所选站点 · {c.granularity === 'year' ? '年度' : c.granularity === 'month' ? '月度' : '每日'}变化</h3>{trendRequest.loading && <p role="status">正在读取站点趋势…</p>}{trendRequest.error && <Problem error={trendRequest.error} retry={trendRequest.retry} />}{trendRequest.data && <EChart option={selectedTrendOption(trendRequest.data, metadata.stations.map(s => s.station_id))} label="所选站点浓度趋势，无观测时断开" height={290} />}<form className="wb-open-month" onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); selectMonth(String(f.get('stationMonth')), String(f.get('detailStation'))); }}><label>站点<Select label="下钻站点" name="detailStation" key={c.selected_station_ids.join(',')} options={c.selected_station_ids.map(id => ({ value: id, label: names.get(id) ?? id, description: id }))} /></label><label>月份<MonthPicker label="站点明细月份" name="stationMonth" key={c.station_mode === 'period' ? c.start.slice(0, 7) : c.target_year} defaultValue={c.station_mode === 'period' ? c.start.slice(0, 7) : `${c.target_year}-01`} hint="选好月份后，点击查看日均 / 小时" /></label><button type="submit">查看日均 / 小时</button></form></section>}
          </>}
        <div className="wb-source-bar">{comparisonTask(state.task) && <span>{c.base_year}：{result.data.base?.n} 天 · {c.target_year}：{result.data.target?.n} 天观测</span>}<button aria-expanded={showData} aria-controls="wb-source-panel" onClick={() => setShowData(v => !v)}>{showData ? '收起数据与口径' : '数据与口径'}</button></div>
        {showData && <div className="wb-source" id="wb-source-panel"><p>{result.provenance.method} P90 为日均浓度的第 90 百分位数。</p><p>数据版本：{result.dataset_version}；{state.task === 'stations' ? '站点归档序列' : c.object_id === 'shanghai' ? '城市归档序列' : '站点归档序列'}。{(state.task === 'stations' || c.object_id !== 'shanghai') && '站点读数不代表区均值。'}</p>{state.task === 'stations' && <><p>地图坐标与边界仅供位置参照，坐标基准尚未核实，不用于距离或行政区归属判断。</p><div className="wb-table-scroll"><table><thead><tr><th>选择站点</th>{c.station_mode === 'compare' && <th>{c.base_year} · {metricName(c)}</th>}<th>{c.station_mode === 'compare' ? c.target_year : '所选时段'} · {metricName(c)}</th>{c.station_mode === 'compare' && <th>差值</th>}</tr></thead><tbody>{result.data.rows?.map(r => <tr key={r.station_id} className={c.selected_station_ids.includes(r.station_id) ? 'wb-row-selected' : ''}><td><button aria-pressed={c.selected_station_ids.includes(r.station_id)} onClick={() => dispatch({ type: 'SELECT_STATION', id: r.station_id })}>{r.name}<small>{r.station_id}</small></button></td>{c.station_mode === 'compare' && <td>{value(r.base?.[c.statistic])}<small>{r.base?.n ?? 0} 天</small></td>}<td>{value(r.target[c.statistic])}<small>{r.target.n} 天</small></td>{c.station_mode === 'compare' && <td>{signed(r.delta)}</td>}</tr>)}</tbody></table></div></>}{state.task !== 'stations' && <div className="wb-table-scroll"><table><thead><tr><th>日期 / 月份</th><th>{comparisonTask(state.task) ? c.base_year : '均值'}</th><th>{comparisonTask(state.task) ? c.target_year : 'P90'}</th><th>{comparisonTask(state.task) ? '差值' : '观测天数'}</th></tr></thead><tbody>{comparisonTask(state.task) ? result.data.rows?.map(r => <tr key={r.month}><td>{r.month} 月</td><td>{value(r.base[c.statistic])}</td><td>{value(r.target[c.statistic])}</td><td>{signed(r.delta)}</td></tr>) : (result.data.points ?? result.data.cells ?? []).slice(0, 150).map(r => <tr key={r.period}><td>{r.period}</td><td>{value(r.mean)}</td><td>{value(r.p90)}</td><td>{r.n}</td></tr>)}</tbody></table>{(result.data.points?.length ?? 0) > 150 && <p>显示前 150 行，导出包含当前条件全部记录。</p>}</div>}</div>}
      </>}
    </motion.section></AnimatePresence>
    {state.month && <MonthDetail key={`${state.detailObject ?? c.object_id}:${state.month}`} version={metadata.dataset_version} objectId={state.detailObject ?? c.object_id} month={state.month} day={state.detailDay ?? ''} tab={state.detailTab} change={patch => dispatch({ type: 'APPLY', ...patch })} close={closeMonth} />}
    <footer className="wb-footer">PM2.5 观测样本分析 · 浓度单位 μg/m³ · 时间为北京时间</footer>
    </div></div>
    <div className="wb-assistant-backdrop" data-open={assistantOpen} aria-hidden="true" inert={!assistantOpen} onClick={closeAssistant} />
    <Assistant analysis={analysis} open={assistantOpen} close={closeAssistant} />
  </main></div></MotionConfig>;
}
export function Workbench() {
  const metadata = useQuery<Metadata>('metadata', undefined);
  return metadata.data ? <Analysis metadata={metadata.data} /> : <main className="wb"><h1>PM2.5 可视分析</h1>{metadata.error ? <Problem error={metadata.error} retry={metadata.retry} /> : <div className="wb-loading" role="status">正在读取数据目录…</div>}</main>;
}
