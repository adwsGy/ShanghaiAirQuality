"""Offline LangGraph execution, checkpoint and HTTP tests using real statistical tools."""
import json
import tempfile
import time
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from api.app import create_app
from api.agent.model import Model
from api.agent.schemas import AnalysisView, RunRequest, SessionRequest
from api.agent.service import AgentService
from api.service import Dataset, ROOT
from tests.agent_fixtures import analysis_response


class AgentGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(ROOT / 'data/processed')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.calls = []
        self.arguments = {'base_year': 2022, 'target_year': 2023}
        self.tool_name = 'compare_periods'
        self.service = self.new_service()
        self.addCleanup(self.service.close)

    def response(self, request):
        self.calls.append(request)
        answer=analysis_response(json.loads(request.content))
        if answer is not None:return answer
        message = {'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': 'call-graph-fixture', 'type': 'function',
            'function': {'name': self.tool_name, 'arguments': json.dumps({**self.arguments,'update_view':True})},
        }]}
        return httpx.Response(200, json={'model': 'graph-fixture', 'choices': [{'message': message, 'finish_reason': 'tool_calls'}]})

    def new_service(self, budget=10):
        config = {'ready': True, 'base_url': 'http://127.0.0.1:9999/v1', 'model': 'graph-fixture',
                  'host': '127.0.0.1', 'key': 'fixture-only', 'timeout': 1, 'thinking': 'provider_default'}
        return AgentService(lambda: self.dataset, directory=self.temporary.name,
                            model_factory=lambda store: Model(store, httpx.MockTransport(self.response),
                                config_loader=lambda: config, budget_loader=lambda: budget))

    def session(self):
        return self.service.create_session(SessionRequest(dataset_version=self.dataset.version))

    def execute(self, session, question='2023 比 2022 高在哪些月份？'):
        run, _ = self.service.store.reserve_run(session['session_id'], RunRequest(
            client_request_id='graph-fixture-request', expected_revision=session['state_revision'], question=question).model_dump())
        return self.service.execute(run['run_id'])

    def test_graph_publishes_computed_view_and_matching_tool_message(self):
        session = self.session()
        run = self.execute(session)
        self.assertEqual(run['status'], 'completed', run.get('error'))
        bundle = run['result']
        self.assertEqual(bundle['view']['task'], 'compare')
        self.assertEqual(bundle['context']['base_year'], 2022)
        self.assertEqual(bundle['state_revision'], 1)
        self.assertEqual(bundle['tool_messages'][1]['tool_call_id'], 'call-graph-fixture')
        self.assertEqual(bundle['results'][0]['result_id'], bundle['result_refs'][0])
        actual = self.dataset.workspace.execute({'dataset_version': self.dataset.version, 'task': 'compare', 'context': bundle['context']})
        self.assertEqual(actual['data'], bundle['results'][0]['data'])
        self.assertEqual(len(self.calls), 2)
        steps = [e['data']['step'] for e in self.service.store.events(run['run_id']) if e['event'] == 'progress']
        self.assertIn('结合查询结果分析并回答',steps)

    def test_checkpoint_and_business_state_survive_reopening_without_model_replay(self):
        session = self.session()
        run = self.execute(session)
        self.service.close()
        recovered = self.new_service()
        self.addCleanup(recovered.close)
        saved = recovered.checked_session(session['session_id'])
        checkpoint = recovered.graph.get_state({'configurable': {'thread_id': session['session_id']}})
        self.assertEqual(saved['last_result']['run_id'], run['run_id'])
        self.assertEqual(checkpoint.values['tool_result']['result_id'], saved['last_result']['result_refs'][0])
        self.assertEqual(len(self.calls), 2)

    def test_unknown_tool_keeps_confirmed_view(self):
        session = self.session()
        self.tool_name = 'execute_python'
        run = self.execute(session)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error_code'], 'INVALID_PLAN')
        self.assertEqual(self.service.store.session(session['session_id'])['state_revision'], 0)

    def test_clarification_has_no_statistical_result_or_view_change(self):
        self.tool_name = 'request_clarification'
        self.arguments = {'question': '请选择两个比较年份。', 'options': ['2022与2023', '2021与2025']}
        session = self.session()
        run = self.execute(session, '比较一下')
        self.assertEqual(run['status'], 'clarification_required')
        self.assertIsNone(run['result'])
        self.assertEqual(self.service.store.session(session['session_id'])['view'], session['view'])

    def test_no_observations_remains_null_and_does_not_become_zero(self):
        self.arguments = {'object_id': '1146A', 'base_year': 2022, 'target_year': 2025}
        run = self.execute(self.session())
        self.assertEqual(run['status'], 'completed', run.get('error'))
        for row in run['result']['results'][0]['data']['rows']:
            self.assertIsNone(row['base']['mean'])
            self.assertIsNone(row['target']['mean'])
            self.assertIsNone(row['delta'])

    def test_two_sessions_are_isolated(self):
        first, second = self.session(), self.session()
        self.execute(first)
        self.assertEqual(self.service.store.session(second['session_id'])['state_revision'], 0)
        self.assertIsNone(self.service.store.session(second['session_id'])['last_result'])

    def test_tool_failure_keeps_the_confirmed_view(self):
        session = self.session()
        with patch.object(self.dataset.workspace, 'execute', side_effect=RuntimeError('offline tool failure')):
            run = self.execute(session)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error_code'], 'WORKFLOW_ERROR')
        self.assertEqual(self.service.store.session(session['session_id'])['state_revision'], 0)

    def test_empty_budget_blocks_model_but_not_direct_actions(self):
        self.service.model.budget_loader = lambda: 0
        session = self.session()
        run = self.execute(session)
        self.assertEqual(run['error_code'], 'AGENT_BUDGET_REACHED')
        self.assertEqual(len(self.calls), 0)
        view = AnalysisView().model_dump()
        view['context']['statistic'] = 'p90'
        updated = self.service.store.action(session['session_id'], {
            'client_request_id': 'budget-free-action', 'expected_revision': 0, 'action': 'apply', 'view': view,
        })
        self.assertEqual(updated['view']['context']['statistic'], 'p90')

    def test_http_duplicate_run_id_is_idempotent(self):
        with TestClient(create_app(agent_service=self.service)) as client:
            session = client.post('/api/v1/analysis/sessions', json={'dataset_version': self.dataset.version}).json()
            url = f'/api/v1/analysis/sessions/{session["session_id"]}/runs'
            body = {'client_request_id': 'http-fixture-request', 'expected_revision': 0, 'question': '比较两个年份'}
            first = client.post(url, json=body)
            second = client.post(url, json=body)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()['run_id'], second.json()['run_id'])
            run_url = '/api/v1/analysis/runs/' + first.json()['run_id']
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                run = client.get(run_url).json()
                if run['status'] not in ('queued', 'running'):
                    break
                time.sleep(.01)
            self.assertEqual(run['status'], 'completed', run.get('error'))
            self.assertEqual(len(self.calls), 2)


if __name__ == '__main__':
    unittest.main()
