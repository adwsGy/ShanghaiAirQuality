import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialState, reducer, stationStyle } from '../src/workbench/model.ts';

test('opening and returning from a month preserve range, object and statistic', () => {
  const chosen = reducer(initialState, { type: 'APPLY', context: { object_id: '1141A', start: '2018-08-01', end: '2018-12-31', statistic: 'p90' } });
  const opened = reducer(chosen, { type: 'APPLY', month: '2018-08' });
  const closed = reducer(opened, { type: 'APPLY', month: null });
  assert.deepEqual(closed.context, chosen.context);
  assert.deepEqual(reducer(closed, { type: 'UNDO' }).month, '2018-08');
});
test('undo restores comparison conditions and task together', () => {
  const compared = reducer(initialState, { type: 'APPLY', task: 'compare', context: { base_year: 2021, target_year: 2025, statistic: 'p90' } });
  const reverted = reducer(compared, { type: 'UNDO' });
  assert.equal(reverted.task, 'trend');
  assert.deepEqual(reverted.context, initialState.context);
});
test('removing another station does not change the remaining encoding', () => {
  let state = initialState;
  for (const id of ['1141A', '1143A', '3270A']) state = reducer(state, { type: 'SELECT_STATION', id });
  const style = stationStyle('1143A');
  state = reducer(state, { type: 'SELECT_STATION', id: '1141A' });
  assert.deepEqual(stationStyle(state.context.selected_station_ids[0]), style);
  state = reducer(state, { type: 'SELECT_STATION', id: '1144A' });
  assert.equal(reducer(state, { type: 'SELECT_STATION', id: '1145A' }).context.selected_station_ids.length, 3);
});

test('every catalogue station has a distinct visible color and line pattern', () => {
  const catalog = ['1141A','1142A','1143A','1144A','1145A','1146A','1147A','1148A','1149A','1150A','3265A','3266A','3268A','3269A','3270A','3271A','3272A','3273A','3274A','3544A','4183A','4205A'];
  const styles = catalog.map(id => stationStyle(id, catalog));
  assert.equal(new Set(styles.map(s => JSON.stringify([s.color, s.type]))).size, catalog.length);
  assert.deepEqual(stationStyle('3265A', catalog), stationStyle('3265A', [...catalog].reverse()));
});

test('month changes clear the selected day, while changing its tab keeps the month', () => {
  const opened = reducer(initialState, { type: 'APPLY', month: '2024-10', detailDay: '2024-10-05', detailTab: 'hourly' });
  const changed = reducer(opened, { type: 'APPLY', month: '2024-11' });
  assert.equal(changed.detailDay, null); assert.equal(changed.detailTab, 'daily');
  const source = reducer(opened, { type: 'APPLY', detailTab: 'source' });
  assert.equal(source.month, '2024-10'); assert.equal(source.detailDay, '2024-10-05');
});

test('a fact can restore another object and open its explicit month in one action', () => {
  const restored = reducer(initialState, { type: 'APPLY', context: { object_id: '1141A' }, month: '2018-12', detailObject: '1141A' });
  assert.equal(restored.month, '2018-12'); assert.equal(restored.detailObject, '1141A');
});

test('switching from a quarter to yearly comparison restores the actual comparison span', () => {
  const quarter = reducer(initialState, { type: 'APPLY', task: 'stations', context: { station_mode: 'period', start: '2023-01-01', end: '2023-03-31', base_year: 2020, target_year: 2024 } });
  const comparison = reducer(quarter, { type: 'APPLY', task: 'distribution' });
  assert.equal(comparison.context.start, '2020-01-01'); assert.equal(comparison.context.end, '2024-12-31');
  const undone = reducer(comparison, { type: 'UNDO' });
  assert.equal(undone.context.end, '2023-03-31'); assert.equal(undone.task, 'stations');
});
