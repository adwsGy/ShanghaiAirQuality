import unittest
import pandas as pd
from analysis.observed_metrics import daily_value,period_statistics,aggregate_daily

def days(rows):
    return pd.DataFrame([{'date':date,'pm25_ug_m3':value,'status':'ok' if value is not None else 'no_observations','source_level':'city_archive','object_id':'shanghai'} for date,value in rows])

class ObservedStatisticsTests(unittest.TestCase):
    def test_one_hour_and_zero_are_observations(self):
        self.assertEqual(daily_value([8]),(8,1))
        self.assertEqual(daily_value([0,None,-1,float('nan')]),(0,1))
        self.assertEqual(daily_value([None,-1]),(None,0))

    def test_one_day_in_a_year_has_mean_and_p90(self):
        result=period_statistics(days([('2021-03-01',12)]),'2021-01-01','2021-12-31',period_kind='year')
        self.assertEqual(result['status'],'ok');self.assertEqual(result['mean'],12);self.assertEqual(result['p90'],12)
        self.assertEqual(result['valid_days'],1);self.assertEqual(result['expected_days'],365);self.assertEqual(result['failed_months'],'')

    def test_missing_months_and_partial_year_do_not_suppress_values(self):
        table=days([('2021-01-01',10),('2021-03-01',30),('2021-03-02',None)])
        result=period_statistics(table,'2021-01-01','2021-12-31',period_kind='year')
        self.assertEqual(result['mean'],20);self.assertEqual(result['p90'],28)
        partial=period_statistics(table,'2021-03-01','2021-03-31',period_kind='year')
        self.assertEqual(partial['mean'],30);self.assertEqual(partial['status'],'ok')
        self.assertIn('partial_calendar_year',partial['reason_codes'])

    def test_only_empty_samples_have_null_statistics(self):
        result=period_statistics(days([('2021-01-01',None)]),'2021-01-01','2021-01-31')
        self.assertIsNone(result['mean']);self.assertIsNone(result['p90']);self.assertEqual(result['valid_days'],0)
        result=period_statistics(days([('2021-01-01',0)]),'2021-01-01','2021-01-31')
        self.assertEqual(result['mean'],0);self.assertEqual(result['status'],'ok')

    def test_periods_use_days_instead_of_averaging_months(self):
        table=days([('2021-01-01',0),('2021-02-01',100),('2021-02-02',100)])
        result=period_statistics(table,'2021-01-01','2021-02-28')
        self.assertAlmostEqual(result['mean'],200/3)
        self.assertEqual(set(aggregate_daily(table).policy_id),{'observed-only'})
        duplicate=pd.concat([table,table.iloc[:1]])
        with self.assertRaises(ValueError):period_statistics(duplicate,'2021-01-01','2021-02-28')
