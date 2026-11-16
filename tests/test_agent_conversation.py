"""Conversation regressions: real statistics, provider-shaped responses, no network."""
import json
from pathlib import Path
import tempfile
import unittest
import httpx
from api.agent.model import Model,reconcile_counts,requires_observations
from api.agent.schemas import ActionRequest, RunRequest, SessionRequest
from api.agent.service import AgentService
from api.agent.views import answer_evidence
from api.service import Dataset, ROOT
from tests.agent_fixtures import analysis_response


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=Dataset(ROOT/'data/processed')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.calls=[];self.direct=None;self.answer_failure=False;self.bad_citation=False;self.inline_only=False;self.prose=False
        self.plans=[('compare_periods',{'base_year':2022,'target_year':2023})]
        cfg={'ready':True,'model':'offline-conversation','base_url':'http://127.0.0.1:9999/v1','host':'127.0.0.1','key':'fixture-private-key','timeout':1,'thinking':'disabled'}
        def response(request):
            body=json.loads(request.content);self.calls.append(body)
            if 'tools' not in body:
                if self.answer_failure:return httpx.Response(503)
                if self.prose:return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'实际差异并非各月一致，全年统计见[R1_PERIOD]。'}}]})
                if self.inline_only:return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps({'text':'参见实际结果[R1_PERIOD]。'})}}]})
                if self.bad_citation:return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps({'text':'未知依据[R9_FAKE]','fact_ids':['R1_PERIOD']})}}]})
                return analysis_response(body)
            message={'role':'assistant','content':self.direct}
            if self.direct is None:message['tool_calls']=[{'id':f'query-{i}','type':'function','function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(self.plans)]
            return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls' if self.direct is None else 'stop','message':message}]})
        self.agent=AgentService(lambda:self.data,directory=self.temp.name,model_factory=lambda s:Model(s,httpx.MockTransport(response),lambda:cfg))
        self.addCleanup(self.agent.close)
        self.session=self.agent.create_session(SessionRequest(dataset_version=self.data.version))

    def execute(self,question='2023相比2022的变化普遍吗？'):
        latest=self.agent.checked_session(self.session['session_id'])
        run,_=self.agent.store.reserve_run(latest['session_id'],RunRequest(client_request_id=f'conversation-{len(self.calls)}',expected_revision=latest['state_revision'],question=question).model_dump())
        return self.agent.execute(run['run_id'])

    def test_concept_question_returns_text_without_query_or_chart_change(self):
        self.direct='P90是第90百分位；AQI是空气质量指数，PM2.5是污染物浓度。'
        run=self.execute('P90是什么意思，和AQI有什么区别？')
        self.assertEqual(run['status'],'completed',run.get('error'))
        result=run['result'];self.assertEqual(result['answer']['source'],'model_explanation')
        self.assertEqual(result['answer']['text'],self.direct);self.assertEqual(result['results'],[])
        self.assertEqual(result['view'],self.session['view']);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0]['tool_choice'],'auto')

    def test_analytical_answer_receives_actual_evidence_and_preserves_chart(self):
        run=self.execute();self.assertEqual(run['status'],'completed',run.get('error'))
        result=run['result'];self.assertEqual(result['answer']['source'],'model_analysis')
        self.assertEqual(result['view'],self.session['view']);self.assertEqual(result['suggested_view']['task'],'compare')
        payload=json.loads(self.calls[1]['messages'][-1]['content'])
        self.assertFalse(payload['chart_updated']);self.assertEqual(payload['question'],run['question'])
        self.assertEqual(payload['query_results'][0]['data']['rows'],result['results'][0]['data']['rows'])
        self.assertTrue(set(result['answer']['fact_ids'])<={f['id'] for f in result['facts']})
        self.assertEqual([a['phase'] for a in self.agent.store.attempts()],['plan','answer'])
        self.assertEqual(self.calls[0]['tool_choice'],'required')

    def test_multiple_queries_combine_evidence_and_use_requested_chart(self):
        self.plans.append(('compare_distributions',{'base_year':2022,'target_year':2023,'update_view':True}))
        run=self.execute('分析这两年并展示分布图');self.assertEqual(run['status'],'completed',run.get('error'))
        result=run['result'];self.assertEqual(result['view']['task'],'distribution')
        self.assertEqual(len(result['results']),2);self.assertEqual(len(result['tool_messages']),3)
        ids=[f['id'] for f in result['facts']];self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(any(i.startswith('R2_') for i in ids))
        payload=json.loads(self.calls[1]['messages'][-1]['content']);self.assertEqual(len(payload['query_results']),2)
        self.assertTrue(payload['chart_updated']);self.assertNotIn('curves',payload['query_results'][1]['data'])

    def test_legacy_budget_file_and_seventh_question_do_not_block_use(self):
        (Path(self.temp.name)/'budget.json').write_text('{"max_calls":0}',encoding='utf-8')
        self.direct='可以继续提问。'
        for _ in range(8):self.assertEqual(self.execute('还能继续问吗？')['status'],'completed')
        self.assertEqual(len(self.calls),8)
        status=self.agent.model.status();self.assertIsNone(status['max_calls']);self.assertIsNone(status['remaining_calls'])
        self.assertEqual(status['used_calls'],8);self.assertIsNone(self.agent.search.status()['max_calls'])

    def test_failed_analysis_is_explicit_and_keeps_computed_results(self):
        self.answer_failure=True;run=self.execute();self.assertEqual(run['status'],'completed')
        self.assertEqual(run['result']['answer']['source'],'computed_fallback')
        self.assertIn('模型未能完成',run['result']['answer']['text'])
        self.assertEqual(len(run['result']['results'][0]['data']['rows']),12)
        self.assertEqual(run['result']['view'],self.session['view']);self.assertEqual(len(self.calls),2)

    def test_unknown_inline_reference_cannot_be_published_as_model_analysis(self):
        self.bad_citation=True;run=self.execute();self.assertEqual(run['status'],'completed')
        self.assertEqual(run['result']['answer']['source'],'computed_fallback')
        self.assertNotIn('R9_FAKE',run['result']['answer']['text'])

    def test_valid_inline_citations_survive_provider_omitting_redundant_id_array(self):
        self.inline_only=True;run=self.execute()
        self.assertEqual(run['result']['answer']['source'],'model_analysis')
        self.assertEqual(run['result']['answer']['fact_ids'],['R1_PERIOD'])
        self.assertEqual(len(self.calls),2)

    def test_native_prose_with_real_citations_does_not_require_json_mode(self):
        self.prose=True;run=self.execute()
        self.assertEqual(run['result']['answer']['source'],'model_analysis')
        self.assertEqual(run['result']['answer']['fact_ids'],['R1_PERIOD'])
        self.assertNotIn('response_format',self.calls[1])

    def test_concrete_period_analysis_cannot_skip_query_in_favor_of_old_prose(self):
        self.assertTrue(requires_observations('请用三段话分析上海全市2023年与2022年的月均和P90：升降是否普遍、哪些月份突出、这两个统计量能说明什么。不要切换图表。'))
        self.assertFalse(requires_observations('P90是什么意思？它和均值有什么区别，什么时候更适合看P90？'))
        self.assertFalse(requires_observations('项目的数据P90怎么算？'))

    def test_question_with_monthly_mean_and_p90_preserves_both_tool_metrics(self):
        self.plans=[('compare_periods',{'base_year':2022,'target_year':2023,'statistic':metric}) for metric in ('mean','p90')]
        run=self.execute('结合月均和P90分析变化。')
        results=run['result']['results']
        self.assertEqual([r['context']['statistic'] for r in results],['mean','p90'])
        self.assertNotEqual(results[0]['data']['rows'][0]['delta'],results[1]['data']['rows'][0]['delta'])
        text,corrections=reconcile_counts('有5个月均值下降、4个月P90下降。均值有7个月上升，P90有8个月上升。',answer_evidence(results))
        self.assertEqual(text,'有4个月均值下降、5个月P90下降。均值有8个月上升，P90有7个月上升。')
        self.assertEqual(len(corrections),4)

    def test_repeated_read_and_answer_phase_do_not_call_provider_again(self):
        run=self.execute();saved=self.agent.checked_session(self.session['session_id'])
        payload=json.loads(self.calls[1]['messages'][-1]['content'])
        for _ in range(2):
            self.agent.model.answer(self.agent.store.run(run['run_id']),self.data,payload['query_results'],payload['facts'],[],False)
            self.assertEqual(self.agent.checked_session(self.session['session_id'])['last_result'],saved['last_result'])
        self.assertEqual(len(self.calls),2)
        self.assertNotIn('fixture-private-key',json.dumps(self.agent.store.attempts()))

    def test_followup_gets_previous_query_context_until_manual_conditions_change(self):
        self.execute();self.direct='请继续。';self.execute('刚才的比较是什么意思？')
        payload=json.loads(self.calls[-1]['messages'][-2]['content'])
        self.assertEqual(payload['recent_analysis']['context']['base_year'],2022)
        self.assertEqual(payload['recent_analysis']['queries'][0]['task'],'compare')
        current=self.agent.checked_session(self.session['session_id']);view=current['view'];view['context']['statistic']='p90'
        self.agent.action(current['session_id'],ActionRequest(client_request_id='manual-reset-context',expected_revision=current['state_revision'],view=view))
        self.execute('当前是什么统计量？')
        payload=json.loads(self.calls[-1]['messages'][-2]['content'])
        self.assertIsNone(payload['recent_analysis']);self.assertEqual(payload['confirmed_view']['context']['statistic'],'p90')

    def test_large_evidence_reports_omissions_and_retains_real_extremes(self):
        self.plans=[('query_trend',{'start':'2015-01-01','end':'2025-12-31','granularity':'day'})]
        result=self.execute()['result']['results'][0]
        packet=answer_evidence([result])[0]['data']['points']
        self.assertGreater(packet['omitted'],0)
        self.assertEqual(packet['total'],len(result['data']['points']))
        maximum=max(p['mean'] for p in result['data']['points'] if p['mean'] is not None)
        self.assertEqual(max(p['mean'] for p in packet['rows'] if p['mean'] is not None),maximum)


if __name__=='__main__':unittest.main()
