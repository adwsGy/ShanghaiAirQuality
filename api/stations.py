"""Station comparisons share the verified daily statistics and query contract."""
from __future__ import annotations
import csv,io
import pandas as pd
from analysis.metrics import comparison_rows
from api.service import metric,validate,invalid,QueryError

class StationService:
    def __init__(self,dataset):
        self.dataset=dataset
        self.metadata={r['station_id']:r for r in dataset.stations.to_dict('records')}
        self.annual={}
        for row in dataset.coverage.loc[dataset.coverage.source_level.eq('site_archive') & dataset.coverage.period_kind.eq('year')].to_dict('records'):
            for key in ('mean','p90'):row[key]=float(row[key]) if row[key]!='' else None
            self.annual[(row['object_id'],row['policy_id'],int(row['period']))]=row
        self.scales={}
        for key in ('mean','p90'):
            values=[r[key] for r in self.annual.values() if r['status']=='ok']
            self.scales[key]={'min':0,'max':max(values),'unit':'μg/m³','overflow_policy':'clip_with_flag_and_exact_value'}

    def station(self,sid):
        r=self.metadata[sid]
        try:lon,lat=float(r['longitude']),float(r['latitude'])
        except (TypeError,ValueError):lon=lat=None
        usable=lon is not None and lat is not None and -180<=lon<=180 and -90<=lat<=90
        return {'station_id':sid,'name':r['name'],
                'map_coordinate':{'longitude':float(lon),'latitude':float(lat),'crs':'unspecified'} if usable else None,
                'coordinate_status':'unverified' if usable else 'missing',
                'reason_codes':['source_crs_unverified','latest_metadata_coordinate_only'] if usable else ['coordinate_missing']}

    def query(self,payload,schema):
        q=self.dataset.query(payload,schema)
        if schema=='CompareRequest' and q['base_year']==q['target_year']:
            invalid('基准年与对比年必须不同。','target_year')
        if 'station_ids' in q:
            if any(sid not in self.metadata for sid in q['station_ids']):invalid('存在未知的站点编码。','station_ids')
            q['station_ids']=sorted(q['station_ids'])
        return q

    def statistic(self,sid,year,policy,key):
        row=self.annual[(sid,policy,year)]
        return metric(row,key,f'site_archive/{sid}/{year}-01-01/{year}-12-31')

    def common(self,kind,q,ranges,label,ids,usable):
        response=self.dataset.common(kind,q,ranges,label,usable)
        response['scope'].update(source_level='site_archive',station_ids=ids)
        response['warnings']=[{'code':'RESEARCH_RULE','message':'比较仅使用两年均通过同一完整性规则的站点；站点结果不代表行政区均值。','object_ids':ids},
                              {'code':'COORDINATE_UNVERIFIED','message':'地图按最新元数据原始坐标作位置示意，基准未核实，不能用于精确叠加、距离或行政区归属判断。','object_ids':ids}]
        if self.dataset.observed:response['warnings'][0]['message']='各年按已有观测日统计，两期都有观测即可计算差值；站点结果不代表行政区均值。'
        return response

    def compare(self,payload):
        q=self.query(payload,'CompareRequest');a,b=q['base_year'],q['target_year'];key=q['statistic'];policy=q['policy_id']
        computed=comparison_rows(self.dataset.coverage,self.dataset.stations,a,b,key,policy)
        rows=[]
        for r in computed.to_dict('records'):
            sid=r['station_id'];base=self.statistic(sid,a,policy,key);target=self.statistic(sid,b,policy,key)
            rows.append({'station':self.station(sid),'base':base,'target':target,'eligible':bool(r['eligible']),
                         'exclusion_reasons':[f'{label}:{s["status"]}' for label,s in [('base',base),('target',target)] if s['status']!='ok'],
                         'absolute_change':r['absolute_change'] if pd.notna(r['absolute_change']) else None,
                         'relative_change_pct':r['relative_change_pct'] if pd.notna(r['relative_change_pct']) else None,
                         'change_reason_codes':['zero_baseline'] if r['eligible'] and base['value']==0 else []})
        n=sum(r['eligible'] for r in rows);ids=sorted(self.metadata)
        return {**self.common('station_comparison',q,[{'start':f'{y}-01-01','end':f'{y}-12-31'} for y in (a,b)],'两期站点比较',ids,n>0),
                'base_year':a,'target_year':b,'statistic':key,'rows':rows,
                'counts':{'catalog_total':len(rows),'with_coordinates':sum(r['station']['map_coordinate'] is not None for r in rows),'paired':n,'excluded':len(rows)-n},
                'color_scale':self.scales[key]},q

    def trends(self,payload):
        q=self.query(payload,'TrendsRequest');ids=q['station_ids']
        series=[{'station_id':sid,'name':self.metadata[sid]['name'],
                 'yearly':[{'year':y,'statistic':self.statistic(sid,y,q['policy_id'],q['statistic'])} for y in range(2021,2026)]} for sid in ids]
        usable=any(p['statistic']['status']=='ok' for s in series for p in s['yearly'])
        return {**self.common('station_trends',q,[{'start':'2021-01-01','end':'2025-12-31'}],'所选站点五年趋势',ids,usable),
                'statistic':q['statistic'],'series':series},q

    def export(self,payload):
        comparison=payload['result_kind']=='station_comparison'
        validate('StationComparisonExportRequest' if comparison else 'StationTrendsExportRequest',payload)
        result,q=(self.compare if comparison else self.trends)(payload['query'])
        if result['context_id']!=payload['context_id']:
            raise QueryError(409,'CONTEXT_MISMATCH','下载条件与当前结果不一致，请刷新后重试。')
        base={'dataset_version':result['dataset_version'],'context_id':result['context_id'],'policy_id':q['policy_id'],
              'source_level':'site_archive','statistic':q['statistic'],'unit':'μg/m³','rule_version':result['provenance']['rule_version']}
        records=[]
        def flatten(stat):return {k:';'.join(v) if isinstance(v,list) else v for k,v in stat.items()}
        if comparison:
            for r in result['rows']:
                station=r['station'];coord=station['map_coordinate'] or {}
                records.append({**base,'station_id':station['station_id'],'name':station['name'],
                                'base_year':q['base_year'],'target_year':q['target_year'],'eligible':r['eligible'],
                                'absolute_change':r['absolute_change'],'relative_change_pct':r['relative_change_pct'],
                                'exclusion_reasons':';'.join(r['exclusion_reasons']),'change_reason_codes':';'.join(r['change_reason_codes']),
                                **{'base_'+k:v for k,v in flatten(r['base']).items()},**{'target_'+k:v for k,v in flatten(r['target']).items()},
                                'longitude':coord.get('longitude'),'latitude':coord.get('latitude'),'coordinate_crs':coord.get('crs'),
                                'coordinate_status':station['coordinate_status']})
        else:
            for s in result['series']:
                for p in s['yearly']:records.append({**base,'station_id':s['station_id'],'name':s['name'],'year':p['year'],**flatten(p['statistic'])})
        buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
        return buffer.getvalue().encode('utf-8-sig'),result
