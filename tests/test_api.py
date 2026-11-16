import csv,io,json,tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from api.app import create_app
from api.service import ROOT,validator

class CityApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(create_app())
        cls.version=cls.client.get('/api/v1/metadata').json()['dataset_version']

    def query(self,**kwargs):
        return {'dataset_version':self.version,'policy_id':'observed-only',
                'analysis_range':{'start':'2015-01-01','end':'2025-12-31'},'granularity':'month',**kwargs}

    def post(self,path,payload,schema):
        r=self.client.post('/api/v1/'+path,json=payload)
        self.assertEqual(r.status_code,200,r.text)
        data=r.json();validator(schema).validate(data);return data

    def test_metadata_contract_and_unverified_coordinates(self):
        data=self.client.get('/api/v1/metadata').json();validator('Metadata').validate(data)
        self.assertEqual(len(data['stations']),22)
        self.assertTrue(all(s['coordinate_status']=='unverified' for s in data['stations']))
        self.assertTrue(all(s['map_coordinate']['crs']=='unspecified' for s in data['stations']))

    def test_full_analysis_uses_every_observed_day(self):
        for policy in ['observed-only']:
            for kind in ['month','year']:
                data=self.post('city/analyze',self.query(policy_id=policy,granularity=kind),'CityAnalysis')
                self.assertEqual(len(data['overview']),132)
                self.assertEqual(len(data['heatmap']),132)
                self.assertEqual(len(data['trend']),132 if kind=='month' else 11)
                if kind=='year':
                    year=next(b for b in data['trend'] if b['period']=='2018')
                    self.assertIsNotNone(year['metrics']['mean']['value'])
                    self.assertEqual(year['metrics']['mean']['status'],'ok')

    def test_partial_years_compute_the_selected_dates(self):
        data=self.post('city/analyze',self.query(granularity='year',analysis_range={'start':'2021-06-01','end':'2022-07-31'}),'CityAnalysis')
        self.assertEqual(len(data['overview']),132)
        self.assertEqual(len(data['heatmap']),14)
        self.assertTrue(all(b['metrics']['mean']['status']=='ok' for b in data['trend']))
        self.assertTrue(all('partial_calendar_year' in b['metrics']['mean']['reason_codes'] for b in data['trend']))
        self.assertTrue(all(b['metrics']['p90']['value'] is not None for b in data['trend']))

    def test_month_detail_missing_source_and_leap_day(self):
        for month,count in [('2015-01',31),('2024-02',29),('2018-08',31)]:
            data=self.post('city/detail',{'dataset_version':self.version,'policy_id':'observed-only','detail_mode':'month','month':month},'CityDetail')
            self.assertEqual(len(data['daily']),count)
            if month=='2015-01':
                self.assertEqual(data['daily'][0]['status'],'source_unavailable')
                self.assertIsNone(data['daily'][0]['value'])
            if month=='2018-08':
                self.assertEqual(data['summary']['mean']['valid_days'],31)
                self.assertIsNotNone(data['summary']['mean']['value'])

    def test_profiles_normalized_context_and_complete_months(self):
        q={'dataset_version':self.version,'policy_id':'observed-only','detail_mode':'profiles','years':[2025,2018,2021]}
        data=self.post('city/detail',q,'CityDetail')
        other=self.post('city/detail',{**q,'years':sorted(q['years'])},'CityDetail')
        self.assertEqual(data['context_id'],other['context_id'])
        self.assertEqual([p['year'] for p in data['profiles']],[2018,2021,2025])
        self.assertTrue(all(len(p['months'])==12 for p in data['profiles']))

    def test_invalid_queries_and_old_version(self):
        bad=[self.query(analysis_range={'start':'2021-02-30','end':'2021-03-31'}),
             self.query(analysis_range={'start':'2022-01-01','end':'2021-12-31'}),
             self.query(analysis_range={'start':'2021-01-02','end':'2021-12-31'}),
             self.query(analysis_range={'start':'2014-01-01','end':'2021-12-31'}),
             self.query(unknown=True)]
        for q in bad:
            r=self.client.post('/api/v1/city/analyze',json=q)
            self.assertEqual(r.status_code,422);validator('Error').validate(r.json())
        r=self.client.post('/api/v1/city/analyze',json=self.query(dataset_version='old'))
        self.assertEqual(r.status_code,409)
        self.assertEqual(r.json()['error']['code'],'DATA_VERSION_CHANGED')
        r=self.client.post('/api/v1/city/detail',json={'dataset_version':self.version,'policy_id':'observed-only','detail_mode':'profiles','years':[2018,2021,2022,2025]})
        self.assertEqual(r.status_code,422)

    def test_month_with_partial_hours_still_has_statistics(self):
        data=self.post('city/analyze',self.query(analysis_range={'start':'2018-08-01','end':'2018-08-31'}),'CityAnalysis')
        self.assertEqual(data['status'],'ok')
        self.assertEqual(data['selected_range_summary']['mean']['valid_days'],31)

    def test_export_matches_values_context_and_scope(self):
        q=self.query(analysis_range={'start':'2021-01-01','end':'2021-12-31'})
        data=self.post('city/analyze',q,'CityAnalysis')
        payload={'result_kind':'city_analysis','query':q,'context_id':data['context_id']}
        r=self.client.post('/api/v1/exports',json=payload)
        self.assertEqual(r.status_code,200);self.assertTrue(r.content.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(r.headers['x-context-id'],data['context_id'])
        rows=list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),26)
        first=next(row for row in rows if row['period']=='2021-01' and row['statistic']=='mean')
        self.assertAlmostEqual(float(first['value']),data['trend'][0]['metrics']['mean']['value'])
        self.assertEqual(first['dataset_version'],self.version)
        payload['context_id']='wrong'
        self.assertEqual(self.client.post('/api/v1/exports',json=payload).status_code,409)

    def test_daily_and_profile_exports_preserve_missing_rows(self):
        for detail in [{'detail_mode':'month','month':'2015-01'},{'detail_mode':'profiles','years':[2018,2021,2025]}]:
            q={'dataset_version':self.version,'policy_id':'observed-only',**detail}
            result=self.post('city/detail',q,'CityDetail')
            r=self.client.post('/api/v1/exports',json={'result_kind':'city_detail','query':q,'context_id':result['context_id']})
            self.assertEqual(r.status_code,200)
            rows=list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig'))))
            if detail['detail_mode']=='month':
                self.assertEqual(len(rows),33)
                self.assertEqual(rows[0]['value'],'')
                self.assertEqual(rows[0]['status'],'source_unavailable')
            else:self.assertEqual(len(rows),72)

    def test_unready_data_returns_actionable_503(self):
        with tempfile.TemporaryDirectory() as directory:
            c=TestClient(create_app(Path(directory)))
            r=c.get('/api/v1/metadata')
            self.assertEqual(r.status_code,503);validator('Error').validate(r.json())

    def test_built_frontend_is_served_with_assets(self):
        if not (ROOT/'frontend/dist/index.html').is_file():
            self.skipTest('Run npm run build before checking built frontend delivery.')
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        import re
        asset=re.search(r'src="(/assets/[^\"]+)"',response.text).group(1)
        self.assertEqual(self.client.get(asset).status_code,200)

if __name__=='__main__':unittest.main()
