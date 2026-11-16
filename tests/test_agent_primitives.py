"""Offline protocol, accounting and publication checks. No real model requests."""
import json
import tempfile
import unittest
import httpx
from api.agent.model import Model
from api.agent.store import Store
from api.agent.tools import comparison_context, parse_plan, execute_comparison
from api.agent.views import build_comparison
from api.agent.schemas import AnalysisView
from api.service import Dataset, ROOT, QueryError


class AgentPrimitiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset(ROOT / 'data/processed')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)
        self.session = self.store.create_session(self.dataset.version, AnalysisView().model_dump())
        self.run, _ = self.store.reserve_run(self.session['session_id'], {
            'client_request_id': 'offline-request-1', 'expected_revision': 0,
            'question': '2025 相比 2021 哪些月份的 P90 更高？',
        })
        self.config = {'ready': True, 'base_url': 'http://127.0.0.1:9999/v1',
                       'model': 'offline-fixture', 'host': '127.0.0.1', 'key': 'offline-secret-marker',
                       'timeout': 1, 'thinking': 'provider_default'}
        self.calls = []

    def model(self, handler, budget=2):
        return Model(self.store, transport=httpx.MockTransport(handler),
                     config_loader=lambda: self.config, budget_loader=lambda: budget)

    def response(self, request):
        self.calls.append(request)
        return httpx.Response(200, json={'model': 'offline-fixture', 'usage': {'total_tokens': 123},
            'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'call-offline-1', 'type': 'function', 'function': {
                    'name': 'compare_periods', 'arguments': json.dumps({'base_year': 2021, 'target_year': 2025, 'statistic': 'p90'})}}]}}]})

    def test_function_call_executes_actual_data_and_duplicate_phase_is_cached(self):
        model = self.model(self.response)
        message = model.plan(self.run, self.dataset)
        self.assertEqual(model.plan(self.run, self.dataset), message)
        self.assertEqual(len(self.calls), 1)
        plan = parse_plan(message)
        context = comparison_context(self.dataset, self.run['view']['context'], plan.arguments)
        result = execute_comparison(self.dataset, context)
        presentation = build_comparison(result)
        self.assertEqual(result['context']['base_year'], 2021)
        self.assertEqual(result['context']['target_year'], 2025)
        self.assertEqual(len(result['data']['rows']), 12)
        self.assertEqual(presentation['view_spec']['data_ref'], result['result_id'])
        self.assertEqual(len(presentation['facts']), 14)
        self.assertNotIn('offline-secret-marker', json.dumps(self.store.attempts()))

    def test_budget_zero_prevents_transport(self):
        with self.assertRaises(QueryError) as caught:
            self.model(self.response, budget=0).plan(self.run, self.dataset)
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(len(self.calls), 0)
        self.assertEqual(len(self.store.attempts()), 0)

    def test_timeout_attempt_is_not_automatically_repeated(self):
        def timeout(request):
            self.calls.append(request)
            raise httpx.ReadTimeout('fixture')
        model = self.model(timeout)
        for expected in [504, 409]:
            with self.assertRaises(QueryError) as caught:
                model.plan(self.run, self.dataset)
            self.assertEqual(caught.exception.status, expected)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.store.attempts()[0]['status'], 'outcome_unknown')

    def test_manual_change_prevents_stale_run_publication(self):
        view = AnalysisView().model_dump()
        view['context']['statistic'] = 'p90'
        updated = self.store.action(self.session['session_id'], {
            'client_request_id': 'manual-change-1', 'expected_revision': 0, 'action': 'apply', 'view': view,
        })
        terminal = self.store.publish(self.run['run_id'], {'view': AnalysisView().model_dump(), 'answer': {'text': 'stale'}})
        self.assertEqual(terminal['status'], 'superseded')
        self.assertEqual(self.store.session(self.session['session_id'])['view'], updated['view'])
        self.assertEqual(self.store.attempts(), [])

    def test_same_request_id_cannot_be_reused_for_a_different_question(self):
        with self.assertRaises(QueryError):
            self.store.reserve_run(self.session['session_id'], {
                'client_request_id': 'offline-request-1', 'expected_revision': 0, 'question': 'Different question',
            })


if __name__ == '__main__':
    unittest.main()
