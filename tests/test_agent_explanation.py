"""Scoped explanations must use both real observations and the enabled search."""
import json
from pathlib import Path
import tempfile
import unittest
import httpx

from api.agent.explanation import explanation_question
from api.agent.model import Model, requires_observations
from api.agent.schemas import RunRequest, SessionRequest
from api.agent.search import WebSearch
from api.agent.service import AgentService
from api.service import Dataset, ROOT


class ExplanationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=Dataset(ROOT/'data/processed')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.calls=[];self.search_status=200;self.bad_reference=False;self.direct=False
        cfg={'ready':True,'base_url':'https://api.deepseek.com/v1','model':'offline-explanation',
             'host':'api.deepseek.com','key':'fixture-secret','timeout':1,'thinking':'disabled'}
        def response(request):
            self.calls.append(request);body=json.loads(request.content)
            if request.url.path.endswith('/search'):
                return httpx.Response(self.search_status,json={'results':[{'title':'同期污染过程解释',
                    'url':'https://sthj.sh.gov.cn/example','date':'2023-11-24','snippet':'输送叠加本地累积',
                    'summary':'监测专家说明11月23日输送过程。','content':'该日受静稳与弱冷空气输送影响。'}]})
            if 'tools' in body:
                message={'role':'assistant','content':'没有气象所以无法回答。'} if self.direct else {
                    'role':'assistant','content':None,'tool_calls':[{'id':'inspect','type':'function','function':{
                        'name':'inspect_month','arguments':json.dumps({'month':'2023-11','day':None})}}]}
                return httpx.Response(200,json={'choices':[{'finish_reason':'stop' if self.direct else 'tool_calls','message':message}]})
            p=json.loads(body['messages'][-1]['content']);sources=p['external_sources']
            text='本地月内分布与同期过程资料可结合解释[R1_DAILY_DISTRIBUTION]。'
            if sources:text+='该日存在输送影响[来源9]。' if self.bad_reference else '该日存在输送影响[来源1]。'
            if (p.get('search_outcome') or {}).get('status')=='failed':text+='本次搜索失败。'
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':text}}]})
        transport=httpx.MockTransport(response)
        self.agent=AgentService(lambda:self.data,directory=Path(self.temp.name),
            model_factory=lambda s:Model(s,transport,lambda:cfg),search_factory=lambda s:WebSearch(s,transport,lambda:cfg))
        self.addCleanup(self.agent.close)
        self.session=self.agent.create_session(SessionRequest(dataset_version=self.data.version))

    def execute(self,enabled=True):
        run,_=self.agent.store.reserve_run(self.session['session_id'],RunRequest(client_request_id='cause-question-test',
            expected_revision=0,question='2023年11月为啥PM2.5这么高，你能解释吗',web_search_enabled=enabled).model_dump())
        return self.agent.execute(run['run_id'])

    def test_missing_search_is_added_once_and_evidence_reaches_answer_without_changing_chart(self):
        run=self.execute();self.assertEqual(run['status'],'completed',run.get('error'))
        self.assertEqual(len(self.calls),3);self.assertEqual(len(self.agent.store.search_attempts()),1)
        self.assertEqual(run['result']['view'],self.session['view'])
        self.assertEqual(len(run['result']['answer']['sources']),1)
        self.assertIn('2023年11月',json.loads(self.calls[1].content)['query'])
        payload=json.loads(json.loads(self.calls[2].content)['messages'][-1]['content'])
        self.assertIn('输送',payload['external_sources'][0]['content_excerpt'])
        summary=payload['query_results'][0]['data']['observations']['daily_summary']
        self.assertAlmostEqual(summary['without_maximum_mean'],31.467078960519725)
        self.assertEqual(summary['without_maximum_n'],29)
        self.assertEqual(run['result']['answer']['source'],'model_analysis')
        messages=run['result']['tool_messages']
        self.assertEqual({c['id'] for c in messages[0]['tool_calls']},{m['tool_call_id'] for m in messages[1:]})

    def test_disabled_search_remains_disabled(self):
        run=self.execute(False);self.assertEqual(run['status'],'completed',run.get('error'))
        self.assertEqual(len(self.calls),2);self.assertEqual(self.agent.store.search_attempts(),[])
        self.assertEqual(run['result']['answer']['sources'],[])

    def test_search_failure_keeps_statistics_and_reports_actual_search_outcome(self):
        self.search_status=503;run=self.execute()
        self.assertEqual(run['status'],'completed',run.get('error'))
        self.assertIn('本次搜索失败',run['result']['answer']['text'])
        self.assertEqual(len(run['result']['results']),1);self.assertEqual(len(self.calls),3)

    def test_unknown_external_citation_cannot_be_published(self):
        self.bad_reference=True;run=self.execute()
        self.assertEqual(run['status'],'completed',run.get('error'))
        self.assertEqual(run['result']['answer']['source'],'computed_fallback')
        self.assertNotIn('来源9',run['result']['answer']['text'])
        self.assertEqual(len(run['result']['answer']['sources']),1)

    def test_direct_model_refusal_still_queries_for_scoped_explanation(self):
        self.direct=True;run=self.execute()
        self.assertEqual(run['status'],'completed',run.get('error'))
        self.assertEqual(run['result']['results'][0]['task'],'observations')
        self.assertEqual(run['result']['results'][0]['context']['start'],'2023-11-01')
        self.assertEqual(len(self.calls),3)

    def test_concept_question_does_not_force_an_observation_search(self):
        self.assertFalse(explanation_question('为什么P90通常高于均值？'))
        self.assertFalse(explanation_question('冬季为什么容易污染？'))
        self.assertTrue(requires_observations('2023年11月为啥PM2.5这么高'))


if __name__=='__main__':unittest.main()
