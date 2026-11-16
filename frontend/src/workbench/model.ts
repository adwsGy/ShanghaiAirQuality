export type Task = 'trend' | 'compare' | 'season' | 'stations' | 'distribution' | 'episodes';
export type Statistic = 'mean' | 'p90';
export type Context = {
  object_id: string; start: string; end: string; statistic: Statistic;
  granularity: 'year' | 'month' | 'day'; base_year: number; target_year: number;
  months: number[]; station_ids: string[]; selected_station_ids: string[];
  direction: 'all' | 'up' | 'down'; station_mode: 'compare' | 'period';
  threshold: number; episode_min_days: number; station_sort: 'delta_asc' | 'delta_desc' | 'target_desc'; season_definition: 'calendar_winter' | 'cross_year_winter' | null;
};
export type Summary = { mean: number | null; p90: number | null; n: number; expected: number; unit: string };
export type Point = Summary & { period: string; start?: string | null; end?: string | null };
export type Pair = { month: number; base: Summary; target: Summary; delta: number | null; base_period?: string | null; target_period?: string | null };
export type SiteRow = { station_id: string; name: string; base: Summary | null; target: Summary; delta: number | null; coordinate: { longitude: number; latitude: number } | null };
export type Result = {
  dataset_version: string; result_id: string; task: string; context: Context; object_name: string;
  unit: string; summary: Summary | null; provenance: { query_version?: number; rule_version: string; method: string; source_level: string };
  data: { month_order?: number[]; curves?: { label: string; n: number; points: number[][] }[]; episodes?: { start: string; end: string; days: number; mean: number; maximum: number }[]; threshold?: number; minimum_days?: number; daily?: { date: string; value: number | null }[]; points?: Point[]; cells?: (Summary & { year: number; month: number; period: string })[];
    rows?: (Pair & SiteRow)[]; base?: Summary; target?: Summary; delta?: number | null;
    series?: { station_id: string; name: string; points: Point[] }[] };
};
export type View = { task: Task; context: Context; month: string | null; detailObject: string | null; detailDay: string | null; detailTab: 'daily' | 'hourly' | 'source' };
export type State = View & { history: View[]; notice: string };
export const defaultContext: Context = {
  object_id: 'shanghai', start: '2015-01-01', end: '2025-12-31', statistic: 'mean', granularity: 'year',
  base_year: 2022, target_year: 2023, months: Array.from({ length: 12 }, (_, i) => i + 1),
  station_ids: [], selected_station_ids: [], direction: 'all', station_mode: 'compare', threshold: 75, episode_min_days: 2, station_sort: 'delta_asc', season_definition: null,
};
export const initialState: State = { task: 'trend', context: defaultContext, month: null, detailObject: null, detailDay: null, detailTab: 'daily', history: [], notice: '' };
export type Action = { type: 'APPLY'; context?: Partial<Context>; task?: Task; month?: string | null; detailObject?: string | null; detailDay?: string | null; detailTab?: 'daily' | 'hourly' | 'source'; notice?: string } | { type: 'UNDO' } | { type: 'RESET' } | { type: 'SELECT_STATION'; id: string };
export function endOfMonth(month: string) { const [y, m] = month.split('-').map(Number); return `${month}-${new Date(y, m, 0).getDate()}`; }
export function reducer(state: State, action: Action): State {
  if (action.type === 'UNDO') {
    const previous = state.history.at(-1);
    return previous ? { ...previous, history: state.history.slice(0, -1), notice: '已恢复上一步的条件与选择。' } : state;
  }
  const view: View = { task: state.task, context: state.context, month: state.month, detailObject: state.detailObject, detailDay: state.detailDay, detailTab: state.detailTab };
  let next: View;
  if (action.type === 'RESET') next = { ...initialState };
  else if (action.type === 'SELECT_STATION') {
    const ids = state.context.selected_station_ids;
    if (!ids.includes(action.id) && ids.length === 3) return { ...state, notice: '最多同时追踪 3 个站点，请先移除一个。' };
    next = { ...view, context: { ...state.context, selected_station_ids: ids.includes(action.id) ? ids.filter(id => id !== action.id) : [...ids, action.id] } };
  } else {
    const context = { ...state.context, ...action.context };
    const task = action.task ?? state.task;
    if (['compare','distribution'].includes(task) || task === 'stations' && context.station_mode === 'compare') {
      context.start = `${Math.min(context.base_year, context.target_year)}-01-01`;
      context.end = `${Math.max(context.base_year, context.target_year)}-12-31`;
    }
    if (context.start > context.end || context.start < '2015-01-01' || context.end > '2025-12-31') return { ...state, notice: '请选择 2015—2025 年内有效的日期范围。' };
    if (['compare','distribution'].includes(action.task ?? state.task) && context.base_year === context.target_year) return { ...state, notice: '比较需要两个不同年份。' };
    next = { task: action.task ?? state.task, context, month: action.month === undefined ? state.month : action.month, detailObject: action.detailObject === undefined ? state.detailObject : action.detailObject, detailDay: action.detailDay === undefined ? state.detailDay : action.detailDay, detailTab: action.detailTab ?? state.detailTab };
    if (action.month !== undefined && action.month !== state.month) { next.detailDay = action.detailDay ?? null; next.detailTab = action.detailTab ?? 'daily'; }
    if (action.context?.object_id && action.context.object_id !== state.context.object_id && action.month === undefined) { next.detailObject = null; next.month = null; next.detailDay = null; next.detailTab = 'daily'; }
  }
  if (JSON.stringify(view) === JSON.stringify(next)) return state;
  return { ...next, history: [...state.history, view].slice(-40), notice: action.type === 'APPLY' ? action.notice ?? '' : '' };
}
export const value = (n: number | null | undefined) => n == null ? '—' : n.toFixed(1);
export const signed = (n: number | null | undefined) => n == null ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(1)}`;

// The station code, rather than its current selection index, owns its encoding.
export function stationStyle(id: string, catalogIds?: readonly string[]) {
  const code = catalogIds ? Math.max(0, [...catalogIds].sort().indexOf(id)) : Number.parseInt(id, 10) || 0;
  const colors = ['#086c74', '#6652a3', '#9d4c15', '#2a65a2', '#8b436c', '#526c26'];
  const dashes: ('solid' | 'dashed' | 'dotted' | number[])[] = ['solid', 'dashed', 'dotted', [8, 3, 2, 3]];
  const symbols = ['circle', 'diamond', 'triangle', 'rect'];
  return { color: colors[code % colors.length], type: dashes[Math.floor(code / colors.length) % dashes.length], symbol: symbols[code % symbols.length] };
}

export const comparisonTask = (task: Task) => task === 'compare' || task === 'distribution';
export const trendTask = (task: Task) => task === 'trend' || task === 'episodes';
export function scopeLabel(c: Context) {
  return c.season_definition === 'cross_year_winter' ? `${c.start.slice(0, 4)}—${c.end.slice(0, 4)} 冬季（上年12月至当年2月）` : `${c.start} — ${c.end}`;
}
export function seasonLabel(c: Context) {
  return c.season_definition === 'cross_year_winter' ? '跨年冬季 · 按结束年命名' : c.season_definition === 'calendar_winter' ? '自然年冬季 · 同年1、2、12月' : c.months.length === 12 ? '全年12个月' : c.months.map(m => `${m}月`).join('、');
}
