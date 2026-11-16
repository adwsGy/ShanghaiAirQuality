import csv,hashlib,io,json,unittest
from itertools import permutations
import pandas as pd
from fastapi.testclient import TestClient
from api.app import create_app
from api.service import ROOT,validator

class StationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(create_app())
        cls.metadata=cls.client.get('/api/v1/metadata').json();cls.version=cls.metadata['dataset_version']
        cls.coverage=pd.read_csv(ROOT/'data/processed/coverage.csv',dtype={'period':str})
        cls.expected={(r['object_id'],r['policy_id'],int(r['period'])):r for r in cls.coverage.loc[cls.coverage.source_level.eq('site_archive')&cls.coverage.period_kind.eq('year')].to_dict('records')}

    def query(self,**kwargs):return {'dataset_version':self.version,'policy_id':'observed-only','base_year':2021,'target_year':2025,'statistic':'mean',**kwargs}
    def post(self,path,q,schema):
        r=self.client.post('/api/v1/'+path,json=q);self.assertEqual(r.status_code,200,r.text)
        data=r.json();validator(schema).validate(data);return data

    def test_all_year_orders_rules_statistics_against_research_table(self):
        for a,b in permutations(range(2021,2026),2):
            for policy in ['observed-only']:
                for metric in ['mean','p90']:
                    data=self.post('stations/compare',self.query(base_year=a,target_year=b,policy_id=policy,statistic=metric),'StationComparison')
                    self.assertEqual(len(data['rows']),22)
                    self.assertEqual(data['scope']['source_level'],'site_archive')
                    for row in data['rows']:
                        sid=row['station']['station_id'];x=self.expected[(sid,policy,a)];y=self.expected[(sid,policy,b)]
                        eligible=x['status']=='ok' and y['status']=='ok'
                        self.assertEqual(row['eligible'],eligible)
                        for actual,expected in [(row['base'],x),(row['target'],y)]:
                            self.assertEqual(actual['status'],expected['status'])
                            self.assertEqual(actual['valid_days'],expected['valid_days'])
                            if expected['status']=='ok':self.assertAlmostEqual(actual['value'],expected[metric],places=10)
                            else:self.assertIsNone(actual['value'])
                        if eligible:
                            self.assertAlmostEqual(row['absolute_change'],y[metric]-x[metric],places=10)
                            self.assertAlmostEqual(row['relative_change_pct'],(y[metric]-x[metric])/x[metric]*100,places=10)
                        else:
                            self.assertIsNone(row['absolute_change']);self.assertIsNone(row['relative_change_pct']);self.assertTrue(row['exclusion_reasons'])
                    self.assertEqual(data['counts']['paired'],sum(r['eligible'] for r in data['rows']))

    def test_pair_count_includes_stations_with_any_observed_days(self):
        data=self.post('stations/compare',self.query(),'StationComparison')
        self.assertEqual(data['counts'],{'catalog_total':22,'with_coordinates':22,'paired':19,'excluded':3})
        sparse=next(r for r in data['rows'] if r['station']['station_id']=='1144A')
        self.assertTrue(sparse['eligible']);self.assertEqual(sparse['target']['valid_days'],9)
        self.assertIsNotNone(sparse['absolute_change'])
        old=self.client.post('/api/v1/stations/compare',json=self.query(policy_id='study-90'))
        self.assertEqual(old.status_code,422)

    def test_trends_keep_five_years_and_nonpaired_stations(self):
        q={'dataset_version':self.version,'policy_id':'observed-only','station_ids':['1144A','4183A','3272A'],'statistic':'mean'}
        data=self.post('stations/trends',q,'StationTrends')
        self.assertEqual(len(data['series']),3)
        for s in data['series']:self.assertEqual([p['year'] for p in s['yearly']],list(range(2021,2026)))
        old=next(s for s in data['series'] if s['station_id']=='1144A')
        self.assertIsNotNone(old['yearly'][-1]['statistic']['value'])
        self.assertEqual(old['yearly'][-1]['statistic']['valid_days'],9)
        empty=next(s for s in data['series'] if s['station_id']=='4183A')
        self.assertTrue(all(p['statistic']['status']=='no_observations' for p in empty['yearly']))
        reordered=self.post('stations/trends',{**q,'station_ids':list(reversed(q['station_ids']))},'StationTrends')
        self.assertEqual(data['context_id'],reordered['context_id'])

    def test_unknown_excess_duplicate_years_and_versions(self):
        bad=[self.query(target_year=2021),self.query(base_year=2020),self.query(statistic='median'),self.query(extra=True)]
        for q in bad:self.assertEqual(self.client.post('/api/v1/stations/compare',json=q).status_code,422)
        trend={'dataset_version':self.version,'policy_id':'observed-only','statistic':'mean'}
        for ids in [[],['9999A'],['1141A','1141A'],['1141A','1142A','1143A','1144A']]:
            r=self.client.post('/api/v1/stations/trends',json={**trend,'station_ids':ids})
            self.assertEqual(r.status_code,422);validator('Error').validate(r.json())
        self.assertEqual(self.client.post('/api/v1/stations/compare',json=self.query(dataset_version='old')).status_code,409)

    def test_comparison_export_keeps_all_exclusions_and_exact_values(self):
        q=self.query();result=self.post('stations/compare',q,'StationComparison')
        payload={'result_kind':'station_comparison','query':q,'context_id':result['context_id']}
        r=self.client.post('/api/v1/exports',json=payload);self.assertEqual(r.status_code,200)
        self.assertTrue(r.content.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),22);self.assertEqual(sum(x['eligible']=='True' for x in rows),19)
        self.assertTrue(all(x['source_level']=='site_archive' and x['coordinate_status']=='unverified' for x in rows))
        for row in result['rows']:
            record=next(x for x in rows if x['station_id']==row['station']['station_id'])
            self.assertEqual(record['context_id'],result['context_id'])
            if row['eligible']:self.assertAlmostEqual(float(record['absolute_change']),row['absolute_change'])
            else:self.assertEqual(record['absolute_change'],'');self.assertTrue(record['exclusion_reasons'])
        payload['context_id']='incorrect';self.assertEqual(self.client.post('/api/v1/exports',json=payload).status_code,409)

    def test_trend_export_retains_null_years_and_normalizes_ids(self):
        q={'dataset_version':self.version,'policy_id':'observed-only','station_ids':['3272A','1144A'],'statistic':'p90'}
        result=self.post('stations/trends',q,'StationTrends')
        r=self.client.post('/api/v1/exports',json={'result_kind':'station_trends','context_id':result['context_id'],'query':q})
        self.assertEqual(r.status_code,200)
        rows=list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),10)
        missing=next(x for x in rows if x['station_id']=='1144A' and x['year']=='2025')
        self.assertNotEqual(missing['value'],'');self.assertEqual(missing['valid_days'],'9')

    def test_local_geometry_matches_manifest_without_claiming_crs(self):
        p=ROOT/'frontend/public/geometry/shanghai.geojson'
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.metadata['geometry']['sha256'])
        self.assertEqual(len(json.loads(p.read_text(encoding='utf-8'))['features']),16)
        self.assertEqual(self.metadata['geometry']['crs'],'unspecified')
        self.assertTrue(all(s['coordinate_status']=='unverified' for s in self.metadata['stations']))

    def test_missing_coordinate_keeps_comparison_and_trend_access(self):
        from api.service import Dataset
        from api.stations import StationService
        service=StationService(Dataset(ROOT/'data/processed'))
        service.metadata['1142A']['longitude']=''
        result,_=service.compare(self.query())
        row=next(r for r in result['rows'] if r['station']['station_id']=='1142A')
        self.assertTrue(row['eligible']);self.assertIsNone(row['station']['map_coordinate'])
        self.assertEqual(row['station']['coordinate_status'],'missing')
        self.assertEqual(result['counts']['with_coordinates'],21)
        trend,_=service.trends({'dataset_version':self.version,'policy_id':'observed-only','station_ids':['1142A'],'statistic':'mean'})
        self.assertEqual(len(trend['series'][0]['yearly']),5)

    def test_zero_baseline_preserves_absolute_change_and_explains_relative_null(self):
        from api.service import Dataset
        from api.stations import StationService
        dataset=Dataset(ROOT/'data/processed')
        frame=dataset.coverage
        mask=frame.source_level.eq('site_archive') & frame.object_id.eq('1142A') & frame.policy_id.eq('observed-only') & frame.period.eq('2021')
        dataset.coverage.loc[mask,'mean']='0'
        result,_=StationService(dataset).compare(self.query())
        row=next(r for r in result['rows'] if r['station']['station_id']=='1142A')
        self.assertAlmostEqual(row['absolute_change'],row['target']['value'])
        self.assertIsNone(row['relative_change_pct'])
        self.assertEqual(row['change_reason_codes'],['zero_baseline'])

if __name__=='__main__':unittest.main()
