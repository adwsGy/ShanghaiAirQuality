"""Durable conversation: answer directly, or query evidence and then reason over it."""
import json
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from api.service import QueryError
from api.workspace import signature
from api.agent.schemas import ResultEnvelope
from api.agent.tools import clarification_payload, execute_tool, explicit_conditions, normalized_context, parse_plans, pending_arguments
from api.agent.views import fallback_presentation, layout, presentation, answer_evidence
from api.agent.explanation import complete_explanation_plan


class GraphState(TypedDict, total=False):
    run: dict
    message: dict
    plan: dict
    plans: list
    context: dict
    tool_result: dict
    tool_results: list
    groups: list
    presentation: dict
    candidate: dict
    clarification: dict
    tool_messages: list
    terminal: dict
    external_result: dict


def build_graph(store, model, dataset_loader, checkpointer, search):
    def progress(state, name):
        run = store.run(state['run']['run_id'])
        if dataset_loader().version != run['dataset_version']:
            raise QueryError(409, 'DATA_VERSION_CHANGED', '数据版本已更新，候选结果未发布。')
        if run['cancel_requested']:
            raise QueryError(409, 'RUN_CANCELLED', '已取消后续分析，当前图表保持原条件。')
        store.event(run['run_id'], 'progress', {'step': name})

    def unchanged(state, title):
        view = state['run']['view']
        return {'view': view, 'view_spec': {'task': view['task'], 'data_ref': signature({'run': state['run']['run_id']}),
                'title': title, 'selected_month': view.get('month'), 'secondary_refs': []}}

    def load_context(state):
        progress(state, '读取当前条件')
        run = state['run']
        store.revision(store.session(run['session_id']), run['expected_revision'])
        return {'context': run['view']['context']}

    def plan(state):
        progress(state, '理解问题')
        return {'message': model.plan(state['run'], dataset_loader())}

    def validate_plan(state):
        progress(state, '核对回答与查询条件')
        plans = []
        for parsed in parse_plans(state['message']):
            args = explicit_conditions(state['run']['question'], parsed.tool, parsed.arguments)
            plan = parsed.model_copy(update={'arguments': args}).model_dump()
            if args != parsed.arguments:
                store.event(state['run']['run_id'], 'progress', {'step': '按本次问题明确指定的统计量校正计划',
                    'original_arguments': parsed.arguments, 'effective_arguments': args})
            if plan['tool'] == 'search_web':
                search.validate(state['run'], args)
            elif plan['tool'] != 'request_clarification':
                plan['context'] = normalized_context(dataset_loader(), state['run']['view'], plan['tool'], args)
            plans.append(plan)
        plans, effective_message = complete_explanation_plan(state['run'], plans, dataset_loader())
        update = {'plans': plans, 'plan': plans[0] if plans else {}}
        if effective_message:
            update['message'] = effective_message
            store.event(state['run']['run_id'], 'progress', {'step': '结合本地观测检索同期成因资料'})
        if plans and plans[0]['tool'] == 'request_clarification':
            update['clarification'] = clarification_payload(dataset_loader(), state['run']['view'], plans[0])
        return update

    def clarify(state):
        payload = state['clarification']; run = state['run']; run_id = run['run_id']
        if payload['kind'] != 'winter':
            terminal = store.update_run(run_id, status='clarification_required', clarification=payload)
            store.remember_clarification(run_id, payload); store.event(run_id, 'clarification_required', payload)
            return {'terminal': terminal}
        choice = interrupt(payload)
        if choice not in ('calendar_winter', 'cross_year_winter'):
            raise QueryError(422, 'INVALID_CHOICE', '请选择有效的冬季定义。')
        progress(state, '应用冬季定义并继续分析')
        store.revision(store.session(run['session_id']), run['expected_revision'])
        pending = state['plan']['arguments']; tool = pending['resume_tool']
        args = {**pending_arguments(run['view'], tool, pending.get('resume_arguments', {})),
                'months': [1, 2, 12], 'season_definition': choice}
        plan = {'tool': tool, 'tool_call_id': state['plan']['tool_call_id'], 'arguments': args,
                'update_view': state['plan'].get('update_view', False),
                'context': normalized_context(dataset_loader(), run['view'], tool, args)}
        return {'plan': plan, 'plans': [plan]}

    def direct_answer(state):
        progress(state, '整理回答')
        return {'candidate': unchanged(state, '问答'), 'tool_results': [], 'tool_messages': [],
                'presentation': {'facts': [], 'answer': {'text': state['message']['content'].strip(),
                    'fact_ids': [], 'source': 'model_explanation', 'sources': []}}}

    def execute_tools(state):
        progress(state, '查询分析所需的数据与资料')
        all_results = []; groups = []; messages = [state['message']]; external = {}
        for plan in state['plans']:
            progress(state, '搜索外部资料' if plan['tool'] == 'search_web' else '执行数据查询与统计')
            if plan['tool'] == 'search_web':
                try:
                    external = search.execute(state['run'], plan['arguments'])
                    external['status'] = 'completed' if external['sources'] else 'no_results'
                except QueryError as error:
                    if not any(p['tool'] not in ('search_web','request_clarification') for p in state['plans']):raise
                    external = {'sources': [], 'status': 'failed', 'error_code': error.code, 'error': error.message}
                    store.event(state['run']['run_id'], 'progress', {'step': '外部检索未完成，保留本地统计', 'code': error.code})
                content = {'executed_tool': 'search_web', **external}
                store.event(state['run']['run_id'], 'tool_completed', {'tool': 'search_web',
                    'result_id': external.get('result_id'), 'source_count': len(external['sources'])})
            else:
                results, context = execute_tool(dataset_loader(), state['run']['view'], plan['tool'], plan['arguments'], plan['context'])
                groups.append({'plan': plan, 'results': results, 'context': context})
                all_results.extend(results)
                content = {'executed_tool': plan['tool'], 'results': results}
                for result in results:
                    store.event(state['run']['run_id'], 'tool_completed', {'tool': plan['tool'],
                        'result_id': result['result_id'], 'task': result['task']})
            messages.append({'role': 'tool', 'tool_call_id': plan['tool_call_id'], 'content': json.dumps(content, ensure_ascii=False)})
        return {'groups': groups, 'tool_results': all_results, 'tool_result': all_results[0] if all_results else {},
                'tool_messages': messages, 'external_result': external,
                'context': groups[0]['context'] if groups else state['context']}

    def build_view(state):
        progress(state, '组织分析依据')
        groups = state['groups']
        if not groups:
            return {'candidate': unchanged(state, '资料解读')}
        target = next((g for g in groups if g['plan']['update_view']), groups[0])
        built = layout(target['results'], target['plan']['arguments'])
        return {'candidate': {**built, 'suggested_view': built['view'],
            'view': built['view'] if target['plan']['update_view'] else state['run']['view']}}

    def compose_answer(state):
        progress(state, '结合查询结果分析并回答')
        facts = []; fallbacks = []; external = state['external_result']; sources = external.get('evidence_sources', external.get('sources', []))
        for index, group in enumerate(state['groups'], 1):
            try:
                built = presentation(group['results'], group['plan']['arguments'])
            except Exception:
                built = fallback_presentation(group['results'])
            for fact in built['facts']:
                facts.append({**fact, 'id': f'R{index}_{fact["id"]}'})
            fallbacks.append(built['answer']['text'])
        try:
            answer = model.answer({**state['run'], 'search_outcome': {k:external[k] for k in ('status','error_code','error','query') if k in external}}, dataset_loader(), answer_evidence(state['tool_results']), facts, sources,
                                  any(p['update_view'] for p in state['plans']))
        except QueryError as error:
            store.event(state['run']['run_id'], 'progress', {'step': '分析回答暂不可用，保留真实查询结果', 'code': error.code})
            answer = {'text': '模型未能完成分析回答，以下为程序计算的结果摘要。\n\n' + '\n\n'.join(fallbacks or ['外部资料见下方来源。']),
                      'fact_ids': [f['id'] for f in facts], 'source': 'computed_fallback',
                      'sources': [{k:s.get(k) for k in ('title','url','snippet','date')} for s in sources]}
        return {'presentation': {'facts': facts, 'answer': answer}}

    def publish(state):
        progress(state, '保存回答')
        run = state['run']; refs = list(dict.fromkeys(r['result_id'] for r in state['tool_results']))
        if state['external_result'].get('result_id'):refs.append(state['external_result']['result_id'])
        envelope = ResultEnvelope.model_validate({'session_id': run['session_id'], 'run_id': run['run_id'],
            'dataset_version': run['dataset_version'], 'state_revision': run['expected_revision'] + 1,
            'context': state['context'], 'result_refs': refs, 'view_spec': state['candidate']['view_spec'], **state['presentation']}).model_dump()
        bundle = {**envelope, 'view': state['candidate']['view'], 'suggested_view': state['candidate'].get('suggested_view'),
                  'results': state['tool_results'], 'tool_messages': state['tool_messages']}
        terminal = store.publish(run['run_id'], bundle)
        event = 'result' if terminal['status'] == 'completed' else 'cancelled' if terminal['status'] == 'cancelled' else 'error'
        store.event(run['run_id'], event, {'status': terminal['status'],
            'state_revision': terminal['result']['state_revision'] if terminal.get('result') else run['expected_revision']})
        return {'terminal': terminal}

    graph = StateGraph(GraphState)
    for name, node in {'load_context': load_context, 'plan': plan, 'validate_plan': validate_plan, 'clarify': clarify,
                       'direct_answer': direct_answer, 'execute_tools': execute_tools, 'build_view': build_view,
                       'compose_answer': compose_answer, 'publish': publish}.items():graph.add_node(name, node)
    graph.add_edge(START, 'load_context'); graph.add_edge('load_context', 'plan'); graph.add_edge('plan', 'validate_plan')
    graph.add_conditional_edges('validate_plan', lambda s: 'direct_answer' if not s['plans'] else
                                'clarify' if s['plan']['tool'] == 'request_clarification' else 'execute_tools')
    graph.add_conditional_edges('clarify', lambda s: END if s['plan']['tool'] == 'request_clarification' else 'execute_tools')
    graph.add_edge('execute_tools', 'build_view'); graph.add_edge('build_view', 'compose_answer')
    graph.add_edge('direct_answer', 'publish'); graph.add_edge('compose_answer', 'publish'); graph.add_edge('publish', END)
    return graph.compile(checkpointer=checkpointer)
