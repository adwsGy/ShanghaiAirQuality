"""Data adapter for the agreed city-analysis contract. No chart-side statistics."""
from __future__ import annotations
from datetime import date
from pathlib import Path
from functools import lru_cache,cached_property
import calendar,csv,hashlib,io,json
import pandas as pd
from jsonschema import Draft202012Validator,FormatChecker
from analysis.metrics import period_statistics
from analysis.observed_metrics import period_statistics as observed_statistics,POLICY_ID

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=json.loads((ROOT/'api/contracts/analysis.openapi.json').read_text(encoding='utf-8'))
CONTRACT_VERSION=CONTRACT['info']['version']
SOURCE='city_archive'
FULL={'start':'2015-01-01','end':'2025-12-31'}

class QueryError(Exception):
    def __init__(self,status,code,message,fields=None):
        self.status,self.code,self.message,self.fields=status,code,message,fields or []

def invalid(message,field='query'):
    raise QueryError(422,'INVALID_QUERY',message,[{'field':field,'reason':message}])

@lru_cache(maxsize=16)
def validator(name):
    return Draft202012Validator({'$ref':f'#/components/schemas/{name}','components':CONTRACT['components']},format_checker=FormatChecker())

def validate(name,payload):
    errors=list(validator(name).iter_errors(payload))
    if errors:
        fields=[{'field':'.'.join(map(str,e.absolute_path)) or 'query','reason':e.message} for e in errors[:5]]
        raise QueryError(422,'INVALID_QUERY','查询格式不正确，请检查日期、范围和选择数量。',fields)

def month_range(ym):
    y,m=map(int,ym.split('-'))
    return {'start':f'{ym}-01','end':f'{ym}-{calendar.monthrange(y,m)[1]:02d}'}

def check_range(scope):
    a,b=date.fromisoformat(scope['start']),date.fromisoformat(scope['end'])
    if a>b:invalid('开始月份不能晚于结束月份。','analysis_range')
    if scope['start']<FULL['start'] or scope['end']>FULL['end']:
        invalid('研究范围为 2015 年 1 月至 2025 年 12 月。','analysis_range')
    if a.day!=1 or b.day!=calendar.monthrange(b.year,b.month)[1]:
        invalid('分析范围必须从月初开始、到月末结束。','analysis_range')

def split_codes(value):
    return str(value).split(';') if value else []

def metric(row,key,locator):
    value=row[key]
    return {'value':None if value is None or pd.isna(value) else float(value),
            'status':row['status'],'reason_codes':split_codes(row['reason_codes']),
            'valid_days':int(row['valid_days']),'expected_days':int(row['expected_days']),
            'coverage':float(row['coverage']),'failed_months':split_codes(row['failed_months']),
            'source_locator':locator}

class Dataset:
    @cached_property
    def workspace(self):
        from api.workspace import WorkspaceService
        return WorkspaceService(self)

    @cached_property
    def site(self):
        name='site_daily.csv'
        if hashlib.sha256((self.directory/name).read_bytes()).hexdigest()!=self.manifest['outputs'][name]['sha256']:raise ValueError('Station daily checksum mismatch')
        return pd.read_csv(self.directory/name,dtype={'date':str,'station_id':str}).rename(columns={'station_id':'object_id'}).fillna({'reason_codes':''})

    @cached_property
    def observation_service(self):
        from api.observations import ObservationService
        return ObservationService(self)

    @cached_property
    def station_service(self):
        from api.stations import StationService
        return StationService(self)

    def __init__(self,directory):
        self.directory=directory
        self.manifest=json.loads((directory/'data_manifest.json').read_text(encoding='utf-8'))
        self.version=self.manifest['dataset_version']
        self.observed=self.manifest.get('statistics_update',{}).get('policy_id')==POLICY_ID
        for name in ['city_daily.csv','coverage.csv','site_metadata.csv','geometry_metadata.json']:
            digest=hashlib.sha256((directory/name).read_bytes()).hexdigest()
            if digest!=self.manifest['outputs'][name]['sha256']:
                raise ValueError(f'Output checksum mismatch: {name}')
        self.city=pd.read_csv(directory/'city_daily.csv',dtype={'date':str}).rename(columns={'city_id':'object_id'})
        self.city=self.city.fillna({'reason_codes':''})
        self.coverage=pd.read_csv(directory/'coverage.csv',dtype={'period':str},keep_default_na=False)
        self.stations=pd.read_csv(directory/'site_metadata.csv',keep_default_na=False)
        self.geometry=json.loads((directory/'geometry_metadata.json').read_text(encoding='utf-8'))
        self.cached={}
        for row in self.coverage.loc[self.coverage.source_level.eq(SOURCE)].to_dict('records'):
            for key in ('mean','p90'):row[key]=float(row[key]) if row[key]!='' else None
            self.cached[(row['policy_id'],row['period'])]=row
        self.scales={key:{'min':0,'max':float(self.coverage.loc[self.coverage.source_level.eq(SOURCE),key].replace('',float('nan')).astype(float).max()),
                          'unit':'μg/m³','overflow_policy':'clip_with_flag_and_exact_value'} for key in ('mean','p90')}

    def metadata(self):
        return {'contract_version':CONTRACT_VERSION,'dataset_version':self.version,'city_range':FULL,
                'station_range':{'start':'2021-01-01','end':'2025-12-31'},'unit':'μg/m³','timezone':'Asia/Shanghai',
                'policies':([{'policy_id':POLICY_ID,'min_valid_hours':1,'monthly_min_coverage':0,'annual_min_coverage':0,'require_all_months':False,'quantile_method':'linear'}] if self.observed else [{'policy_id':f'study-{p}','min_valid_hours':20,'monthly_min_coverage':p/100,
                             'annual_min_coverage':p/100,'require_all_months':True,'quantile_method':'linear'} for p in (75,90)]),
                'stations':[self.station_service.station(sid) for sid in sorted(self.station_service.metadata)],
                'geometry':{'asset_path':'/geometry/shanghai.geojson','sha256':self.geometry['sha256'],
                            'crs':'unspecified','source_url':'https://geo.datav.aliyun.com/areas_v3/bound/310000_full.json',
                            'coordinate_note':'站点坐标基准未核实，地图叠加前继续核对。'}}

    def query(self,payload,schema):
        validate(schema,payload)
        if payload['dataset_version']!=self.version:
            raise QueryError(409,'DATA_VERSION_CHANGED','数据版本已变化，请重新载入当前数据。')
        if self.observed and payload['policy_id']!=POLICY_ID:invalid('当前按已有观测计算，请重新读取统计口径。','policy_id')
        q=json.loads(json.dumps(payload))
        if 'years' in q:q['years']=sorted(q['years'])
        if 'analysis_range' in q:check_range(q['analysis_range'])
        if q.get('detail_mode')=='month':
            scope=month_range(q['month']);check_range(scope)
        return q

    def metrics(self,scope,policy,kind='range'):
        label=scope['start'][:7] if kind=='month' else scope['start'][:4]
        row=self.cached.get((policy,label)) if kind in ('month','year') else None
        # Annual windows may be clipped; these must remain partial_period.
        if row is None or row['start']!=scope['start'] or row['end']!=scope['end']:
            row=(observed_statistics if self.observed else period_statistics)(self.city,scope['start'],scope['end'],policy,kind)
        locator=f'{SOURCE}/shanghai/{scope["start"]}/{scope["end"]}'
        return {k:metric(row,k,locator) for k in ('mean','p90')}

    def buckets(self,scope,policy,kind):
        results=[]
        for period in pd.period_range(scope['start'],scope['end'],freq='M' if kind=='month' else 'Y'):
            bounds={'start':max(scope['start'],period.start_time.strftime('%Y-%m-%d')),
                    'end':min(scope['end'],period.end_time.strftime('%Y-%m-%d'))}
            results.append({'period':str(period),'range':bounds,'metrics':self.metrics(bounds,policy,kind)})
        return results

    def common(self,kind,q,ranges,label,usable):
        context=hashlib.sha256(json.dumps({'kind':kind,'query':q},sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
        response={'contract_version':CONTRACT_VERSION,'dataset_version':self.version,'context_id':context,
                'policy_id':q['policy_id'],'status':'ok' if usable else 'empty',
                'scope':{'source_level':SOURCE,'city_id':'shanghai','station_ids':[],'ranges':ranges,'label':label},
                'warnings':[{'code':'RESEARCH_RULE','message':'完整性门槛为本研究规则，不代表官方达标评价。','object_ids':['shanghai']},
                            {'code':'TIME_CONVENTION','message':'沿用北京时间日历及来源小时标签，来源无时区偏移字段。','object_ids':['shanghai']}],
                'provenance':{'manifest_id':self.version,'rule_version':self.manifest['rule_version'],
                              'pipeline_version':self.manifest['pipeline_version']}}
        if self.manifest.get('supplemental') and any(r['start']<='2018-12-31' and r['end']>='2018-12-01' for r in ranges):
            response['warnings'].append({'code':'RECOVERED_CITY_HOURS','message':'2018 年 12 月含 69 个完整九站实测重算小时；原城市值优先，具体来源可在小时记录的来源详情中核查。','object_ids':['shanghai']})
        if self.observed:response['warnings'][0]['message']='按已有观测日计算均值与 P90，未观测日期不补零；结果为观测样本统计。'
        return response

    def analyze(self,payload):
        q=self.query(payload,'CityRequest');scope=q['analysis_range'];policy=q['policy_id']
        monthly=self.buckets(scope,policy,'month')
        trend=monthly if q['granularity']=='month' else self.buckets(scope,policy,'year')
        heat=[{'year':int(b['period'][:4]),'month':int(b['period'][5:7]),'statistic':b['metrics']['mean']} for b in monthly]
        response={**self.common('city_analysis',q,[scope],'所选时段',any(b['metrics']['mean']['value'] is not None for b in trend)),
                  'overview':self.buckets(FULL,policy,'month'),'trend':trend,'heatmap':heat,
                  'selected_range_summary':self.metrics(scope,policy),'color_scales':self.scales}
        return response,q

    def detail(self,payload):
        q=self.query(payload,'CityDetailRequest');policy=q['policy_id'];mode=q['detail_mode']
        if mode=='profiles':
            profiles=[];ranges=[]
            for year in q['years']:
                scope={'start':f'{year}-01-01','end':f'{year}-12-31'};ranges.append(scope)
                months=self.buckets(scope,policy,'month')
                profiles.append({'year':year,'months':[{'year':year,'month':i+1,'statistic':b['metrics']['mean']} for i,b in enumerate(months)],
                                 'p90_by_month':[b['metrics']['p90'] for b in months]})
            usable=any(m['statistic']['value'] is not None for p in profiles for m in p['months'])
            return {**self.common('city_detail',q,ranges,'完整年份剖面对比',usable),'detail_mode':mode,'profiles':profiles},q
        scope=month_range(q['month']) if mode=='month' else q['analysis_range']
        rows=self.city.loc[self.city.date.between(scope['start'],scope['end'])]
        daily=[{'date':r['date'],'value':None if pd.isna(r['pm25_ug_m3']) else float(r['pm25_ug_m3']),
                'valid_hours':int(r['valid_hours']),'status':r['status'],'reason_codes':split_codes(r['reason_codes'])} for r in rows.to_dict('records')]
        return {**self.common('city_detail',q,[scope],'月份日均' if mode=='month' else '所选时段日均',any(r['value'] is not None for r in daily)),
                'detail_mode':mode,'daily':daily,'summary':self.metrics(scope,policy,'month' if mode=='month' else 'range')},q

    def export(self,payload):
        kind=payload.get('result_kind')
        if kind in ('station_comparison','station_trends'):return self.station_service.export(payload)
        if kind not in ('city_analysis','city_detail'):invalid('未知的结果导出类型。','result_kind')
        validate('CityAnalysisExportRequest' if kind=='city_analysis' else 'CityDetailExportRequest',payload)
        result,q=(self.analyze if kind=='city_analysis' else self.detail)(payload['query'])
        if result['context_id']!=payload['context_id']:
            raise QueryError(409,'CONTEXT_MISMATCH','下载条件与当前结果不一致，请刷新后重试。')
        base={'dataset_version':self.version,'context_id':result['context_id'],'policy_id':q['policy_id'],
              'source_level':SOURCE,'city_id':'shanghai','unit':'μg/m³','rule_version':self.manifest['rule_version']}
        records=[]
        def add_metric(label,scope,metrics):
            days=self.city.loc[self.city.date.between(scope['start'],scope['end'])]
            origin={'reconstructed_hours':int(days['reconstructed_hours'].sum()),'observation_basis':'city_observation_and_complete9' if days['reconstructed_hours'].sum() else 'original_city_observation'} if 'reconstructed_hours' in days else {}
            for statistic,m in metrics.items():
                records.append({**base,'record_kind':'statistic','period':label,'start':scope['start'],'end':scope['end'],
                                'statistic':statistic,**origin,**{k:';'.join(v) if isinstance(v,list) else v for k,v in m.items()}})
        if kind=='city_analysis':
            for b in result['trend']:add_metric(b['period'],b['range'],b['metrics'])
            add_metric('selected_range_summary',q['analysis_range'],result['selected_range_summary'])
        elif result['detail_mode']=='profiles':
            for p in result['profiles']:
                for i,m in enumerate(p['months']):
                    ym=f'{p["year"]}-{i+1:02d}'
                    add_metric(ym,month_range(ym),{'mean':m['statistic'],'p90':p['p90_by_month'][i]})
        else:
            for d in result['daily']:
                row=self.city.loc[self.city.date.eq(d['date'])].iloc[0]
                origin={k:row[k] for k in ['original_valid_hours','reconstructed_hours','observation_basis','source_ref'] if k in row}
                records.append({**base,'record_kind':'daily',**{k:';'.join(v) if isinstance(v,list) else v for k,v in d.items()},**origin,
                                'source_locator':f'{SOURCE}/shanghai/{d["date"]}'})
            add_metric('detail_summary',result['scope']['ranges'][0],result['summary'])
        headers=list(dict.fromkeys(k for r in records for k in r))
        stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=headers)
        writer.writeheader();writer.writerows(records)
        return stream.getvalue().encode('utf-8-sig'),result
