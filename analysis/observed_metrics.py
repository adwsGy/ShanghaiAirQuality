"""Statistics from every available observed day, with no coverage gates."""
from datetime import date
import calendar,math
import pandas as pd
from analysis.metrics import _base_statistics,comparison_rows

RULE_VERSION='pm25-observed-days-1.0.0'
POLICY_ID='observed-only'

def daily_value(values):
    good=[float(v) for v in values if v is not None and math.isfinite(float(v)) and float(v)>=0]
    return (math.fsum(good)/len(good) if good else None,len(good))

def period_statistics(days,start,end,policy_id=POLICY_ID,period_kind='range'):
    if policy_id!=POLICY_ID:raise ValueError('Use the available-observation policy')
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    if a>b:raise ValueError('start must not follow end')
    if not days.empty:
        if days.object_id.nunique()!=1 or days.source_level.nunique()!=1:raise ValueError('Never mix sources or objects')
        if days.date.duplicated().any():raise ValueError('Duplicate observed days')
    subset=days.loc[days.date.between(start,end)]
    values=pd.to_numeric(subset.loc[subset.status.eq('ok'),'pm25_ug_m3'],errors='coerce')
    values=values.loc[values.map(lambda v:math.isfinite(v) and v>=0)]
    n=len(values);expected=(b-a).days+1
    status='ok' if n else 'source_unavailable' if not subset.empty and subset.status.eq('source_unavailable').all() else 'no_observations'
    reasons=[] if n else ['no_observed_days']
    if period_kind=='year' and (a!=date(a.year,1,1) or b!=date(a.year,12,31) or a.year!=b.year):reasons.append('partial_calendar_year')
    stats=_base_statistics(values)
    return {'status':status,'reason_codes':';'.join(reasons),'valid_days':n,'expected_days':expected,'coverage':n/expected,
            'required_days':1,'failed_months':'',**stats,'observed_mean':stats['mean'],'observed_p90':stats['p90']}

def aggregate_daily(days):
    rows=[]
    for (source,object_id),group in days.groupby(['source_level','object_id'],sort=True):
        periods=[]
        for month in sorted(group.date.str[:7].unique()):
            year,m=map(int,month.split('-'));periods.append(('month',month,month+'-01',f'{month}-{calendar.monthrange(year,m)[1]:02d}'))
        for year in range(int(group.date.min()[:4]),int(group.date.max()[:4])+1):periods.append(('year',str(year),f'{year}-01-01',f'{year}-12-31'))
        for kind,label,start,end in periods:
            rows.append({'source_level':source,'object_id':object_id,'period_kind':kind,'period':label,'start':start,'end':end,
                         'policy_id':POLICY_ID,'source_locator':f'{source}/{object_id}/{start}/{end}',**period_statistics(group,start,end,POLICY_ID,kind)})
    return pd.DataFrame(rows)
