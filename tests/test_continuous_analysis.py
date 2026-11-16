"""Numerical and lifecycle checks for continuous analysis, without real model requests."""
import json
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from api.app import create_app
from api.service import Dataset, QueryError, ROOT
from api.workspace import WorkspaceService
from api.agent.model import Model
from api.agent.schemas import ActionRequest, ClarificationRequest, RecoveryRequest, RunRequest, SessionRequest
from api.agent.service import AgentService
from api.agent.tools import execute_tool, normalized_context
from tests.agent_fixtures import analysis_response


class ContinuousAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=Dataset(ROOT/'data/processed')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.calls=[];self.tool='compare_periods';self.args={'base_year':2022,'target_year':2023};self.block=None
        self.agent=self.service();self.addCleanup(self.agent.close)
        self.session=self.agent.create_session(SessionRequest(dataset_version=self.data.version))

    def response(self,request):
        self.calls.append(json.loads(request.content))
        answer=analysis_response(self.calls[-1])
        if answer is not None:return answer
        if self.block:
            self.block[0].set();self.block[1].wait(5)
        return httpx.Response(200,json={'model':'offline-continuous','choices':[{'finish_reason':'tool_calls','message':{
            'role':'assistant','content':None,'tool_calls':[{'id':'continuous-call','type':'function','function':{'name':self.tool,'arguments':json.dumps({**self.args,'update_view':True})}}]}}]})

    def service(self):
        cfg={'ready':True,'base_url':'http://127.0.0.1:9999/v1','model':'offline-continuous','host':'127.0.0.1','key':'offline-only','timeout':1,'thinking':'provider_default'}
        return AgentService(lambda:self.data,directory=self.temp.name,model_factory=lambda store:Model(store,httpx.MockTransport(self.response),config_loader=lambda:cfg,budget_loader=lambda:30))

    def reserve(self,question='连续分析协议测试'):
        return self.agent.store.reserve_run(self.session['session_id'],RunRequest(client_request_id='continuous-'+str(len(self.calls)),expected_revision=self.agent.store.session(self.session['session_id'])['state_revision'],question=question).model_dump())[0]

    def execute(self):
        run=self.reserve();return self.agent.execute(run['run_id'])

    def wait(self,run_id,agent=None):
        service=agent or self.agent;deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            run=service.store.run(run_id)
            if run['status'] not in ('queued','running','cancelling'):return run
            time.sleep(.01)
        self.fail('offline run did not finish')

    def test_cross_year_winter_dates_and_distribution_are_exact(self):
        self.tool='compare_distributions';self.args={'base_year':2020,'target_year':2024,'months':[1,2,12],'season_definition':'cross_year_winter'}
        run=self.execute();self.assertEqual(run['status'],'completed',run.get('error'))
        result=run['result']['results'][0];rows=result['data']['rows']
        self.assertEqual([r['month'] for r in rows],[12,1,2]);self.assertEqual(rows[0]['target_period'],'2023-12')
        for key,year in [('base',2020),('target',2024)]:
            frame=self.data.city;prefix=[f'{year-1}-12',f'{year}-01',f'{year}-02']
            values=frame.loc[frame.date.str[:7].isin(prefix)&frame.status.eq('ok'),'pm25_ug_m3']
            self.assertEqual(result['data'][key]['n'],len(values))
            self.assertAlmostEqual(result['data'][key]['p90'],np.quantile(values,.9),places=9)
        for curve in result['data']['curves']:
            self.assertEqual(curve['points'][0],[0.,0.]);self.assertEqual(curve['points'][-1][1],1.)
            self.assertTrue(all(a[0]<=b[0] and a[1]<=b[1] for a,b in zip(curve['points'],curve['points'][1:])))

    def test_winter_interrupt_survives_restart_and_resumes_without_another_call(self):
        self.tool='request_clarification';self.args={'question':'请选择冬季定义','options':[],'kind':'winter','resume_tool':'compare_periods','resume_arguments':{'base_year':2020,'target_year':2024,'granularity':'year'}}
        run=self.execute();self.assertEqual(run['status'],'clarification_required')
        self.agent.close();recovered=self.service();self.addCleanup(recovered.close)
        request=ClarificationRequest(client_request_id='resume-winter-one',expected_revision=0,choice='cross_year_winter')
        first=recovered.resume_run(run['run_id'],request);second=recovered.resume_run(run['run_id'],request)
        self.assertEqual(first['run_id'],second['run_id'])
        finished=self.wait(run['run_id'],recovered)
        self.assertEqual(finished['status'],'completed',finished.get('error'))
        self.assertEqual(finished['result']['context']['season_definition'],'cross_year_winter')
        self.assertEqual(len(self.calls),2);self.assertEqual(len(recovered.store.attempts()),2)

    def test_local_validation_recovery_reuses_saved_response_without_calling_model(self):
        with patch('api.agent.graph.normalized_context',side_effect=QueryError(422,'INVALID_QUERY','offline contract failure')):run=self.execute()
        self.assertEqual(run['status'],'failed')
        request=RecoveryRequest(client_request_id='recover-saved-plan',expected_revision=0)
        self.agent.recover_run(run['run_id'],request)
        finished=self.wait(run['run_id']);self.assertEqual(finished['status'],'completed',finished.get('error'))
        self.assertEqual(len(self.calls),2);self.assertTrue(finished['recovered_saved_plan'])

    def test_period_stations_track_actual_top_values_at_monthly_scale(self):
        self.tool='station_analysis';self.args={'station_mode':'period','start':'2023-01-01','end':'2023-03-31','months':[1,2,3],'statistic':'p90','track_top':3,'granularity':'month'}
        run=self.execute();self.assertEqual(run['status'],'completed',run.get('error'))
        bundle=run['result'];self.assertEqual(len(bundle['results']),2)
        frame=self.data.site;frame=frame.loc[frame.date.between('2023-01-01','2023-03-31')&frame.status.eq('ok')]
        ranking=frame.groupby('object_id').pm25_ug_m3.quantile(.9).sort_values(ascending=False)
        self.assertEqual(bundle['context']['selected_station_ids'],list(ranking.index[:3]))
        for series in bundle['results'][1]['data']['series']:
            self.assertEqual([p['period'] for p in series['points']],['2023-01','2023-02','2023-03'])
            self.assertTrue(all(p['n']>0 for p in series['points']))

    def test_explicit_quarter_mean_replaces_inherited_winter_and_wrong_model_metric(self):
        self.session['view']['context'].update(start='2020-01-01',end='2024-12-31',months=[1,2,12],season_definition='cross_year_winter',statistic='p90')
        self.session=self.agent.create_session(SessionRequest(dataset_version=self.data.version,view=self.session['view']))
        self.tool='station_analysis';self.args={'station_mode':'period','start':'2023-01-01','end':'2023-03-31','statistic':'p90','station_sort':'target_desc','track_top':3,'granularity':'month'}
        run=self.agent.execute(self.reserve('换成2023年第一季度，列出各监测站的观测均值，选出最高的三个站点，按月追踪它们。')['run_id'])
        self.assertEqual(run['status'],'completed',run.get('error'))
        context=run['result']['context'];self.assertEqual(context['statistic'],'mean');self.assertIsNone(context['season_definition'])
        values=self.data.site.loc[self.data.site.date.between('2023-01-01','2023-03-31')&self.data.site.status.eq('ok')].groupby('object_id').pm25_ug_m3.mean().sort_values(ascending=False)
        self.assertEqual(context['selected_station_ids'],list(values.index[:3]))
        self.assertTrue(all([p['period'] for p in s['points']]==['2023-01','2023-02','2023-03'] for s in run['result']['results'][1]['data']['series']))
        raw=json.loads(self.agent.store.attempts()[0]['message']['tool_calls'][0]['function']['arguments'])
        self.assertEqual(raw['statistic'],'p90')

    def test_selected_month_day_and_station_are_available_to_inspection_tool(self):
        view=self.session['view'];view.update(month='2018-12',detailObject='1141A',detailDay='2018-12-22',detailTab='hourly')
        context=normalized_context(self.data,view,'inspect_month',{})
        results,_=execute_tool(self.data,view,'inspect_month',{},context)
        obs=results[0]['data']['observations'];self.assertEqual(obs['station_id'],'1141A');self.assertEqual(obs['selected_day'],'2018-12-22')
        self.assertEqual(len(obs['points']),24);self.assertTrue(all(p['date']=='2018-12-22' for p in obs['points']))

    def test_cancel_queued_run_does_not_call_model(self):
        run=self.reserve();self.agent.cancel_run(run['run_id'],'cancel-queued-id')
        finished=self.agent.execute(run['run_id']);self.assertEqual(finished['status'],'cancelled');self.assertEqual(self.calls,[])

    def test_cancel_during_provider_stops_tools_and_does_not_publish(self):
        entered,release=threading.Event(),threading.Event();self.block=(entered,release)
        run=self.reserve();future=self.agent.pool.submit(self.agent.execute,run['run_id'])
        self.assertTrue(entered.wait(3));self.agent.cancel_run(run['run_id'],'cancel-active-id');release.set()
        finished=future.result(4);self.assertEqual(finished['status'],'cancelled')
        self.assertEqual(self.agent.store.session(self.session['session_id'])['state_revision'],0)
        self.assertEqual(len(self.calls),1);self.assertEqual(len(self.agent.store.attempts()),1)

    def test_manual_change_prevents_late_publication(self):
        entered,release=threading.Event(),threading.Event();self.block=(entered,release)
        run=self.reserve();future=self.agent.pool.submit(self.agent.execute,run['run_id']);self.assertTrue(entered.wait(3))
        view=self.session['view'];view['context']['statistic']='p90'
        self.agent.action(self.session['session_id'],ActionRequest(client_request_id='manual-during-run',expected_revision=0,view=view))
        release.set();finished=future.result(4)
        self.assertEqual(finished['status'],'superseded');self.assertEqual(self.agent.store.session(self.session['session_id'])['view']['context']['statistic'],'p90')

    def test_undo_and_dialogue_restore_after_manual_action(self):
        run=self.execute();view=run['result']['view'];changed={**view,'context':{**view['context'],'statistic':'p90'}}
        self.agent.action(self.session['session_id'],ActionRequest(client_request_id='change-statistic',expected_revision=1,view=changed))
        saved=self.agent.checked_session(self.session['session_id']);self.assertEqual(len(saved['dialogue']),1);self.assertIsNotNone(saved['dialogue'][0]['result'])
        undone=self.agent.action(self.session['session_id'],ActionRequest(client_request_id='undo-statistic',expected_revision=2,action='undo'))
        self.assertEqual(undone['view']['context']['statistic'],'mean');self.assertEqual(undone['last_result']['run_id'],run['run_id']);self.assertEqual(len(self.calls),2)

    def test_answer_failure_keeps_true_view_and_computed_fallback(self):
        with patch.object(self.agent.model,'answer',side_effect=QueryError(502,'ANSWER_INVALID','offline composition failure')):run=self.execute()
        self.assertEqual(run['status'],'completed');self.assertEqual(run['result']['answer']['source'],'computed_fallback')
        self.assertEqual(run['result']['view']['task'],'compare');self.assertEqual(len(run['result']['results'][0]['data']['rows']),12)

    def test_sse_reconnect_reads_existing_run_without_another_call(self):
        run=self.execute();count=len(self.calls)
        with TestClient(create_app(agent_service=self.agent)) as client:
            url=f'/api/v1/analysis/runs/{run["run_id"]}/events'
            first=client.get(url);last=self.agent.store.events(run['run_id'])[-1]['event_id']
            resumed=client.get(url,headers={'Last-Event-ID':str(last-1)})
            self.assertEqual(first.status_code,200);self.assertIn('text/event-stream',first.headers['content-type'])
            self.assertIn('event: snapshot',resumed.text);self.assertIn('completed',resumed.text)
        self.assertEqual(len(self.calls),count)

    def test_missing_day_breaks_episodes_and_zero_is_retained(self):
        frame=pd.DataFrame({'object_id':['shanghai']*7,'date':pd.date_range('2015-01-01',periods=7).strftime('%Y-%m-%d'),
            'pm25_ug_m3':[100,None,100,101,0,110,120],'status':['ok','missing','ok','ok','ok','ok','ok']})
        fixture=SimpleNamespace(city=frame,version='episode-fixture',manifest={'rule_version':'fixture'},metadata=lambda:{'stations':[]})
        result=WorkspaceService(fixture).execute({'dataset_version':fixture.version,'task':'episodes','context':{'start':'2015-01-01','end':'2015-01-07','threshold':75,'episode_min_days':2}})
        self.assertEqual([(e['start'],e['end']) for e in result['data']['episodes']],[('2015-01-03','2015-01-04'),('2015-01-06','2015-01-07')])
        self.assertEqual(result['data']['daily'][4]['value'],0);self.assertIsNone(result['data']['daily'][1]['value']);self.assertEqual(result['summary']['n'],6)


if __name__=='__main__':unittest.main()
