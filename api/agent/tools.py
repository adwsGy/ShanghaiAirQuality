"""Registered, bounded analysis tools backed by the same statistical services as the UI."""
import calendar
import json
import re
from pydantic import ValidationError
from api.service import QueryError, invalid
from api.workspace import AnalysisContext, signature
from api.agent.schemas import AnalysisPlan, ToolResult

TOOL_VERSION = 'analysis-tools-3.1.0'
COMMON = {'object_id','start','end','statistic','months','season_definition'}
COMPARISON = {'object_id','base_year','target_year','statistic','months','season_definition','granularity'}
TOOL_FIELDS = {
    'compare_periods': COMPARISON,
    'compare_distributions': COMPARISON,
    'query_trend': COMMON | {'granularity'},
    'seasonal_matrix': COMMON,
    'station_analysis': COMMON | {'station_ids','selected_station_ids','base_year','target_year','direction','station_mode','station_sort','granularity','track_top'},
    'find_episodes': COMMON | {'threshold','episode_min_days'},
    'inspect_month': {'object_id','month','day','display'},
}
TASK = {'compare_periods':'compare','compare_distributions':'distribution','query_trend':'trend',
        'seasonal_matrix':'season','station_analysis':'stations','find_episodes':'episodes','inspect_month':'observations'}


def model_tools(web_search_enabled=True):
    fields = AnalysisContext.model_json_schema()['properties']
    descriptions = {
        'compare_periods':'两个年份同历月的均值/P90及差值。省略的条件继承当前比较。',
        'compare_distributions':'比较两个年份所选月份的日均浓度累计分布、均值与P90。',
        'query_trend':'上海全市或一个监测站在指定日期范围内的年/月/日趋势。',
        'seasonal_matrix':'按年×月展示浓度矩阵，比较月份与年份差异，支持月份筛选。',
        'station_analysis':'比较监测站。station_mode=period表示一个指定时段，compare表示两个年份。direction筛选升降；track_top=1至3按真实结果选择并追踪站点；granularity控制追踪尺度。',
        'find_episodes':'找日均达到threshold且连续至少episode_min_days天的高值过程；缺测及未选择月份中断连续性。',
        'inspect_month':'查看选中月份的日均和小时，回答最高日或最高小时。month格式YYYY-MM，day可选YYYY-MM-DD；“这个月”继承当前选中月，站点继承明细对象。',
    }
    tools=[]
    for name, allowed in TOOL_FIELDS.items():
        properties={key:fields[key] for key in sorted(allowed) if key in fields}
        if name=='station_analysis':properties['track_top']={'type':'integer','minimum':0,'maximum':3}
        if name=='inspect_month':properties.update(display={'type':'string','enum':['daily','hourly']},month={'type':'string','pattern':'^20[0-9]{2}-(0[1-9]|1[0-2])$'},day={'anyOf':[{'type':'string','pattern':'^20[0-9]{2}-[0-9]{2}-[0-9]{2}$'},{'type':'null'}]})
        properties['update_view']={'type':'boolean','default':False,'description':'仅用户要求显示、切换、追踪图形时为true；只问数值、解释和原因时为false，查询照常执行。'}
        tools.append({'type':'function','function':{'name':name,'description':descriptions[name],
            'parameters':{'type':'object','additionalProperties':False,'properties':properties}}})
    tools.append({'type':'function','function':{'name':'request_clarification',
        'description':'条件不清或工具不支持时澄清。仅说冬天且未指定自然年/跨年时，kind=winter，提供resume_tool和resume_arguments；用户选择定义后程序继续原计划，无需再请求模型。其他情况kind=general。',
        'parameters':{'type':'object','additionalProperties':False,'properties':{
            'question':{'type':'string','maxLength':240},'options':{'type':'array','items':{'type':'string'},'maxItems':3},
            'kind':{'type':'string','enum':['general','winter']},
            'resume_tool':{'type':'string','enum':list(TOOL_FIELDS)},
            'resume_arguments':{'type':'object','additionalProperties':False,'properties':{**fields,'track_top':{'type':'integer','minimum':0,'maximum':3}}},
        },'required':['question','options']}}})
    if web_search_enabled:
        tools.append({'type':'function','function':{'name':'search_web','description':'检索同地区、同年份、同日期的官方污染通报、气象分析和监测专家说明，为原因回答提供可引用的解释。项目浓度数值和排名仍查询本地工具。',
            'parameters':{'type':'object','additionalProperties':False,'properties':{'query':{'type':'string','minLength':1,'maxLength':128},'count':{'type':'integer','minimum':1,'maximum':5}},'required':['query']}}})
    return tools


def parse_plans(message):
    calls=message.get('tool_calls')
    if not calls:
        if isinstance(message.get('content'),str) and message['content'].strip():return []
        invalid('模型没有返回回答或查询计划，本次未改变图表。')
    if not isinstance(calls,list) or not 1<=len(calls)<=4:invalid('一次问题的查询计划无效，本次未改变图表。')
    try:
        plans=[]
        for call in calls:
            args=json.loads(call['function']['arguments'])
            if not isinstance(args,dict):raise ValueError('Arguments must be an object')
            update=args.pop('update_view',False)
            plans.append(AnalysisPlan.model_validate({'tool':call['function']['name'],'tool_call_id':call['id'],'arguments':args,'update_view':update}))
        if len({p.tool_call_id for p in plans})!=len(plans):raise ValueError('Duplicate call id')
        if sum(p.tool=='search_web' for p in plans)>1:raise ValueError('Duplicate search')
        if len(plans)>1 and any(p.tool=='request_clarification' for p in plans):raise ValueError('Clarification must stand alone')
        if sum(p.update_view for p in plans)>1:raise ValueError('Only one chart target')
        return plans
    except (ValidationError,ValueError,KeyError,TypeError) as error:
        raise QueryError(422,'INVALID_PLAN','模型返回的工具计划无效，本次未改变图表。') from error


def parse_plan(message):
    plans=parse_plans(message)
    if len(plans)!=1:invalid('此入口需要一个工具计划。')
    return plans[0]


def normalized_context(dataset,view,tool,arguments):
    if tool not in TOOL_FIELDS or set(arguments)-TOOL_FIELDS[tool]:invalid('工具包含不支持的参数。')
    old=view['context'];args=dict(arguments)
    if tool=='station_analysis':
        count=args.get('track_top',0)
        if not isinstance(count,int) or isinstance(count,bool) or not 0<=count<=3:invalid('追踪站点数量需要在 0—3 之间。')
        if count and 'station_sort' not in args:args['station_sort']='delta_asc' if args.get('direction',old['direction'])=='down' else 'delta_desc'
    if tool=='inspect_month':
        month=args.get('month') or view.get('month')
        if not month and old['start'][:7]==old['end'][:7]:month=old['start'][:7]
        if not month:invalid('请先选择或指定要查看的月份。')
        obj=args.get('object_id') or view.get('detailObject') or old['object_id']
        # The hourly service validates date availability and object identity before any result is published.
        observations=dataset.observation_service.monthly({'dataset_version':dataset.version,'month':month,'station_id':obj})
        if args.get('day') and args['day'] not in {d['date'] for d in observations['daily']}:invalid('日期不在所选月份内。')
        args={'object_id':obj,'start':month+'-01','end':month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:]))[1]),'granularity':'day','months':[int(month[5:])],'season_definition':None}
    else:
        args.pop('track_top',None)
    merged={**old,**args}
    # A replacement time span starts a new calendar window. Inherit a month/season
    # filter only when no new range was supplied, or the caller explicitly retains it.
    if ('start' in args or 'end' in args) and 'months' not in args and 'season_definition' not in args:
        merged.update(months=list(range(1,13)),season_definition=None)
    if 'months' in args and 'season_definition' not in args and sorted(set(args['months']))!=[1,2,12]:merged['season_definition']=None
    if tool in ('compare_periods','compare_distributions') or tool=='station_analysis' and merged['station_mode']=='compare':
        merged['start']=f'{min(merged["base_year"],merged["target_year"])}-01-01';merged['end']=f'{max(merged["base_year"],merged["target_year"])}-12-31'
    if tool=='station_analysis' and merged['station_mode']=='period':merged['direction']='all'
    try:context=AnalysisContext.model_validate(merged).model_dump()
    except ValidationError as error:raise QueryError(422,'INVALID_PLAN',error.errors()[0]['msg']) from error
    if tool!='inspect_month':dataset.workspace.validate({'dataset_version':dataset.version,'task':TASK[tool],'context':context})
    return context


def explicit_conditions(question,tool,arguments):
    """Honor unambiguous metric words in the current request over stale model echoes.

    This corrects only an explicit single metric; requests mentioning both mean
    and P90 retain the typed tool plan. Raw provider arguments remain in the ledger.
    """
    args=dict(arguments)
    if tool in TOOL_FIELDS and tool!='inspect_month':
        mean=bool(re.search(r'均值|月均|年均|平均(?:值|浓度)|\bmean\b|\baverage\b',question,re.I))
        p90=bool(re.search(r'P\s*90|第\s*90\s*百分位|90%\s*分位',question,re.I))
        if mean!=p90:args['statistic']='mean' if mean else 'p90'
    return args


def comparison_context(dataset,previous,arguments):
    return normalized_context(dataset,{'context':previous},'compare_periods',arguments)


def checked(result):return ToolResult.model_validate(result).model_dump()


def execute_comparison(dataset,context):
    return checked(dataset.workspace.execute({'dataset_version':dataset.version,'task':'compare','context':context}))


def execute_tool(dataset,view,tool,arguments,context):
    if tool=='inspect_month':
        month=context['start'][:7]
        observations=dataset.observation_service.monthly({'dataset_version':dataset.version,'month':month,'station_id':context['object_id']})
        chosen_day=arguments.get('day',view.get('detailDay') if month==view.get('month') else None)
        if chosen_day and chosen_day not in {d['date'] for d in observations['daily']}:invalid('日期不在所选月份内。')
        observations={**observations,'selected_day':chosen_day}
        if chosen_day:
            observations={**observations,'points':[p for p in observations['points'] if p['date']==chosen_day]}
        result=dataset.workspace.execute({'dataset_version':dataset.version,'task':'trend','context':context})
        result.update(task='observations',result_id=signature({'task':'observations','daily_ref':result['result_id'],'month':month,'day':chosen_day}))
        result['data']['observations']=observations
        return [checked(result)],context
    result=dataset.workspace.execute({'dataset_version':dataset.version,'task':TASK[tool],'context':context})
    secondary=[]
    if tool=='station_analysis':
        count=arguments.get('track_top',0)
        if not isinstance(count,int) or isinstance(count,bool) or not 0<=count<=3:invalid('追踪站点数量需要在 0—3 之间。')
        if count:
            rows=result['data']['rows'];stat=context['statistic']
            candidates=[r for r in rows if (r['delta'] if context['station_mode']=='compare' else r['target'][stat]) is not None]
            key=(lambda r:r['delta']) if context['station_mode']=='compare' else (lambda r:r['target'][stat])
            candidates=sorted(candidates,key=key,reverse=context['direction']!='down')
            context={**context,'selected_station_ids':[r['station_id'] for r in candidates[:count]]}
            result=dataset.workspace.execute({'dataset_version':dataset.version,'task':'stations','context':context})
        if context['selected_station_ids']:
            secondary=[checked(dataset.workspace.execute({'dataset_version':dataset.version,'task':'station_trends','context':context}))]
    return [checked(result),*secondary],context


def clarification_payload(dataset,view,plan):
    args=plan['arguments']
    if set(args)-{'question','options','kind','resume_tool','resume_arguments'} or not isinstance(args.get('question'),str) or not 1<=len(args['question'])<=240:invalid('澄清问题格式无效。')
    options=args.get('options',[])
    if not isinstance(options,list) or len(options)>3 or any(not isinstance(s,str) or len(s)>120 for s in options):invalid('澄清选项格式无效。')
    if args.get('kind','general') not in ('general','winter'):invalid('未知澄清类型。')
    if args.get('kind')=='winter':
        tool=args.get('resume_tool');pending=args.get('resume_arguments',{})
        if tool not in TOOL_FIELDS or tool=='inspect_month' or not isinstance(pending,dict):invalid('冬季澄清缺少可恢复计划。')
        pending=pending_arguments(view,tool,pending)
        normalized_context(dataset,view,tool,{**pending,'months':[1,2,12],'season_definition':'calendar_winter'})
        return {'kind':'winter','question':args['question'],'options':['自然年冬季：同年1、2、12月','跨年冬季：上年12月至当年2月'],'choices':['calendar_winter','cross_year_winter']}
    return {'kind':'general','question':args['question'],'options':options}


def pending_arguments(view,tool,arguments):
    # The clarification contract accepts context fields for different resume tools.
    # Inert echoes are harmless; a changed unsupported condition is never silently dropped.
    allowed=TOOL_FIELDS[tool];known=set(AnalysisContext.model_fields)|{'track_top'}
    if set(arguments)-known:invalid('恢复计划包含未知参数。')
    for key in set(arguments)-allowed:
        if key not in view['context'] or arguments[key]!=view['context'][key]:invalid('恢复工具不支持修改该条件。')
    return {key:value for key,value in arguments.items() if key in allowed}
