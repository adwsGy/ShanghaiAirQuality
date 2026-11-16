import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as echarts from 'echarts';
import { seasonOption } from '../src/workbench/charts.ts';
import { defaultContext, type Result, type Statistic } from '../src/workbench/model.ts';

function fixture(values: (number | null)[], statistic: Statistic = 'mean', objectId = 'shanghai'): Result {
  return { dataset_version: 'test', result_id: 'test', task: 'season', object_name: objectId, unit: 'μg/m³',
    context: { ...defaultContext, statistic, object_id: objectId }, summary: null,
    provenance: { rule_version: 'test', method: 'test', source_level: 'test' },
    data: { cells: values.map((concentration, index) => ({ year: 2023, month: index + 1, period: `2023-${String(index + 1).padStart(2, '0')}`,
      mean: concentration, p90: concentration, n: concentration === null ? 0 : 31, expected: 31, unit: 'μg/m³' })) } };
}

function rendered(result: Result) {
  const chart = echarts.init(null, undefined, { renderer: 'svg', ssr: true, width: 800, height: 450 });
  const option = seasonOption(result, null, true);
  try {
    chart.setOption(option);
    return { colors: (result.data.cells ?? []).map((_, dataIndex) => String(chart.getVisual({ seriesIndex: 0, dataIndex }, 'color'))), svg: chart.renderToSVGString() };
  } finally { chart.dispose(); }
}

const renderedColors = (result: Result) => rendered(result).colors;

function luminance(color: string) {
  const channels = color.startsWith('#') ? [1, 3, 5].map(offset => parseInt(color.slice(offset, offset + 2), 16))
    : color.match(/[\d.]+/g)!.slice(0, 3).map(Number);
  const [r, g, b] = channels.map(channel => { const x = channel / 255; return x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; });
  return .2126 * r + .7152 * g + .0722 * b;
}

test('equal concentrations retain their rendered color when extrema, time range or object change', () => {
  const full = renderedColors(fixture([12, 40, 83]));
  const filtered = fixture([40]); filtered.context.start = '2023-01-01'; filtered.context.end = '2023-12-31';
  assert.equal(full[1], renderedColors(filtered)[0]);
  assert.equal(full[1], renderedColors(fixture([40, 62], 'mean', '1144A'))[0]);
});

test('typical low and high monthly concentrations use visibly different luminance, with readable numeric labels', () => {
  const result = fixture([15, 25, 40, 50, 65, 83]);
  const colors = renderedColors(result);
  assert.ok(luminance(colors[0]) - luminance(colors[3]) > .3, '15 and 50 should not be compressed into nearly equal pale colors');
  const option: any = seasonOption(result, null, true);
  colors.forEach((color, i) => {
    const a = luminance(color), b = luminance(option.series[0].data[i].label.color);
    assert.ok((Math.max(a, b) + .05) / (Math.min(a, b) + .05) >= 4.5, `numeric label ${i} must remain readable`);
  });
});

test('missing observations remain distinct from high P90 and above-scale valid observations', () => {
  const colors = renderedColors(fixture([null, 100, 155]));
  assert.notEqual(colors[0], colors[2]);
  assert.equal(colors[1], colors[2]);
  assert.match(rendered(fixture([null, 28])).svg, /fill="#d8dddf"/, 'a missing month must draw an actual gray cell');
  const missingOption: any = seasonOption(fixture([null]), null, true);
  assert.equal(missingOption.series[0].label.formatter({ data: missingOption.series[0].data[0], value: missingOption.series[0].data[0].value }), '—');
  assert.match(missingOption.tooltip.formatter({ dataIndex: 0 }), /—.*0 天观测/);
  assert.notEqual(renderedColors(fixture([168], 'p90'))[0], colors[0]);
  const option: any = seasonOption(fixture([155]), null, false);
  assert.match(option.tooltip.formatter({ dataIndex: 0 }), /155\.0/);
});
