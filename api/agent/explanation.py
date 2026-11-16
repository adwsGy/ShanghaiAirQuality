"""Ensure scoped cause questions obtain observations and external explanations."""
import json
import re


def explanation_question(question):
    reason = re.search(r'为什么|为何|为啥|原因|成因|解释|\bwhy\b|\bcause', question, re.I)
    phenomenon = re.search(r'高|低|升|降|回升|反弹|污染|变化|异常|high|low|rise|fall|pollut', question, re.I)
    scope = re.search(r'20\d{2}|当前|这个月|这一天|这次|该月|当月|所选|current|selected', question, re.I)
    return bool(reason and phenomenon and scope)


def complete_explanation_plan(run, plans, dataset):
    """Add one search when enabled; never change the user's chart to get evidence.

    The raw model message remains in its attempt log. The graph stores the effective
    tool-call message so subsequent tool results always have matching call IDs.
    """
    if not explanation_question(run['question']) or any(p['tool'] == 'request_clarification' for p in plans):
        return plans, None
    effective = list(plans)
    local = [p for p in effective if p['tool'] != 'search_web']
    if not local:
        from api.agent.tools import normalized_context
        question = run['question']
        match = re.search(r'(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?', question)
        month = f'{match[1]}-{int(match[2]):02d}' if match else run['view'].get('month')
        if month:
            tool = 'inspect_month'; args = {'month': month, 'day': None, 'display': 'daily'}
        else:
            tool = 'query_trend'; args = {'granularity': 'month'}
            year = re.search(r'20\d{2}', question)
            if year:
                args.update(start=year[0]+'-01-01', end=year[0]+'-12-31')
        plan = {'tool': tool, 'tool_call_id': 'cause-observations', 'arguments': args, 'update_view': False}
        plan['context'] = normalized_context(dataset, run['view'], tool, args)
        effective.insert(0, plan); local = [plan]
    if run.get('web_search_enabled', True) and not any(p['tool'] == 'search_web' for p in effective):
        c = local[0]['context']
        # Resolve deictic questions with the effective local query, not today's date.
        period = '' if re.search(r'20\d{2}', run['question']) else f' {c["start"]}至{c["end"]}'
        query = (run['question'][:65] + period + ' 上海 环境监测中心 污染 气象 原因')[:128]
        effective.append({'tool': 'search_web', 'tool_call_id': 'cause-background-search',
                          'arguments': {'query': query, 'count': 3}, 'update_view': False})
    if effective == plans:
        return effective, None
    message = {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': p['tool_call_id'], 'type': 'function', 'function': {
            'name': p['tool'], 'arguments': json.dumps({**p['arguments'], 'update_view': p['update_view']}, ensure_ascii=False)
        }} for p in effective
    ]}
    return effective, message
