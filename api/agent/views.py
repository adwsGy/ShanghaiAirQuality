"""Trusted view mapping and numerical observations; no model-generated chart code."""
from api.agent.schemas import Answer, Fact, ViewSpec
from statistics import mean, median


def daily_sensitivity(observations):
    valid=[d for d in observations['daily'] if d['daily_mean'] is not None]
    if not valid:return None
    peak=max(valid,key=lambda d:d['daily_mean'])
    remaining=list(valid);remaining.remove(peak)
    return {'n':len(valid),'mean':mean(d['daily_mean'] for d in valid),
            'median':median(d['daily_mean'] for d in valid),'maximum_date':peak['date'],
            'maximum':peak['daily_mean'],'without_maximum_n':len(remaining),
            'without_maximum_mean':mean(d['daily_mean'] for d in remaining) if remaining else None,
            'method':'仅排除一个最高日的敏感性计算，不是同比贡献或成因分解。'}


def fixed(value):
    return '无观测' if value is None else f'{value:.1f}'


def build_comparison(result):
    c = result['context']
    metric = '均值' if c['statistic'] == 'mean' else 'P90'
    base, target = c['base_year'], c['target_year']
    result_id = result['result_id']
    facts = []
    for row in result['data']['rows']:
        m = row['month']
        a, b = row['base'], row['target']
        delta = row['delta']
        change = '差值无法计算' if delta is None else f'差值 {delta:+.1f} μg/m³'
        facts.append(Fact(id=f'M{m:02d}', month=m, selection_kind='month', result_id=result_id,
                          date=(row.get('target_period') or f'{target}-{m:02d}')+'-01', text=f'{row.get("base_period") or str(base)+"-"+str(m).zfill(2)} 的{metric} {fixed(a[c["statistic"]])}，{row.get("target_period") or str(target)+"-"+str(m).zfill(2)} 的{metric} {fixed(b[c["statistic"]])} μg/m³；{change}。两期分别有 {a["n"]}、{b["n"]} 天观测。').model_dump())
    a, b = result['data']['base'], result['data']['target']
    facts.append(Fact(id='PERIOD', result_id=result_id,
                      text=f'所选月份合并后：{base} 年{metric} {fixed(a[c["statistic"]])}，{target} 年{metric} {fixed(b[c["statistic"]])} μg/m³，分别 {a["n"]}、{b["n"]} 天观测；使用已有日均统计，缺测不补零。').model_dump())
    higher = [r for r in result['data']['rows'] if r['delta'] is not None and r['delta'] > 0]
    lower = [r for r in result['data']['rows'] if r['delta'] is not None and r['delta'] < 0]
    no_pair = [r for r in result['data']['rows'] if r['delta'] is None]
    equal = [r for r in result['data']['rows'] if r['delta'] == 0]
    facts.append(Fact(id='COUNTS',result_id=result_id,text=f'{target} 相比 {base}，所选月份的{metric}：{len(higher)} 个月上升，{len(lower)} 个月下降，{len(equal)} 个月相等，{len(no_pair)} 个月无法配对；升降数量由逐月差值计数。').model_dump())
    text = f'{result["object_name"]}，{target} 相比 {base}：'
    text += '、'.join(f'{r["month"]}月' for r in higher) + f'的{metric}更高。' if higher else f'所选月份没有可比较的{metric}升高。'
    if lower:
        text += '、'.join(f'{r["month"]}月' for r in lower) + '更低。'
    if higher:
        peak = max(higher, key=lambda row: row['delta'])
        text += f'升幅最大为 {peak["month"]}月（{peak["delta"]:+.1f} μg/m³）。'
    if no_pair:
        text += '、'.join(f'{r["month"]}月' for r in no_pair) + '缺少一期观测，不能计算差值。'
    text += '下方事实可定位月份；均值及 P90 均由实际日均记录计算。'
    answer = Answer(text=text, fact_ids=[f['id'] for f in facts]).model_dump()
    view = ViewSpec(task='compare', data_ref=result_id, title=f'{result["object_name"]} · {target} 与 {base} 同历月比较').model_dump()
    return {'view_spec': view, 'facts': facts, 'answer': answer}


def season_label(context):
    return '跨年冬季（上年12月—当年2月，按结束年命名）' if context['season_definition']=='cross_year_winter' else '自然年冬季（同年1、2、12月）' if context['season_definition']=='calendar_winter' else '、'.join(f'{m}月' for m in context['months']) if len(context['months'])<12 else '全年月份'


def presentation(results, arguments):
    result=results[0];c=result['context'];task=result['task'];data=result['data'];rid=result['result_id']
    metric='均值' if c['statistic']=='mean' else 'P90'
    facts=[]
    def fact(identifier,text,date=None,station=None,selection='month'):
        facts.append(Fact(id=identifier,text=text,result_id=rid,date=date,month=int(date[5:7]) if date and len(date)>=7 else None,station_id=station,selection_kind=selection if date else 'none').model_dump())
    selected_month=None;detail_day=None;detail_tab='daily'
    if task=='compare':
        built=build_comparison(result);facts=built['facts'];text=built['answer']['text'];title=built['view_spec']['title']
    elif task=='distribution':
        a,b=data['base'],data['target'];dm=b['mean']-a['mean'] if a['mean'] is not None and b['mean'] is not None else None;dp=b['p90']-a['p90'] if a['p90'] is not None and b['p90'] is not None else None
        for key,year,s in [('BASE',c['base_year'],a),('TARGET',c['target_year'],b)]:fact(key,f'{year}：日均样本 {s["n"]} 天，均值 {fixed(s["mean"])}，P90 {fixed(s["p90"])} μg/m³。')
        fact('CHANGE',f'对比年减基准年：均值变化 {fixed(dm)}，P90 变化 {fixed(dp)} μg/m³。')
        text=f'{c["target_year"]} 相对 {c["base_year"]}，均值变化 {fixed(dm)}，P90 变化 {fixed(dp)} μg/m³。累计曲线按各期样本数归一化，可比较浓度分布的位置和高值尾部。'
        title=f'{result["object_name"]} · 日均分布对照'
    elif task in ('trend','season'):
        points=data.get('points',data.get('cells',[]));stat='mean' if task=='trend' and c['granularity']=='day' else c['statistic'];name='日均浓度' if task=='trend' and c['granularity']=='day' else metric
        observed=[p for p in points if p[stat] is not None];summary=result['summary']
        fact('SAMPLE',f'所选范围有 {summary["n"]} 天日均观测，均值 {fixed(summary["mean"])}，P90 {fixed(summary["p90"])} μg/m³。')
        if observed:
            chosen={observed[0]['period']:observed[0],observed[-1]['period']:observed[-1],max(observed,key=lambda p:p[stat])['period']:max(observed,key=lambda p:p[stat])}
            for i,p in enumerate(chosen.values()):fact(f'P{i+1}',f'{p["period"]}：{name} {fixed(p[stat])} μg/m³，{p["n"]} 天观测。',p['period'][:10] if len(p['period'])==10 else p['period']+'-01' if len(p['period'])==7 else None,selection='day' if len(p['period'])==10 else 'month')
            peak=max(observed,key=lambda p:p[stat]);text=f'在所选范围内，{peak["period"]} 的{name}最高，为 {fixed(peak[stat])} μg/m³。当前有 {summary["n"]} 天日均样本。'
        else:text='当前选择没有观测，保留空值；可以调整对象或日期继续查看。'
        title=f'{result["object_name"]} · '+('年月矩阵' if task=='season' else '浓度变化')
    elif task=='stations':
        rows=data['rows'];period=c['station_mode']=='period';observed=[r for r in rows if r['target'][c['statistic']] is not None]
        for row in rows:
            label=f'{c["start"]}—{c["end"]}' if period else str(c['target_year'])
            description=f'{row["name"]}：{label} {metric} {fixed(row["target"][c["statistic"]])} μg/m³，{row["target"]["n"]} 天观测。'
            if not period:description+=f'基准年 {fixed(row["base"][c["statistic"]])} μg/m³，{row["base"]["n"]} 天；差值 {fixed(row["delta"])} μg/m³。'
            month=12 if c['season_definition']=='cross_year_winter' else c['months'][0]
            date=c['start'] if period else f'{c["target_year"]-1 if c["season_definition"]=="cross_year_winter" and month==12 else c["target_year"]}-{month:02d}-01'
            fact(row['station_id'],description,date,row['station_id'])
        text=f'当前条件下有 {len(observed)} 个站点在对比时段有观测。' if not period else f'当前时段有 {len(observed)} 个站点有观测。'
        if observed:
            peak=max(observed,key=lambda r:r['target'][c['statistic']]);text+=f'{peak["name"]}的观测{metric}最高，为 {fixed(peak["target"][c["statistic"]])} μg/m³。'
        if c['selected_station_ids']:text+='已追踪 '+ '、'.join(r['name'] for r in rows if r['station_id'] in c['selected_station_ids'])+'，下方曲线使用相同对象和统计量。'
        title='上海监测站 · '+('指定时段浓度' if period else '两期差异')
    elif task=='episodes':
        events=data['episodes'];threshold=data['threshold'];minimum=data['minimum_days']
        text=f'按日均 ≥ {threshold:g} μg/m³、连续至少 {minimum} 日，找到 {len(events)} 个高值过程。缺测和未选择月份会中断连续性。'
        fact('DEFINITION',text)
        for i,e in enumerate(sorted(events,key=lambda e:(-e['maximum'],-e['days'],e['start']))[:30]):fact(f'E{i+1}',f'{e["start"]}—{e["end"]}，连续 {e["days"]} 日，过程日均平均 {e["mean"]:.1f}、最高日均 {e["maximum"]:.1f} μg/m³。',e['start'],selection='day')
        title=f'{result["object_name"]} · 连续高值过程'
    else:
        observations=data['observations'];points=observations['points'];valid=[p for p in points if p['value'] is not None];selected_month=observations['month'];detail_day=observations.get('selected_day');detail_tab='hourly' if detail_day or arguments.get('display')=='hourly' else 'daily'
        text=f'{result["object_name"]}，{detail_day or selected_month} 有 {len(valid)}/{len(points)} 小时观测。'
        if valid:
            peak=max(valid,key=lambda p:p['value']);text+=f'最高小时为 {peak["date"]} {peak["hour"]:02d}:00，{peak["value"]:.1f} μg/m³。';fact('HOUR',text,peak['date'],c['object_id'] if c['object_id']!='shanghai' else None,selection='day')
        daily=[d for d in observations['daily'] if d['daily_mean'] is not None and (not detail_day or d['date']==detail_day)]
        if daily:
            peak=max(daily,key=lambda d:d['daily_mean']);fact('DAY',f'{peak["date"]} 日均 {peak["daily_mean"]:.1f} μg/m³，使用当天 {peak["valid_hours"]} 个小时观测。',peak['date'],c['object_id'] if c['object_id']!='shanghai' else None,selection='day')
        sensitivity=daily_sensitivity(observations)
        if not detail_day and sensitivity and sensitivity['without_maximum_mean'] is not None:
            fact('DAILY_DISTRIBUTION',f'{selected_month} 有 {sensitivity["n"]} 个日均，中位数 {sensitivity["median"]:.1f} μg/m³；'
                 f'仅移除最高日 {sensitivity["maximum_date"]} 后，其余 {sensitivity["without_maximum_n"]} 天均值为 {sensitivity["without_maximum_mean"]:.1f} μg/m³。',selected_month+'-01')
        if not facts:fact('EMPTY','当前选择没有小时观测，保留空值。')
        title=f'{result["object_name"]} · {detail_day or selected_month} 观测记录'
    text+=' 分析范围：'+season_label(c)+'。' if c['season_definition'] else ''
    view_task='trend' if task=='observations' else task
    view={'task':view_task,'context':c,'month':selected_month,'detailObject':c['object_id'] if selected_month else None,'detailDay':detail_day,'detailTab':detail_tab}
    return {'view_spec':ViewSpec(task=view_task,data_ref=rid,title=title,selected_month=selected_month,secondary_refs=[r['result_id'] for r in results[1:]]).model_dump(),
            'facts':facts,'answer':Answer(text=text,fact_ids=[f['id'] for f in facts]).model_dump(),'view':view}


def layout(results,arguments):
    result=results[0];c=result['context'];task=result['task']
    names={'trend':'浓度变化','compare':f'{c["target_year"]} 与 {c["base_year"]} 同历月比较','distribution':'日均分布对照','season':'年月矩阵','stations':'指定时段浓度' if c['station_mode']=='period' else '两期差异','episodes':'连续高值过程','observations':'观测记录'}
    month=result['data']['observations']['month'] if task=='observations' else None
    day=result['data']['observations'].get('selected_day') if task=='observations' else None
    tab='hourly' if day or arguments.get('display')=='hourly' else 'daily'
    view_task='trend' if task=='observations' else task
    return {'view':{'task':view_task,'context':c,'month':month,'detailObject':c['object_id'] if month else None,'detailDay':day,'detailTab':tab},
            'view_spec':ViewSpec(task=view_task,data_ref=result['result_id'],title=result['object_name']+' · '+names[task],selected_month=month,secondary_refs=[r['result_id'] for r in results[1:]]).model_dump()}


def fallback_presentation(results):
    result=results[0]
    text='说明暂未完整生成，已保留真实图形和数据；可使用数据表与导出继续核查。'
    summary=result['summary']
    detail=f'当前查询有 {summary["n"]} 天日均观测。' if summary else f'当前查询返回 {len(result["data"].get("rows",[]))} 个站点。'
    facts=[Fact(id='RESULT',text=detail,result_id=result['result_id']).model_dump()]
    return {'facts':facts,'answer':Answer(text=text,fact_ids=['RESULT'],source='computed_fallback').model_dump()}


def answer_evidence(results):
    """Send exact aggregates and bounded extremes, with every omission explicit.

    The stored tool results remain complete. A decade of hourly/daily values or
    full ECDF coordinates is not needed in a language-model prompt.
    """
    def bounded(rows, key, maximum=36):
        if len(rows)<=maximum:return {'total':len(rows),'rows':rows,'omitted':0}
        valid=[r for r in rows if r.get(key) is not None]
        chosen=rows[:6]+rows[-6:]+sorted(valid,key=lambda r:r[key])[:12]+sorted(valid,key=lambda r:r[key],reverse=True)[:12]
        unique=list({json_key(r):r for r in chosen}.values())
        return {'total':len(rows),'rows':unique,'omitted':len(rows)-len(unique),'selection':'首尾各6项及最低/最高各12项；未提供完整序列，不能据此计算完整序列频次。'}
    def json_key(row):
        return str(row.get('period') or row.get('date'))+str(row.get('hour',''))
    evidence=[]
    for result in results:
        task=result['task'];data=result['data'];c=result['context']
        compact={k:v for k,v in data.items() if k not in ('curves','points','cells','daily','observations','series')}
        if 'curves' in data:compact['curve_coordinates_omitted']=True
        if task=='compare':
            compact['change_counts']={key:sum(test(row['delta']) for row in data['rows']) for key,test in {
                'higher':lambda d:d is not None and d>0,'lower':lambda d:d is not None and d<0,
                'equal':lambda d:d==0,'unpaired':lambda d:d is None}.items()}
        for field in ('points','cells'):
            if field in data:compact[field]=bounded(data[field],c['statistic'],maximum=144)
        if 'daily' in data:compact['daily']=bounded(data['daily'],'value')
        if 'series' in data:compact['series']=[{**s,'points':bounded(s['points'],c['statistic'],maximum=144)} for s in data['series']]
        if 'observations' in data:
            obs=data['observations']
            compact['observations']={k:v for k,v in obs.items() if k not in ('points','daily')}
            compact['observations']['daily']=bounded(obs['daily'],'daily_mean')
            compact['observations']['hours']=bounded(obs['points'],'value')
            compact['observations']['daily_summary']=daily_sensitivity(obs)
        evidence.append({k:result[k] for k in ('result_id','task','context','object_name','summary') if k in result}|{'data':compact})
    return evidence
