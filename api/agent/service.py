"""Analysis sessions keep business snapshots separate from graph checkpoints."""
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from langsmith import tracing_context
from api.service import QueryError, ROOT, invalid
from api.agent.graph import build_graph
from api.agent.model import Model
from api.agent.schemas import ActionRequest, AnalysisView, ClarificationRequest, RecoveryRequest, RunRequest, SessionRequest
from api.agent.store import Store
from api.agent.search import WebSearch


class AgentService:
    def __init__(self, dataset_loader, directory=None, model_factory=None, search_factory=None):
        self.dataset_loader = dataset_loader
        self.store = Store(directory or ROOT / 'data/runtime/agent')
        self.store.recover_interrupted()
        self.model = model_factory(self.store) if model_factory else Model(self.store)
        self.search=search_factory(self.store) if search_factory else WebSearch(self.store)
        self.saver_context = SqliteSaver.from_conn_string(str(self.store.directory / 'checkpoints.sqlite'))
        self.saver = self.saver_context.__enter__()
        self.graph = build_graph(self.store, self.model, dataset_loader, self.saver,self.search)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='air-analysis')
        self.session_locks = {}
        self._closed = False

    def close(self):
        if not self._closed:
            self.pool.shutdown(wait=True)
            self.saver_context.__exit__(None, None, None)
            self._closed = True

    def checked_session(self, session_id):
        self.store.normalize_session(session_id,lambda view:AnalysisView.model_validate(view).model_dump())
        session = self.store.session(session_id)
        if session['dataset_version'] != self.dataset_loader().version:
            raise QueryError(409, 'DATA_VERSION_CHANGED', '数据版本已更新，请建立新会话。')
        return session

    def validate_view(self, view, version):
        data = self.dataset_loader()
        data.workspace.validate({'dataset_version': version, 'task': view['task'], 'context': view['context']})
        if view['month'] is not None and (not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', view['month']) or not '2015-01' <= view['month'] <= '2025-12'):
            invalid('请选择研究范围内的月份。')
        if view['detailObject'] is not None and view['detailObject'] != 'shanghai' and view['detailObject'] not in data.workspace.catalog:
            invalid('未知的明细对象。')
        if view['detailDay'] is not None:
            from datetime import date
            try:date.fromisoformat(view['detailDay'])
            except ValueError:invalid('明细日期无效。')
            if not view['month'] or not view['detailDay'].startswith(view['month']+'-'):invalid('明细日期不在选中月份内。')

    def create_session(self, request: SessionRequest):
        view = request.view.model_dump()
        self.validate_view(view, request.dataset_version)
        return self.store.create_session(request.dataset_version, view)

    def action(self, session_id, request: ActionRequest):
        session = self.checked_session(session_id)
        if request.view is not None:
            self.validate_view(request.view.model_dump(), session['dataset_version'])
        return self.store.action(session_id, request.model_dump())

    def create_run(self, session_id, request: RunRequest):
        self.checked_session(session_id)
        run, created = self.store.reserve_run(session_id, request.model_dump())
        if created:
            self.pool.submit(self.execute, run['run_id'])
        return self.public_run(run)

    def resume_run(self,run_id,request:ClarificationRequest):
        run=self.store.run(run_id);self.checked_session(run['session_id'])
        run,created=self.store.resume(run_id,request.model_dump())
        if created:self.pool.submit(self.execute,run_id,request.choice)
        return self.public_run(run)

    def cancel_run(self,run_id,request_id):
        run=self.store.cancel(run_id,request_id)
        self.store.event(run_id,'cancelled' if run['status']=='cancelled' else 'progress',{'step':'已请求停止后续分析','status':run['status']})
        return self.public_run(run)

    def recover_run(self,run_id,request:RecoveryRequest):
        run=self.store.run(run_id);self.checked_session(run['session_id'])
        checkpoint=self.graph.get_state({'configurable':{'thread_id':run['session_id']}})
        if checkpoint.values.get('run',{}).get('run_id')!=run_id or not checkpoint.values.get('message',{}).get('tool_calls') or any(node in ('plan','load_context') for node in checkpoint.next):
            raise QueryError(409,'NO_SAVED_PLAN','没有可安全复用的已完成模型计划，不会自动重试模型请求。')
        run,created=self.store.recover_saved_plan(run_id,request.model_dump())
        if created:self.pool.submit(self.execute,run_id,None,True)
        return self.public_run(run)

    @staticmethod
    def public_run(run):
        return {key: run.get(key) for key in ['run_id', 'session_id', 'dataset_version', 'question', 'status', 'result', 'error', 'error_code', 'clarification', 'expected_revision','cancel_requested','resume_choice']}

    def execute(self, run_id, resume_choice=None, recover_saved=False):
        run = self.store.run(run_id)
        lock = self.session_locks.setdefault(run['session_id'], threading.Lock())
        with lock:
            run=self.store.run(run_id)
            if run['cancel_requested']:
                self.store.update_run(run_id,status='cancelled');self.store.event(run_id,'cancelled',{})
                return self.store.run(run_id)
            self.store.update_run(run_id, status='running')
            self.store.event(run_id, 'run_started', {})
            try:
                # Every invocation explicitly replaces prior per-run channels on the session thread.
                config={'configurable':{'thread_id':run['session_id']},'recursion_limit':14}
                if resume_choice is not None or recover_saved:
                    state=self.graph.get_state(config)
                    if state.values.get('run',{}).get('run_id')!=run_id:raise QueryError(409,'CHECKPOINT_CHANGED','会话已有后续分析，请基于当前条件重新提问。')
                    graph_input=None if recover_saved else Command(resume=resume_choice)
                else:
                    self.store.supersede_clarifications(run['session_id'],run_id)
                    graph_input={'run':run,'message':{},'plan':{},'plans':[],'groups':[],'context':{},'tool_result':{},'tool_results':[],
                                 'candidate':{},'clarification':{},'presentation':{},'tool_messages':[],'terminal':{},'external_result':{}}
                with tracing_context(enabled=False):
                    output=self.graph.invoke(graph_input,config)
                if output.get('__interrupt__'):
                    payload=output['__interrupt__'][0].value
                    self.store.update_run(run_id,status='clarification_required',clarification=payload)
                    self.store.remember_clarification(run_id,payload)
                    self.store.event(run_id,'clarification_required',payload)
            except QueryError as error:
                status = 'cancelled' if error.code == 'RUN_CANCELLED' else 'failed'
                self.store.update_run(run_id, status=status, error=error.message, error_code=error.code)
                self.store.event(run_id, 'cancelled' if status == 'cancelled' else 'error', {'code': error.code, 'message': error.message})
            except Exception:
                self.store.update_run(run_id, status='failed', error='分析执行失败，当前图表保持原条件；本次不会自动重试。', error_code='WORKFLOW_ERROR')
                self.store.event(run_id, 'error', {'code': 'WORKFLOW_ERROR'})
        return self.store.run(run_id)
