"""Shared, deterministic queries for the workbench and subsequent agent tools."""
from __future__ import annotations
import calendar,hashlib,json,math
from datetime import date
import numpy as np
import pandas as pd
from pydantic import BaseModel,ConfigDict,Field,ValidationError,model_validator
from typing import Literal
from api.service import QueryError,invalid

class AnalysisContext(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    object_id:str='shanghai'
    start:str='2015-01-01'
    end:str='2025-12-31'
    statistic:Literal['mean','p90']='mean'
    granularity:Literal['year','month','day']='year'
    base_year:int=Field(default=2022,ge=2015,le=2025)
    target_year:int=Field(default=2023,ge=2015,le=2025)
    months:list[int]=Field(default_factory=lambda:list(range(1,13)))
    station_ids:list[str]=Field(default_factory=list)
    selected_station_ids:list[str]=Field(default_factory=list,max_length=3)
    direction:Literal['all','up','down']='all'
    station_mode:Literal['compare','period']='compare'
    threshold:float=Field(default=75,ge=0,le=1000)
    episode_min_days:int=Field(default=2,ge=1,le=31)
    station_sort:Literal['delta_asc','delta_desc','target_desc']='delta_asc'
    season_definition:Literal['calendar_winter','cross_year_winter']|None=None

    @model_validator(mode='after')
    def check(self):
        try:a,b=date.fromisoformat(self.start),date.fromisoformat(self.end)
        except ValueError:raise ValueError('日期格式无效')
        if a>b or self.start<'2015-01-01' or self.end>'2025-12-31':raise ValueError('请选择 2015—2025 年内的日期范围')
        if not self.months or any(m<1 or m>12 for m in self.months):raise ValueError('月份需要在 1—12 之间')
        self.months=sorted(set(self.months));self.station_ids=sorted(set(self.station_ids));self.selected_station_ids=list(dict.fromkeys(self.selected_station_ids))
        if self.season_definition and self.months != [1,2,12]:raise ValueError('冬季定义对应 1、2、12 月；选择其他月份时请清除冬季定义')
        if self.season_definition=='cross_year_winter' and (not self.start.endswith('-01-01') or not self.end.endswith('-12-31') or self.start<'2016-01-01'):raise ValueError('跨年冬季按结束年命名，请选择 2016—2025 年的完整年份范围')
        return self

TASKS=Literal['trend','season','compare','stations','distribution','episodes','station_trends']
class WorkspaceRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_version:str
    task:TASKS='trend'
    context:AnalysisContext=Field(default_factory=AnalysisContext)

def signature(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:24]

def summarize(frame,expected):
    values=pd.to_numeric(frame.loc[frame.status.eq('ok'),'pm25_ug_m3'],errors='coerce').dropna().to_numpy(dtype=float)
    values=values[np.isfinite(values)&(values>=0)]
    return {'mean':float(values.mean()) if len(values) else None,'p90':float(np.quantile(values,.9)) if len(values) else None,
            'n':len(values),'expected':int(expected),'unit':'μg/m³'}

class WorkspaceService:
    def __init__(self,dataset):
        self.dataset=dataset
        self.catalog={s['station_id']:s for s in dataset.metadata()['stations']}

    def validate(self,payload):
        try:q=WorkspaceRequest.model_validate(payload)
        except ValidationError as e:invalid(str(e.errors()[0]['msg']))
        if q.dataset_version!=self.dataset.version:raise QueryError(409,'DATA_VERSION_CHANGED','数据已更新，请重新载入。')
        c=q.context
        if c.object_id!='shanghai' and c.object_id not in self.catalog:invalid('未知监测站。','object_id')
        if any(s not in self.catalog for s in [*c.station_ids,*c.selected_station_ids]):invalid('未知监测站。','station_ids')
        if q.task in ('compare','distribution') or q.task=='stations' and c.station_mode=='compare':
            if c.base_year==c.target_year:invalid('请选择两个不同的比较年份。')
            c.start=f'{min(c.base_year,c.target_year)}-01-01';c.end=f'{max(c.base_year,c.target_year)}-12-31'
        return q

    def table(self,object_id):
        return self.dataset.city if object_id=='shanghai' else self.dataset.site.loc[self.dataset.site.object_id.eq(object_id)]

    def label(self,object_id):return '上海全市' if object_id=='shanghai' else self.catalog[object_id]['name']

    def window(self,frame,start,end,months):
        dates=pd.date_range(start,end).strftime('%Y-%m-%d')
        chosen={d for d in dates if int(d[5:7]) in months}
        return frame.loc[frame.date.isin(chosen)],len(chosen)

    def year_window(self,frame,year,c):
        start=f'{year}-01-01';end=f'{year}-12-31'
        if c.season_definition=='cross_year_winter':
            start=f'{year-1}-12-01';end=f'{year}-02-{calendar.monthrange(year,2)[1]}'
            if start<'2015-01-01':invalid('跨年冬季超出研究日期范围。')
        return self.window(frame,start,end,c.months)

    def domain(self,c):
        if c.season_definition=='cross_year_winter':
            return f'{int(c.start[:4])-1}-12-01',f'{c.end[:4]}-02-{calendar.monthrange(int(c.end[:4]),2)[1]}'
        return c.start,c.end

    def selection(self,frame,c):
        if c.season_definition!='cross_year_winter':return self.window(frame,c.start,c.end,c.months)
        pairs=[self.year_window(frame,year,c) for year in range(int(c.start[:4]),int(c.end[:4])+1)]
        return pd.concat([p[0] for p in pairs]).drop_duplicates(['date','object_id']),sum(p[1] for p in pairs)

    def execute(self,payload):
        q=self.validate(payload);c=q.context;frame=self.table(c.object_id)
        part,expected=self.selection(frame,c);domain_start,domain_end=self.domain(c)
        month_order=[12,1,2] if c.season_definition=='cross_year_winter' else c.months
        result={'dataset_version':q.dataset_version,'result_id':signature({'query_version':2,**q.model_dump()}),'task':q.task,'context':c.model_dump(),'object_name':self.label(c.object_id),
                'unit':'μg/m³','summary':summarize(part,expected),'data':{},'provenance':{'query_version':2,'rule_version':self.dataset.manifest['rule_version'],'method':'按已有日均统计，不补零；日均由当天已有有效小时计算。','source_level':'city_archive' if c.object_id=='shanghai' else 'site_archive'}}
        if q.task=='trend':
            freq={'year':'Y','month':'M','day':'D'}[c.granularity];points=[]
            for period in pd.period_range(c.start if freq=='Y' else domain_start,c.end if freq=='Y' else domain_end,freq=freq):
                if freq=='Y' and c.season_definition=='cross_year_winter':
                    sub,n=self.year_window(frame,period.year,c);lo=f'{period.year-1}-12-01';hi=f'{period.year}-02-{calendar.monthrange(period.year,2)[1]}'
                else:
                    lo=max(domain_start,period.start_time.strftime('%Y-%m-%d'));hi=min(domain_end,period.end_time.strftime('%Y-%m-%d'))
                    sub,n=self.window(part,lo,hi,c.months)
                points.append({'period':str(period),'start':lo,'end':hi,**summarize(sub,n)})
            result['data']={'points':points}
        elif q.task=='season':
            cells=[]
            for year in range(int(c.start[:4]),int(c.end[:4])+1):
                for month in month_order:
                    actual_year=year-1 if c.season_definition=='cross_year_winter' and month==12 else year
                    lo=max(domain_start,f'{actual_year}-{month:02d}-01');hi=min(domain_end,f'{actual_year}-{month:02d}-{calendar.monthrange(actual_year,month)[1]}')
                    if lo>hi:continue
                    sub,n=self.window(frame,lo,hi,[month]);cells.append({'year':year,'month':month,'period':f'{actual_year}-{month:02d}',**summarize(sub,n)})
            result['data']={'cells':cells,'month_order':month_order}
        elif q.task in ('compare','distribution'):
            samples={};summaries={}
            for year in [c.base_year,c.target_year]:
                sub,n=self.year_window(frame,year,c);summaries[str(year)]=summarize(sub,n)
                samples[str(year)]=sub.loc[sub.status.eq('ok'),['date','pm25_ug_m3']].dropna().to_dict('records')
            rows=[]
            for month in month_order:
                pair=[]
                for year in [c.base_year,c.target_year]:
                    effective=year-1 if c.season_definition=='cross_year_winter' and month==12 else year
                    lo=f'{effective}-{month:02d}-01';hi=f'{effective}-{month:02d}-{calendar.monthrange(effective,month)[1]}'
                    sub,n=self.window(frame,lo,hi,[month]);pair.append(summarize(sub,n))
                a,b=[p[c.statistic] for p in pair]
                rows.append({'month':month,'base_period':f'{c.base_year-1 if c.season_definition=="cross_year_winter" and month==12 else c.base_year}-{month:02d}','target_period':f'{c.target_year-1 if c.season_definition=="cross_year_winter" and month==12 else c.target_year}-{month:02d}','base':pair[0],'target':pair[1],'delta':b-a if a is not None and b is not None else None})
            a,b=[summaries[str(y)][c.statistic] for y in [c.base_year,c.target_year]]
            result['data']={'rows':rows,'base':summaries[str(c.base_year)],'target':summaries[str(c.target_year)],'delta':b-a if a is not None and b is not None else None}
            if q.task=='distribution':
                curves=[]
                for year in [c.base_year,c.target_year]:
                    values=sorted(float(r['pm25_ug_m3']) for r in samples[str(year)])
                    curves.append({'label':str(year),'n':len(values),'points':([[0.,0.]]+[[v,(i+1)/len(values)] for i,v in enumerate(values)]) if values else []})
                result['data']['curves']=curves
        elif q.task=='stations':
            result['summary']=None
            result['object_name']='上海监测站'
            result['provenance']['source_level']='site_archive'
            rows=[]
            for sid in c.station_ids or sorted(self.catalog):
                table=self.table(sid)
                if c.station_mode=='compare':
                    a,na=self.year_window(table,c.base_year,c);b,nb=self.year_window(table,c.target_year,c)
                    base=summarize(a,na);target=summarize(b,nb)
                else:
                    b,nb=self.selection(table,c);base=None;target=summarize(b,nb)
                av=base[c.statistic] if base else None;bv=target[c.statistic];delta=bv-av if av is not None and bv is not None else None
                if c.direction=='up' and not (delta is not None and delta>0):continue
                if c.direction=='down' and not (delta is not None and delta<0):continue
                rows.append({'station_id':sid,'name':self.label(sid),'base':base,'target':target,'delta':delta,'coordinate':self.catalog[sid]['map_coordinate']})
            sort_key=(lambda r:(r['target'][c.statistic] is None,-(r['target'][c.statistic] or 0),r['station_id'])) if c.station_mode=='period' or c.station_sort=='target_desc' else (lambda r:(r['delta'] is None,(-1 if c.station_sort=='delta_desc' else 1)*(r['delta'] or 0),r['station_id']))
            result['data']={'rows':sorted(rows,key=sort_key)}
        elif q.task=='station_trends':
            result['summary']=None
            result['object_name']='所选监测站'
            result['provenance']['source_level']='site_archive'
            series=[]
            for sid in c.selected_station_ids[:3]:
                points=[]
                table=self.table(sid);selected,_=self.selection(table,c)
                freq={'year':'Y','month':'M','day':'D'}[c.granularity]
                for period in pd.period_range(c.start if freq=='Y' else domain_start,c.end if freq=='Y' else domain_end,freq=freq):
                    if freq=='Y' and c.season_definition=='cross_year_winter':sub,n=self.year_window(table,period.year,c)
                    else:sub,n=self.window(selected,max(domain_start,period.start_time.strftime('%Y-%m-%d')),min(domain_end,period.end_time.strftime('%Y-%m-%d')),c.months)
                    points.append({'period':str(period),**summarize(sub,n)})
                series.append({'station_id':sid,'name':self.label(sid),'points':points})
            result['data']={'series':series}
        else:
            events=[];active=[]
            good={r['date']:float(r['pm25_ug_m3']) for r in part.loc[part.status.eq('ok')].dropna(subset=['pm25_ug_m3']).to_dict('records')}
            def finish():
                if len(active)>=c.episode_min_days:events.append({'start':active[0][0],'end':active[-1][0],'days':len(active),'mean':sum(v for _,v in active)/len(active),'maximum':max(v for _,v in active)})
                active.clear()
            for day in pd.date_range(domain_start,domain_end).strftime('%Y-%m-%d'):
                if int(day[5:7]) in c.months and day in good and good[day]>=c.threshold:active.append((day,good[day]))
                else:finish()
            finish();result['data']={'episodes':events,'threshold':c.threshold,'minimum_days':c.episode_min_days,'daily':[{'date':d,'value':good.get(d)} for d in pd.date_range(domain_start,domain_end).strftime('%Y-%m-%d')]}
        return result
