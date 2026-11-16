"""Check the workbench queries against independent selections of the daily tables."""
import unittest
import numpy as np
from fastapi.testclient import TestClient
from api.app import create_app
from api.service import Dataset, QueryError, ROOT


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(ROOT / 'data/processed')

    def query(self, task, **context):
        return self.dataset.workspace.execute({
            'dataset_version': self.dataset.version, 'task': task, 'context': context,
        })

    def test_monthly_comparison_matches_daily_samples_and_changes_with_year(self):
        result = self.query('compare', base_year=2022, target_year=2023, months=[2, 8], statistic='p90')
        for row in result['data']['rows']:
            values = []
            for year, key in [(2022, 'base'), (2023, 'target')]:
                prefix = f'{year}-{row["month"]:02d}'
                frame = self.dataset.city
                observed = frame.loc[frame.date.str.startswith(prefix) & frame.status.eq('ok'), 'pm25_ug_m3']
                self.assertEqual(row[key]['n'], len(observed))
                self.assertAlmostEqual(row[key]['p90'], np.quantile(observed, .9), places=9)
                values.append(float(np.quantile(observed, .9)))
            self.assertAlmostEqual(row['delta'], values[1] - values[0], places=9)
        other = self.query('compare', base_year=2021, target_year=2025, months=[2, 8], statistic='p90')
        self.assertNotEqual(result['result_id'], other['result_id'])
        self.assertNotEqual(result['data']['rows'], other['data']['rows'])

    def test_historical_station_daily_and_hourly_use_same_values(self):
        result = self.query('trend', object_id='1141A', start='2018-08-01', end='2018-08-31', granularity='day')
        hours = self.dataset.observation_service.monthly({'dataset_version': self.dataset.version, 'station_id': '1141A', 'month': '2018-08'})
        daily = {r['date']: r['daily_mean'] for r in hours['daily']}
        self.assertEqual(len(result['data']['points']), 31)
        for p in result['data']['points']:
            if daily[p['period']] is None:
                self.assertIsNone(p['mean'])
            else:
                self.assertAlmostEqual(p['mean'], daily[p['period']], places=9)

    def test_one_observed_day_is_kept_and_empty_year_remains_null(self):
        result = self.query('stations', base_year=2021, target_year=2025, station_ids=['1146A'])
        row = result['data']['rows'][0]
        self.assertIsNone(result['summary'])
        self.assertEqual(result['provenance']['source_level'], 'site_archive')
        self.assertEqual(row['base']['n'], 1)
        self.assertIsNotNone(row['base']['mean'])
        self.assertEqual(row['target']['n'], 0)
        self.assertIsNone(row['delta'])

    def test_period_station_query_uses_historical_main_table(self):
        result = self.query('stations', station_mode='period', start='2018-12-01', end='2018-12-31', station_ids=['1141A'])
        row = result['data']['rows'][0]
        expected = self.dataset.site
        expected = expected.loc[expected.object_id.eq('1141A') & expected.date.str.startswith('2018-12') & expected.status.eq('ok')]
        self.assertEqual(row['target']['n'], len(expected))
        self.assertAlmostEqual(row['target']['mean'], expected.pm25_ug_m3.mean(), places=9)

    def test_invalid_query_and_dataset_conflict_are_api_errors(self):
        client = TestClient(create_app())
        request = {'dataset_version': self.dataset.version, 'task': 'compare', 'context': {'base_year': 2023, 'target_year': 2023}}
        self.assertEqual(client.post('/api/v1/workspace/query', json=request).status_code, 422)
        request['dataset_version'] = 'old-version'
        self.assertEqual(client.post('/api/v1/workspace/query', json=request).status_code, 409)
        for context in [{'object_id': 'unknown'}, {'months': []}, {'start': '2025-01-01', 'end': '2024-01-01'}]:
            with self.assertRaises(QueryError):
                self.query('trend', **context)


if __name__ == '__main__':
    unittest.main()
