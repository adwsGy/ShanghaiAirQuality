"""Clean national hourly PM2.5 CSV or ZIP files into a normalized hourly table."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import zipfile

import pandas as pd

from pipeline.io import write_csv, write_json
from pipeline.parsing import collapse_hour, parse_day


def clean(input_file, output_file, source, objects):
    input_file, output_file = Path(input_file).resolve(), Path(output_file).resolve()
    if input_file == output_file:
        raise ValueError('Use a separate output file; original observations must be preserved.')
    if len(set(objects.values())) != len(objects) or not objects:
        raise ValueError('Object IDs must be nonempty and unique.')
    source_level = 'city_archive' if source == 'city' else 'site_archive'
    rows, audits, issues, seen = [], [], [], set()

    def consume(name, body):
        match = re.search(r'(\d{8})\.csv$', name)
        if not match:
            return
        day = datetime.strptime(match[1], '%Y%m%d').date().isoformat()
        if day in seen:
            raise ValueError(f'Duplicate date in input archive: {day}')
        seen.add(day)
        cells, present, audit, problems = parse_day(body, day, list(objects))
        audits.append({'date': day, 'member': name, **audit})
        issues.extend({'date': day, 'member': name, **problem} for problem in problems)
        for label, object_id in objects.items():
            for hour in range(24):
                candidates = cells[label].get(hour, [])
                if candidates:
                    value, status, duplicate_count = collapse_hour(candidates)
                else:
                    value, status, duplicate_count = None, ('missing_row' if label in present else 'missing_column'), 0
                rows.append({'source_level': source_level, 'object_id': object_id, 'date': day, 'hour': hour,
                    'pm25_ug_m3': value, 'status': 'ok' if status == 'ok' else status,
                    'observation_kind': ('original_city_observation' if source == 'city' else 'original_station_observation') if status == 'ok' else 'missing',
                    'source_ref': input_file.name + '::' + name, 'duplicate_cells': duplicate_count})

    if zipfile.is_zipfile(input_file):
        with zipfile.ZipFile(input_file) as archive:
            for member in sorted(archive.namelist()):
                if '__MACOSX' not in member and member.lower().endswith('.csv'):
                    consume(member, archive.read(member))
    else:
        consume(input_file.name, input_file.read_bytes())
    if not rows:
        raise ValueError('No dated CSV files found. Expected a filename ending in YYYYMMDD.csv.')
    frame = pd.DataFrame(rows).sort_values(['object_id', 'date', 'hour'])
    write_csv(frame, output_file)
    report = {'input': input_file.name, 'output': output_file.name, 'dates': len(seen),
              'objects': objects, 'rows': len(frame), 'valid_hours': int(frame.status.eq('ok').sum()),
              'audits': audits, 'issues': issues}
    write_json(report, output_file.with_name(output_file.name + '.audit.json'))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', choices=['city', 'site'], required=True)
    parser.add_argument('--objects', nargs='+', metavar='COLUMN=ID', required=True)
    args = parser.parse_args()
    mapping = {}
    for item in args.objects:
        if '=' not in item or not all(item.split('=', 1)):
            parser.error('--objects entries must be COLUMN=ID.')
        column, object_id = item.split('=', 1)
        if column in mapping:
            parser.error('Duplicate object column.')
        mapping[column] = object_id
    report = clean(args.input, args.output, args.source, mapping)
    print(json.dumps({key: report[key] for key in ('dates', 'rows', 'valid_hours')}, indent=2))
