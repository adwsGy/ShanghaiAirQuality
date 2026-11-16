import type { EChartsOption } from 'echarts';
import type { Context, Result, SiteRow } from './model.ts';
import { signed, stationStyle, value } from './model.ts';
export const palette = { mean: '#086c74', p90: '#6652a3', base: '#687985', target: '#086c74', up: '#a64f21', down: '#266aa3', text: '#33434b', grid: '#e5e9eb', selection: '#172d36' };
const font = '"Microsoft YaHei", "PingFang SC", sans-serif';
const axis = { axisLabel: { color: palette.text, fontSize: 12 }, axisLine: { lineStyle: { color: '#b7c4ca' } }, axisTick: { show: false } };
const grid = { left: 52, right: 28, top: 40, bottom: 60 };
const tooltip = { trigger: 'axis' as const, confine: true, backgroundColor: '#fff', borderColor: '#ced8dc', textStyle: { color: '#243940', fontSize: 14 }, valueFormatter: (v: any) => v == null ? '—' : value(Number(v)) };
const yAxis = { ...axis, type: 'value' as const, min: 0, name: 'μg/m³', nameTextStyle: { color: palette.text, fontSize: 12 }, splitLine: { lineStyle: { color: palette.grid } } };
export const base = { textStyle: { fontFamily: font, color: palette.text }, animation: false, grid, tooltip };
function line(name: string, data: (number | null)[], color: string, dashed = false) {
  return { name, type: 'line' as const, data, connectNulls: false, symbolSize: 7, showSymbol: data.length <= 36, lineStyle: { color, width: 2, type: dashed ? 'dashed' as const : 'solid' as const }, itemStyle: { color }, emphasis: { focus: 'series' as const } };
}
export function trendOption(result: Result, overlay: boolean, zoom: [number, number]): EChartsOption {
  const c = result.context, points = result.data.points ?? [];
  const metric = c.granularity === 'day' ? 'mean' : c.statistic;
  return { ...base, legend: { top: 0, left: 'center', textStyle: { fontSize: 12 } }, xAxis: { ...axis, type: 'category', boundaryGap: false, data: points.map(p => p.period), axisLabel: { ...axis.axisLabel, hideOverlap: true } }, yAxis,
    dataZoom: [{ type: 'slider', bottom: 0, height: 20, start: zoom[0], end: zoom[1], borderColor: '#d4dddf', fillerColor: '#d4e5e7', handleSize: '110%' }],
    series: [line(metric === 'mean' ? (c.granularity === 'day' ? '日均' : '均值') : 'P90', points.map(p => p[metric]), palette[metric], metric === 'p90'), ...(overlay && c.granularity !== 'day' ? [line(metric === 'mean' ? 'P90' : '均值', points.map(p => p[metric === 'mean' ? 'p90' : 'mean']), palette[metric === 'mean' ? 'p90' : 'mean'], metric === 'mean')] : [])] };
}
export function compareOption(result: Result, difference = false, selected: string | null = null): EChartsOption {
  const c = result.context, rows = result.data.rows ?? [];
  const comparisonLines = [line(`${c.base_year} · ${c.statistic === 'mean' ? '均值' : 'P90'}`, rows.map(r => r.base[c.statistic]), palette.base, true), line(`${c.target_year} · ${c.statistic === 'mean' ? '均值' : 'P90'}`, rows.map(r => r.target[c.statistic]), palette.target)].map(series => ({ ...series, data: series.data.map((v, i) => ({ value: v, symbolSize: selected && (selected === rows[i].target_period || selected === rows[i].base_period) ? 12 : 7, itemStyle: selected && (selected === rows[i].target_period || selected === rows[i].base_period) ? { borderColor: palette.selection, borderWidth: 3 } : undefined })) }));
  return { ...base, grid: { ...grid, bottom: 30, top: difference ? 26 : 40 }, tooltip,
    legend: difference ? undefined : { top: 0, left: 'center', textStyle: { fontSize: 12 } },
    xAxis: { ...axis, type: 'category', data: rows.map(r => c.season_definition === 'cross_year_winter' && r.month === 12 ? '上年12月' : `${r.month}月`), boundaryGap: difference },
    yAxis: difference ? { ...yAxis, min: undefined, name: '差值 · μg/m³' } : yAxis,
    series: difference ? [{ type: 'bar', name: `${c.target_year} − ${c.base_year}`, barMaxWidth: 32,
      data: rows.map(r => ({ value: r.delta, itemStyle: { color: r.delta !== null && r.delta > 0 ? palette.up : palette.down } })) }] : comparisonLines };
}
export function seasonOption(result: Result, selected: string | null, numbers: boolean, compact = false): EChartsOption {
  const cells = result.data.cells ?? [], years = [...new Set(cells.map(p => p.year))];
  const monthOrder = result.data.month_order ?? result.context.months;
  // Fixed metric scales make colors comparable across object and range changes.
  const max = result.context.statistic === 'mean' ? 150 : 250;
  return { ...base, grid: { left: 56, right: 24, top: 12, bottom: 68 }, tooltip: { ...tooltip, trigger: 'item', formatter: (p: any) => { const cell = cells[p.dataIndex]; return cell ? `${cell.period}<br/>${result.context.statistic === 'mean' ? '均值' : 'P90'}：${value(cell[result.context.statistic])} μg/m³<br/>${cell.n} 天观测` : ''; } },
    xAxis: { ...axis, type: 'category', data: monthOrder.map(m => result.context.season_definition === 'cross_year_winter' && m === 12 ? '上年12月' : compact ? String(m) : `${m}月`), splitArea: { show: false } },
    yAxis: { ...axis, type: 'category', inverse: true, data: years.map(String), splitArea: { show: false } },
    visualMap: { min: 0, max, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 140, text: [`${max} μg/m³`, '0'], inRange: { color: ['#edf6f5', '#bfddda', '#81bbb8', '#388c91', '#13545f'] }, outOfRange: { color: '#d8dddf' } },
    series: [{ type: 'heatmap', data: cells.map(cell => ({ name: cell.period, value: [monthOrder.indexOf(cell.month), years.indexOf(cell.year), cell[result.context.statistic]], itemStyle: { borderColor: selected === cell.period ? palette.selection : '#fff', borderWidth: selected === cell.period ? 3 : 2, color: cell.n === 0 ? '#d8dddf' : undefined }, label: { color: (cell[result.context.statistic] ?? 0) > max * .6 ? '#fff' : '#17343b' } })), label: { show: numbers, fontSize: 12, color: '#17343b', formatter: (p: any) => p.value[2] == null ? '—' : compact ? String(Math.round(p.value[2])) : value(p.value[2]) }, emphasis: { itemStyle: { borderColor: palette.selection, borderWidth: 3 } } }] };
}
export function stationOption(result: Result): EChartsOption {
  if (result.context.station_mode === 'period') {
    const rows = result.data.rows ?? [], c = result.context;
    return { ...base, grid: { left: 125, right: 24, top: 35, bottom: 36 }, tooltip: { ...tooltip, trigger: 'item', formatter: (p: any) => `${p.data.name}<br/>${value(p.value[0])} μg/m³<br/>${p.data.n} 天观测` },
      xAxis: yAxis, yAxis: { ...axis, type: 'category', inverse: true, data: rows.map(r => r.name), axisLabel: { fontSize: 13, color: palette.text } },
      series: [{ type: 'scatter', symbolSize: 13, data: rows.map((r, i) => ({ name: r.name, station_id: r.station_id, n: r.target.n, value: [r.target[c.statistic], i], itemStyle: { color: palette.target, borderColor: c.selected_station_ids.includes(r.station_id) ? palette.selection : '#fff', borderWidth: c.selected_station_ids.includes(r.station_id) ? 3 : 1 } })) }] };
  }
  const rows = (result.data.rows ?? []).filter(r => r.base?.[result.context.statistic] != null && r.target[result.context.statistic] != null), c = result.context;
  const series: any[] = rows.map((r, i) => ({ type: 'line', data: [[r.base![c.statistic], i], [r.target[c.statistic], i]], symbol: 'none', lineStyle: { color: '#bdcbd0', width: c.selected_station_ids.includes(r.station_id) ? 4 : 2 }, silent: true }));
  for (const target of [false, true]) series.push({ name: String(target ? c.target_year : c.base_year), type: 'scatter', symbolSize: 12,
    itemStyle: { color: target ? palette.target : '#fff', borderColor: target ? palette.target : palette.base, borderWidth: 2 },
    data: rows.map((r, i) => ({ station_id: r.station_id, name: r.name, value: [(target ? r.target : r.base)![c.statistic], i], itemStyle: { color: target ? palette.target : '#fff', borderColor: c.selected_station_ids.includes(r.station_id) ? palette.selection : (target ? palette.target : palette.base), borderWidth: c.selected_station_ids.includes(r.station_id) ? 3 : 2 } })),
    tooltip: { formatter: (p: any) => { const r = rows[p.value[1]]; return `${r.name}<br/>${c.base_year}：${value(r.base![c.statistic])}<br/>${c.target_year}：${value(r.target[c.statistic])}<br/>差值：${signed(r.delta)} μg/m³`; } } });
  return { ...base, grid: { left: 125, right: 24, top: 40, bottom: 36 }, legend: { top: 0, left: 125, textStyle: { fontSize: 12 } }, tooltip: { ...tooltip, trigger: 'item' },
    xAxis: { ...yAxis, nameLocation: 'end' }, yAxis: { ...axis, type: 'category', inverse: true, data: rows.map(r => r.name), axisLabel: { fontSize: 13, color: palette.text }, splitLine: { show: true, lineStyle: { color: '#f1f3f4' } } }, series };
}
export function selectedTrendOption(result: Result, catalogIds?: readonly string[]): EChartsOption {
  const series = result.data.series ?? [], points = series[0]?.points ?? [];
  return { ...base, grid: { ...grid, bottom: 30 }, legend: { top: 0, left: 'center', textStyle: { fontSize: 12 } },
    xAxis: { ...axis, type: 'category', data: points.map(p => p.period), boundaryGap: false, axisLabel: { ...axis.axisLabel, hideOverlap: true } }, yAxis,
    dataZoom: points.length > 36 ? [{ type: 'slider', bottom: 0, height: 18 }] : [],
    series: series.map(s => { const style = stationStyle(s.station_id, catalogIds); return { ...line(s.name, s.points.map(p => p[result.context.statistic]), style.color), symbol: style.symbol, lineStyle: { color: style.color, type: style.type, width: 2 } }; }) };
}

export function distributionOption(result: Result): EChartsOption {
  const c = result.context;
  return { ...base, grid: { ...grid, bottom: 40 }, legend: { top: 0, left: 'center', textStyle: { fontSize: 12 } },
    xAxis: { ...yAxis, name: 'μg/m³', nameGap: 8 }, yAxis: { ...axis, type: 'value', min: 0, max: 1, name: '累计比例', axisLabel: { fontSize: 12, formatter: (v: number) => `${Math.round(v * 100)}%` }, splitLine: { lineStyle: { color: palette.grid } } },
    tooltip: { ...tooltip, trigger: 'item', formatter: (p: any) => `${p.seriesName}<br/>≤ ${value(p.value[0])} μg/m³：${(p.value[1] * 100).toFixed(1)}%` },
    series: (result.data.curves ?? []).map((curve, i) => ({ name: `${curve.label} · n=${curve.n}`, type: 'line', data: curve.points, step: 'end', showSymbol: false, lineStyle: { width: 2, color: i ? palette.target : palette.base, type: i ? 'solid' : 'dashed' } })) };
}

export function episodeOption(result: Result): EChartsOption {
  const points = result.data.daily ?? [], threshold = result.data.threshold ?? 75;
  return { ...base, legend: { top: 0, left: 'center', textStyle: { fontSize: 12 } },
    xAxis: { ...axis, type: 'category', data: points.map(p => p.date), boundaryGap: false, axisLabel: { ...axis.axisLabel, hideOverlap: true } }, yAxis,
    dataZoom: [{ type: 'slider', height: 20, bottom: 0 }],
    series: [{ ...line('日均浓度', points.map(p => p.value), palette.mean), markArea: { silent: true, itemStyle: { color: '#d9e9e980' }, data: (result.data.episodes ?? []).map(e => [{ xAxis: e.start }, { xAxis: e.end }]) } },
      { ...line(`参考值 ${threshold} μg/m³`, points.map(() => threshold), palette.p90, true), symbol: 'none', silent: true }] };
}
export function mapOption(rows: SiteRow[], context: Context, map: string, view: { center?: number[]; zoom?: number } = {}): EChartsOption {
  return { ...base, tooltip: { ...tooltip, trigger: 'item', formatter: (p: any) => `${p.name} · ${value(p.value?.[2])} μg/m³` },
    geo: { map, ...view, roam: true, scaleLimit: { min: .8, max: 5 }, label: { show: false }, itemStyle: { areaColor: '#edf3f2', borderColor: '#a8bdbf', borderWidth: 1 }, emphasis: { disabled: true } },
    series: [{ type: 'scatter', coordinateSystem: 'geo', symbolSize: 13, data: rows.filter(r => r.coordinate).map(r => ({ name: r.name, station_id: r.station_id, value: [r.coordinate!.longitude, r.coordinate!.latitude, r.target[context.statistic]], itemStyle: { color: r.target.n ? palette.target : '#9ba9ae', borderWidth: context.selected_station_ids.includes(r.station_id) ? 3 : 1, borderColor: context.selected_station_ids.includes(r.station_id) ? palette.selection : '#fff' } })) }] };
}
