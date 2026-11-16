"""Recompute daily and period statistics from included normalized hourly data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from analysis.observed_metrics import aggregate_daily, comparison_rows, POLICY_ID, RULE_VERSION
from pipeline.io import DATA, ROOT, sha256, write_csv, write_json
from pipeline.verify import verify


def rebuild(source=DATA, output=None):
    source = Path(source).resolve()
    output = Path(output or ROOT / 'data/rebuilt').resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('Use a separate output directory outside the source dataset.')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty. Choose a new --output path.')
    verify(source)
    original = json.loads((source / 'data_manifest.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    write_json({'status': 'building'}, output / 'build_status.json')
    for name in original['outputs']:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    hourly_groups = {'city_archive': [], 'site_archive': []}
    for name in original['outputs']:
        if not name.startswith('hourly/'):
            continue
        frame = pd.read_csv(source / name, keep_default_na=False, dtype={'date': str, 'object_id': str})
        if frame.duplicated(['object_id', 'date', 'hour']).any():
            raise ValueError(f'Duplicate hourly key: {name}')
        values = pd.to_numeric(frame.pm25_ug_m3, errors='coerce')
        frame = frame.loc[frame.status.eq('ok') & values.ge(0) & np.isfinite(values)].copy()
        frame['pm25_ug_m3'] = values.loc[frame.index]
        level = 'city_archive' if name.startswith('hourly/city_') else 'site_archive'
        hourly_groups[level].append(frame.groupby(['object_id', 'date']).pm25_ug_m3.agg(['mean', 'count']))
    daily = []
    for name, level, id_column in [('city_daily.csv', 'city_archive', 'city_id'), ('site_daily.csv', 'site_archive', 'station_id')]:
        frame = pd.read_csv(source / name, keep_default_na=False, dtype={'date': str, id_column: str}).rename(columns={id_column: 'object_id'})
        observed = pd.concat(hourly_groups[level])
        if observed.index.duplicated().any():
            raise ValueError(f'Overlapping hourly partitions: {level}')
        keys = pd.MultiIndex.from_frame(frame[['object_id', 'date']])
        if not observed.index.isin(keys).all():
            raise ValueError('Hourly records extend beyond the daily calendar; update the calendar before rebuilding.')
        totals = observed.reindex(keys)
        frame['pm25_ug_m3'] = totals['mean'].to_numpy()
        frame['valid_hours'] = totals['count'].fillna(0).astype(int).to_numpy()
        frame['status'] = ['ok' if n else old if old in ('source_unavailable', 'not_in_network') else 'no_observations'
                           for n, old in zip(frame.valid_hours, frame.status)]
        frame['reason_codes'] = ['' if n else 'no_valid_hourly_observations' for n in frame.valid_hours]
        daily.append(frame)
        write_csv(frame.rename(columns={'object_id': id_column}), output / name)
    coverage = aggregate_daily(pd.concat(daily, ignore_index=True))
    write_csv(coverage, output / 'coverage.csv')
    metadata = pd.read_csv(source / 'site_metadata.csv', keep_default_na=False)
    comparisons = [comparison_rows(coverage, metadata, a, b, statistic, POLICY_ID)
                   for a in range(2021, 2026) for b in range(2021, 2026) if a != b for statistic in ('mean', 'p90')]
    write_csv(pd.concat(comparisons, ignore_index=True), output / 'station_comparisons.csv')
    code_files = ['pipeline/rebuild.py', 'pipeline/io.py', 'analysis/observed_metrics.py', 'analysis/metrics.py']
    build_code = {name: sha256(ROOT / name) for name in code_files}
    outputs = {p.relative_to(output).as_posix(): {'sha256': sha256(p), 'bytes': p.stat().st_size}
               for p in sorted(output.rglob('*')) if p.is_file() and p.name not in ('build_status.json', 'data_manifest.json')}
    fingerprint = {'source_version': original['dataset_version'], 'code': build_code,
                   'outputs': {name: record['sha256'] for name, record in outputs.items()}}
    version = 'sh-pm25-' + hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:16]
    info = {**original, 'dataset_version': version, 'rule_version': RULE_VERSION,
            'pipeline_version': 'standalone-1.0.0', 'outputs': outputs,
            'rebuild': {'source_version': original['dataset_version'], 'source_manifest_sha256': sha256(source / 'data_manifest.json'),
                        'code': build_code, 'created_at': datetime.now(timezone.utc).isoformat()}}
    write_json(info, output / 'data_manifest.json')
    write_json({'status': 'complete', 'dataset_version': version}, output / 'build_status.json')
    return verify(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DATA)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/rebuilt')
    args = parser.parse_args()
    print(json.dumps(rebuild(args.source, args.output), indent=2))
