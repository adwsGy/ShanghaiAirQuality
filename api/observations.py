"""Hourly inspection of the current, unified city and station observations."""
from __future__ import annotations
import calendar,csv,hashlib,io,json,math,re
from functools import cached_property
import pandas as pd
from api.service import QueryError,invalid

KINDS={'original_city_observation':'城市归档观测','reconstructed_complete9':'完整九站实测重算','original_station_observation':'站点归档观测','openaq_station_observation':'OpenAQ 站点观测','missing':'缺测'}

class ObservationService:
    def __init__(self,dataset):
        self.dataset=dataset
        self.partitions={}

    @cached_property
    def report(self):
        p=self.dataset.directory/'supplemental/manifest.json'
        if 'supplemental/manifest.json' not in self.dataset.manifest['outputs']:return None
        self.checked('supplemental/manifest.json')
        return json.loads(p.read_text(encoding='utf8'))

    def checked(self,name):
        p=self.dataset.directory/name
        if hashlib.sha256(p.read_bytes()).hexdigest()!=self.dataset.manifest['outputs'][name]['sha256']:raise ValueError('Supplement checksum mismatch: '+name)
        return p

    def partition(self,name,kind):
        if name not in self.partitions:
            if len(self.partitions)>=3:self.partitions.pop(next(iter(self.partitions)))
            table=pd.read_csv(self.checked(name),keep_default_na=False,dtype={'date':str,'object_id':str,'station_id':str})
            if 'station_id' in table:table=table.rename(columns={'station_id':'object_id'})
            if 'observation_kind' not in table:table['observation_kind']=table.status.map(lambda s:kind if s=='ok' else 'missing')
            self.partitions[name]=table
        return self.partitions[name]

    def version(self,payload):
        if payload.get('dataset_version')!=self.dataset.version:raise QueryError(409,'DATA_VERSION_CHANGED','数据已更新，请刷新数据连接。')

    def summary(self,payload):
        if set(payload)!={'dataset_version'}:invalid('请提供数据版本。')
        self.version(payload)
        return {'dataset_version':self.dataset.version,'available':self.report is not None,**(self.report or {})}

    def catalog(self,payload):
        if set(payload)!={'dataset_version'}:invalid('请提供数据版本。')
        self.version(payload)
        def months(source):
            years=[int(name.rsplit('_',1)[-1][:4]) for name in self.dataset.manifest['outputs'] if name.startswith('hourly/'+source+'_')]
            return [f'{year}-{month:02d}' for year in sorted(years) for month in range(1,13)]
        objects=[{'object_id':'shanghai','name':'上海全市','months':months('city_archive')}]
        site_months={sid:sorted(g.date.str[:7].unique()) for sid,g in self.dataset.site.groupby('object_id')}
        for station in self.dataset.metadata()['stations']:
            available=site_months.get(station['station_id'],[])
            objects.append({'object_id':station['station_id'],'name':station['name'],'months':sorted(set(available))})
        return {'dataset_version':self.dataset.version,'objects':objects}

    def monthly(self,payload):
        if not {'dataset_version','month','station_id'}.issubset(payload) or set(payload)-{'dataset_version','month','station_id'}:invalid('请提供月份、观测对象和数据版本。')
        self.version(payload)
        month=payload['month'];sid=payload['station_id']
        if not isinstance(month,str) or not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',month) or not '2015-01'<=month<='2025-12':invalid('请选择 2015—2025 年内有效的月份。','month')
        catalog={r['object_id']:r for r in self.catalog({'dataset_version':self.dataset.version})['objects']}
        if not isinstance(sid,str) or sid not in catalog:invalid('请选择有效的观测对象。','station_id')
        if month not in catalog[sid]['months']:invalid('当前研究数据未收录该月份的小时记录。','month')
        city=sid=='shanghai';label=catalog[sid]['name']
        filename=f'hourly/{"city" if city else "site"}_archive_{month[:4]}.csv.gz'
        source=self.partition(filename,'original_city_observation' if city else 'original_station_observation')
        source=source.loc[source.date.str.startswith(month)&source.object_id.eq(sid)]
        lookup={(r['date'],int(r['hour'])):r for r in source.to_dict('records')}
        year,m=map(int,month.split('-'));points=[];daily=[]
        for day in range(1,calendar.monthrange(year,m)[1]+1):
            date=f'{month}-{day:02d}';day_points=[]
            for hour in range(24):
                r=lookup.get((date,hour),{});v=r.get('pm25_ug_m3');value=float(v) if v not in (None,'') else None
                if value is not None and (not math.isfinite(value) or value<0):value=None
                if r.get('observation_kind')=='missing':value=None
                kind=r.get('observation_kind','missing') if value is not None else 'missing'
                p={'date':date,'hour':hour,'datetime_local':f'{date}T{hour:02d}:00:00+08:00','value':value,'kind':kind,'source_ref':r.get('source_ref',''),'station_count':9 if kind=='reconstructed_complete9' else None}
                points.append(p);day_points.append(p)
            good=[p['value'] for p in day_points if p['value'] is not None];counts={k:sum(p['kind']==k for p in day_points) for k in KINDS}
            daily.append({'date':date,'valid_hours':len(good),'daily_mean':math.fsum(good)/len(good) if len(good)>=(1 if self.dataset.observed else 20) else None,'observed_mean':math.fsum(good)/len(good) if good else None,'original_hours':counts['original_city_observation']+counts['original_station_observation'],'added_station_hours':counts['openaq_station_observation'],'reconstructed_hours':counts['reconstructed_complete9'],'missing_hours':counts['missing']})
        counts={k:sum(p['kind']==k for p in points) for k in KINDS}
        context=hashlib.sha256(json.dumps({'kind':'hourly_observations',**payload},sort_keys=True).encode()).hexdigest()[:24]
        method='小时归档观测与当前日均、月度统计使用相同数据版本；保留缺测，不插值。'
        if counts['reconstructed_complete9']:method+='缺失城市小时仅在同小时九个评价站齐全时重算均值，不含青浦背景站；原城市值优先。'
        if counts['openaq_station_observation']:method+='OpenAQ 观测已核对时区、单位与历史站点身份，重叠时保留原归档值。'
        return {'dataset_version':self.dataset.version,'context_id':context,'month':month,'station_id':sid,'label':label,'is_background':sid=='1146A','unit':'μg/m³','timezone':'Asia/Shanghai','summary':{'expected_hours':len(points),'valid_hours':len(points)-counts['missing'],'original_hours':counts['original_city_observation']+counts['original_station_observation'],'added_station_hours':counts['openaq_station_observation'],'reconstructed_hours':counts['reconstructed_complete9'],'missing_hours':counts['missing']},'points':points,'daily':daily,'source_labels':KINDS,'method':method}

    def export(self,payload):
        if set(payload)!={'dataset_version','month','station_id','context_id'}:invalid('请使用当前小时视图导出。')
        query={k:v for k,v in payload.items() if k!='context_id'};result=self.monthly(query)
        if result['context_id']!=payload['context_id']:raise QueryError(409,'CONTEXT_MISMATCH','导出条件与当前小时视图不一致。')
        rows=[{'dataset_version':self.dataset.version,'context_id':result['context_id'],'object_id':result['station_id'],'object_name':result['label'],'unit':result['unit'],'timezone':result['timezone'],**p,'source_label':KINDS[p['kind']]} for p in result['points']]
        buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return buffer.getvalue().encode('utf-8-sig'),result
