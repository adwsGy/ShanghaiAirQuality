"""Research statistics, independent of the UI and of chart display resolution."""
from __future__ import annotations

from dataclasses import dataclass
import calendar
import math
from datetime import date, timedelta
import numpy as np
import pandas as pd

RULE_VERSION = 'pm25-research-1.0.0'

@dataclass(frozen=True)
class Policy:
    policy_id: str
    coverage_percent: int
    min_valid_hours: int = 20

POLICIES = {'study-75': Policy('study-75', 75), 'study-90': Policy('study-90', 90)}

def load_daily_tables(directory):
    """Normalize public table keys only at the calculation boundary."""
    from pathlib import Path
    directory=Path(directory)
    city=pd.read_csv(directory/'city_daily.csv',dtype={'date':str,'city_id':str}).rename(columns={'city_id':'object_id'})
    site=pd.read_csv(directory/'site_daily.csv',dtype={'date':str,'station_id':str}).rename(columns={'station_id':'object_id'})
    return city,site

def daily_value(values, min_hours=20):
    """Caller resolves duplicate hours first. Real zero is a valid observation."""
    good = [float(x) for x in values if x is not None and math.isfinite(float(x)) and float(x) >= 0]
    return (math.fsum(good)/len(good) if len(good) >= min_hours else None, len(good))

def _base_statistics(values):
    a=np.asarray(list(values), dtype=float)
    a=a[np.isfinite(a)]
    if not len(a):
        return {k:None for k in ('mean','median','p90','minimum','maximum')}
    return {'mean':float(a.mean()),'median':float(np.median(a)),
            'p90':float(np.quantile(a,.9,method='linear')),
            'minimum':float(a.min()),'maximum':float(a.max())}

def period_statistics(days: pd.DataFrame, start: str, end: str, policy_id='study-75', period_kind='range'):
    """Return sample quality and statistics for ONE source/object, inclusive dates.

    A period's missing dates remain in the denominator. Annual/range validity
    also checks all included calendar months. Partial years never become annuals.
    """
    policy=POLICIES[policy_id]
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    if a>b:raise ValueError('start must not follow end')
    if not days.empty:
        if days['object_id'].nunique()!=1 or days['source_level'].nunique()!=1:
            raise ValueError('Never mix source levels or observation objects')
        if days['date'].duplicated().any():raise ValueError('duplicate research days')
    subset=days.loc[(days['date']>=start)&(days['date']<=end)]
    valid=subset.loc[subset['status'].eq('ok'),'pm25_ug_m3'].dropna()
    expected=(b-a).days+1
    n=len(valid)
    coverage=n/expected
    failed=[]
    if period_kind in ('year','range'):
        cursor=date(a.year,a.month,1)
        while cursor<=b:
            month_end=date(cursor.year,cursor.month,calendar.monthrange(cursor.year,cursor.month)[1])
            lo,hi=max(a,cursor),min(b,month_end)
            ndays=(hi-lo).days+1
            nvalid=int(((subset['date']>=lo.isoformat())&(subset['date']<=hi.isoformat())&subset['status'].eq('ok')).sum())
            if nvalid*100<ndays*policy.coverage_percent:failed.append(cursor.strftime('%Y-%m'))
            cursor=(month_end+timedelta(days=1))
    partial=period_kind=='year' and (a!=date(a.year,1,1) or b!=date(a.year,12,31) or a.year!=b.year)
    reasons=[]
    if partial:status='partial_period';reasons.append('incomplete_calendar_year')
    elif n==0:
        status='source_unavailable' if not subset.empty and subset['status'].eq('source_unavailable').all() else 'no_observations'
        reasons.append('no_valid_research_days')
    elif n*100<expected*policy.coverage_percent or failed:
        status='insufficient_coverage'
        if n*100<expected*policy.coverage_percent:reasons.append('period_coverage_below_threshold')
        if failed:reasons.append('monthly_coverage_gate_failed')
    else:status='ok'
    raw=_base_statistics(valid)
    result={'status':status,'reason_codes':';'.join(reasons),'valid_days':n,'expected_days':expected,
            'coverage':coverage,'required_days':math.ceil(expected*policy.coverage_percent/100),
            'failed_months':';'.join(failed),**raw}
    # Raw distribution summaries are retained only as EDA diagnostics.
    for k in ('mean','p90'):result['observed_'+k]=result[k];result[k]=result[k] if status=='ok' else None
    return result

def aggregate_daily(days: pd.DataFrame):
    records=[]
    for (source,object_id),group in days.groupby(['source_level','object_id'],sort=True):
        first,last=group['date'].min(),group['date'].max()
        periods=[]
        for ym,part in group.groupby(group['date'].str[:7],sort=True):
            y,m=map(int,ym.split('-'))
            periods.append(('month',ym,f'{ym}-01',f'{ym}-{calendar.monthrange(y,m)[1]:02d}'))
        for y in range(int(first[:4]),int(last[:4])+1):periods.append(('year',str(y),f'{y}-01-01',f'{y}-12-31'))
        for pid in POLICIES:
            for kind,label,start,end in periods:
                records.append({'source_level':source,'object_id':object_id,'period_kind':kind,'period':label,
                                'start':start,'end':end,'policy_id':pid,
                                'source_locator':f'{source}/{object_id}/{start}/{end}',
                                **period_statistics(group,start,end,pid,kind)})
    return pd.DataFrame(records)

def comparison_rows(coverage: pd.DataFrame, metadata: pd.DataFrame, base_year=2021,target_year=2025,
                    statistic='mean',policy_id='study-75'):
    if base_year==target_year:raise ValueError('Use two distinct years')
    if statistic not in ('mean','p90'):raise ValueError('Unknown statistic')
    c=coverage.loc[coverage['source_level'].eq('site_archive')&coverage['period_kind'].eq('year')&coverage['policy_id'].eq(policy_id)]
    records=[]
    for station in metadata.to_dict('records'):
        sid=station['station_id'];a=c.loc[c['object_id'].eq(sid)&c['period'].eq(str(base_year))];b=c.loc[c['object_id'].eq(sid)&c['period'].eq(str(target_year))]
        a=a.iloc[0] if len(a) else None;b=b.iloc[0] if len(b) else None
        eligible=a is not None and b is not None and a['status']=='ok' and b['status']=='ok'
        av=float(a[statistic]) if a is not None and a['status']=='ok' else None
        bv=float(b[statistic]) if b is not None and b['status']=='ok' else None
        delta=bv-av if eligible else None
        records.append({'station_id':sid,'name':station['name'],'base_year':base_year,'target_year':target_year,
                        'statistic':statistic,'policy_id':policy_id,'base_value':av,'target_value':bv,
                        'base_status':a['status'] if a is not None else 'no_observations',
                        'target_status':b['status'] if b is not None else 'no_observations',
                        'eligible':eligible,'absolute_change':delta,
                        'relative_change_pct':delta/av*100 if eligible and av!=0 else None,
                        'reason_codes':('' if eligible else 'one_or_both_years_ineligible')+('zero_baseline' if eligible and av==0 else ''),
                        'base_valid_days':int(a['valid_days']) if a is not None else 0,
                        'target_valid_days':int(b['valid_days']) if b is not None else 0})
    return pd.DataFrame(records)
