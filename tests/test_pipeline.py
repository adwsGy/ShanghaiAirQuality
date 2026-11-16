import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
import pandas as pd

from pipeline.clean import clean
from pipeline.io import DATA, sha256, write_json
from pipeline.rebuild import rebuild
from pipeline.verify import verify


class CleaningTests(unittest.TestCase):
    def test_zip_cleaning_preserves_zero_and_quarantines_conflicting_hours(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source = directory / 'national.zip'
            body = ('date,hour,type,上海\n20230101,0,PM2.5,0\n20230101,0,PM2.5,0\n'
                    '20230101,1,PM2.5,10\n20230101,1,PM2.5,20\n'
                    '20230101,2,PM2.5,-1\n20230101,3,PM2.5,inf\n'
                    '20230101,4,PM2.5_24h,99\n20230101,25,PM2.5,9\n')
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('china_cities_20230101.csv', body.encode('utf-8'))
            original_hash = sha256(source)
            target = directory / 'hourly.csv.gz'
            report = clean(source, target, 'city', {'上海': 'shanghai'})
            rows = pd.read_csv(target, keep_default_na=False)
            self.assertEqual(len(rows), 24)
            self.assertEqual(report['valid_hours'], 1)
            self.assertEqual(float(rows.iloc[0].pm25_ug_m3), 0)
            self.assertEqual(rows.iloc[1].status, 'conflicting_duplicate')
            self.assertEqual(rows.iloc[2].status, 'negative_value')
            self.assertEqual(rows.iloc[3].status, 'nonfinite_value')
            self.assertEqual(rows.iloc[4].pm25_ug_m3, '')
            self.assertEqual(report['issues'][0]['reason'], 'invalid_hour')
            self.assertEqual(sha256(source), original_hash)
            self.assertTrue(target.with_name(target.name + '.audit.json').exists())

    def test_checker_rejects_modified_data_and_incomplete_status(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            file = directory / 'sample.csv'
            file.write_text('value\n1\n', encoding='utf-8')
            write_json({'dataset_version': 'test', 'outputs': {'sample.csv': {'sha256': sha256(file), 'bytes': file.stat().st_size}},
                        'statistics_update': {'policy_id': 'observed-only'}}, directory / 'data_manifest.json')
            write_json({'status': 'complete', 'dataset_version': 'test'}, directory / 'build_status.json')
            self.assertEqual(verify(directory)['files_verified'], 1)
            file.write_text('value\n2\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                verify(directory)
            write_json({'status': 'building'}, directory / 'build_status.json')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                verify(directory)


class RebuildTests(unittest.TestCase):
    def test_included_hourly_data_reproduces_every_daily_and_period_value(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / 'rebuilt'
            original_manifest_hash = sha256(DATA / 'data_manifest.json')
            report = rebuild(DATA, output)
            self.assertEqual(report['files_verified'], 33)
            self.assertNotEqual(report['dataset_version'], json.loads((DATA / 'data_manifest.json').read_text(encoding='utf-8'))['dataset_version'])
            for table in ('city_daily.csv', 'site_daily.csv'):
                a, b = (pd.read_csv(directory / table) for directory in (DATA, output))
                np.testing.assert_allclose(a.pm25_ug_m3, b.pm25_ug_m3, atol=1e-9, rtol=0, equal_nan=True)
                np.testing.assert_array_equal(a.valid_hours, b.valid_hours)
                self.assertEqual(a.status.tolist(), b.status.tolist())
            keys = ['source_level', 'object_id', 'period_kind', 'period', 'policy_id']
            a, b = (pd.read_csv(directory / 'coverage.csv').sort_values(keys).reset_index(drop=True)
                    for directory in (DATA, output))
            self.assertEqual(a[keys].to_dict('records'), b[keys].to_dict('records'))
            for column in ('mean', 'p90', 'median', 'valid_days', 'expected_days'):
                np.testing.assert_allclose(a[column], b[column], atol=1e-9, rtol=0, equal_nan=True)
            self.assertEqual(sha256(DATA / 'data_manifest.json'), original_manifest_hash)
            with self.assertRaisesRegex(ValueError, 'empty'):
                rebuild(DATA, output)


if __name__ == '__main__':
    unittest.main()
