"""External search routing, references, cancellation and separate cost accounting."""
import json
import tempfile
import unittest
from pathlib import Path
import httpx
from api.agent.model import Model
from api.agent.schemas import RunRequest,SessionRequest
from api.agent.search import WebSearch
from api.agent.service import AgentService
from api.agent.tools import model_tools
from api.service import Dataset,ROOT,QueryError
from tests.agent_fixtures import analysis_response


class AgentSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=Dataset(ROOT/'data/processed')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.requests=[];self.status=200
        self.cfg={'ready':True,'base_url':'https://api.deepseek.com/v1','model':'offline-search','host':'api.deepseek.com','key':'offline-secret','timeout':1,'thinking':'disabled'}
        def response(request):
            self.requests.append(request)
            if request.url.path.endswith('/search'):
                return httpx.Response(self.status,json={'results':[{'title':'上海环境公报','url':'https://sthj.sh.gov.cn/example','snippet':'公开资料的摘要','summary':'官方通报的详细解释','content':'同期输送与气象分析。'*600,'date':'2025-05-01'},
                    {'title':'不可打开','url':'javascript:alert(1)','snippet':'恶意链接'}]})
            answer=analysis_response(json.loads(request.content))
            if answer is not None:return answer
            return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'web-1','type':'function','function':{'name':'search_web','arguments':json.dumps({'query':'上海空气质量 公报 site:sh.gov.cn','count':3})}}]}}]})
        self.transport=httpx.MockTransport(response)
        self.agent=AgentService(lambda:self.data,directory=Path(self.temp.name),
            model_factory=lambda s:Model(s,self.transport,lambda:self.cfg,budget_loader=lambda:6),
            search_factory=lambda s:WebSearch(s,self.transport,lambda:self.cfg))
        self.addCleanup(self.agent.close);self.session=self.agent.create_session(SessionRequest(dataset_version=self.data.version))

    def run_search(self,enabled=True):
        run,_=self.agent.store.reserve_run(self.session['session_id'],RunRequest(client_request_id='external-search-case',expected_revision=0,question='找上海空气质量公报原文',web_search_enabled=enabled).model_dump())
        return self.agent.execute(run['run_id'])

    def test_graph_search_preserves_view_and_publishes_references_with_separate_ledger(self):
        run=self.run_search();self.assertEqual(run['status'],'completed',run.get('error'))
        result=run['result'];self.assertEqual(result['view'],self.session['view']);self.assertEqual(result['results'],[])
        self.assertEqual(result['answer']['source'],'external_sources');self.assertEqual(len(result['answer']['sources']),1)
        self.assertEqual(len(self.agent.store.attempts()),2);self.assertEqual(len(self.agent.store.search_attempts()),1)
        request=self.requests[1];self.assertEqual(str(request.url),'https://api.deepseek.com/v1/tools/search')
        self.assertTrue(json.loads(request.content)['need_content'])
        payload=json.loads(self.requests[2].content)['messages'][-1]['content']
        source=json.loads(payload)['external_sources'][0]
        self.assertEqual(source['summary'],'官方通报的详细解释')
        self.assertEqual(len(source['content_excerpt']),3500);self.assertTrue(source['content_truncated'])
        self.assertNotIn('content_excerpt',result['answer']['sources'][0])
        self.agent.search.execute(self.agent.store.run(run['run_id']),{'query':'上海空气质量 公报 site:sh.gov.cn','count':3})
        self.assertEqual(len(self.requests),3)
        self.assertNotIn('offline-secret',self.agent.store.path.read_bytes().decode('utf-8',errors='ignore'))

    def test_switch_off_omits_search_schema_and_rejects_unauthorized_search(self):
        self.assertNotIn('search_web',[t['function']['name'] for t in model_tools(False)])
        run=self.run_search(False);self.assertEqual(run['status'],'failed');self.assertEqual(len(self.requests),1)
        self.assertEqual(self.agent.store.search_attempts(),[]);self.assertEqual(self.agent.checked_session(self.session['session_id'])['state_revision'],0)

    def test_search_http_failure_does_not_retry_or_publish(self):
        self.status=402;run=self.run_search();self.assertEqual(run['error_code'],'SEARCH_HTTP_ERROR');self.assertEqual(run['status'],'failed')
        with self.assertRaises(QueryError):self.agent.search.execute(self.agent.store.run(run['run_id']),{'query':'上海空气质量 公报 site:sh.gov.cn','count':3})
        self.assertEqual(len(self.requests),2);self.assertEqual(self.agent.checked_session(self.session['session_id'])['state_revision'],0)


if __name__=='__main__':unittest.main()
