"""Legacy statistics retained for archived dataset and AI replay checks.
Active available-observation rules are tested in test_observed_metrics.py.
"""
import unittest
import pandas as pd
from analysis.metrics import daily_value,period_statistics,comparison_rows
from pipeline.parsing import parse_number,collapse_hour,parse_day

def days(start,end,value=10):
    return pd.DataFrame({'date':pd.date_range(start,end).strftime('%Y-%m-%d'),
                         'source_level':'city_archive','object_id':'shanghai','status':'ok','pm25_ug_m3':value})

class ResearchRulesTests(unittest.TestCase):
    def test_hour_threshold_and_zero(self):
        self.assertEqual(daily_value([0]*20),(0,20))
        self.assertEqual(daily_value([9]*19),(None,19))
        self.assertEqual(daily_value([1]*20+[-1,float('nan')]),(1,20))
    def test_duplicate_conflict_is_quarantined(self):
        self.assertEqual(collapse_hour([(2,'ok'),(2,'ok')]),(2,'ok',1))
        self.assertEqual(collapse_hour([(2,'ok'),(3,'ok')]),(None,'conflicting_duplicate',1))
        self.assertEqual(parse_number('-1'),(None,'negative_value'))
        self.assertEqual(parse_number('0'),(0,'ok'))
    def test_day_parser_rejects_wrong_date_hour_and_rolling_value(self):
        raw=b'date,hour,type,1141A\n20210101,0,PM2.5,0\n20210101,24,PM2.5,50\n20210102,1,PM2.5,70\n20210101,2,PM2.5_24h,999\n'
        cells,present,audit,issues=parse_day(raw,'2021-01-01',['1141A'])
        self.assertEqual(list(cells['1141A']),[0]);self.assertEqual(audit['invalid_time_rows'],1)
        self.assertEqual(audit['date_mismatch_rows'],1);self.assertEqual(len(issues),2)
    def test_coverage_boundary(self):
        d=days('2021-01-01','2021-01-31');d.loc[24:,'status']='no_observations'
        self.assertEqual(period_statistics(d,'2021-01-01','2021-01-31','study-75','month')['status'],'ok')
        self.assertEqual(period_statistics(d,'2021-01-01','2021-01-31','study-90','month')['status'],'insufficient_coverage')
        d.loc[23,'status']='no_observations'
        self.assertEqual(period_statistics(d,'2021-01-01','2021-01-31','study-75','month')['status'],'insufficient_coverage')
    def test_year_requires_every_month(self):
        d=days('2021-01-01','2021-12-31');d.loc[d['date'].str.startswith('2021-07'),'status']='no_observations'
        r=period_statistics(d,'2021-01-01','2021-12-31','study-75','year')
        self.assertGreater(r['coverage'],.9);self.assertEqual(r['mean'],None);self.assertEqual(r['failed_months'],'2021-07')
    def test_weighted_mean_and_p90_from_days(self):
        d=days('2021-01-01','2021-02-28',0);d.loc[d['date'].str.startswith('2021-02'),'pm25_ug_m3']=100
        r=period_statistics(d,'2021-01-01','2021-02-28','study-75','range')
        self.assertAlmostEqual(r['mean'],2800/59);self.assertEqual(r['p90'],100)
        self.assertNotEqual(r['mean'],50);self.assertNotEqual(r['p90'],50)
    def test_partial_year_and_source_separation(self):
        d=days('2021-01-01','2021-03-31')
        self.assertEqual(period_statistics(d,'2021-01-01','2021-03-31',period_kind='year')['status'],'partial_period')
        other=d.copy();other['object_id']='other'
        with self.assertRaises(ValueError):period_statistics(pd.concat([d,other]),'2021-01-01','2021-03-31')
    def test_zero_baseline_relative_change(self):
        c=pd.DataFrame([{'source_level':'site_archive','object_id':'1141A','period_kind':'year','period':str(y),'policy_id':'study-75','status':'ok','mean':v,'p90':v,'valid_days':365} for y,v in [(2021,0),(2025,1)]])
        r=comparison_rows(c,pd.DataFrame([{'station_id':'1141A','name':'test'}])).iloc[0]
        self.assertEqual(r['absolute_change'],1);self.assertIsNone(r['relative_change_pct'])

if __name__=='__main__':unittest.main()
