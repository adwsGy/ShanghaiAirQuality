"""Transactional business history, idempotent requests and model-attempt accounting."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid
from api.service import QueryError
from api.workspace import signature


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'analysis.sqlite'
        with self.db() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(session_id, request_id));
                CREATE TABLE IF NOT EXISTS actions (session_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(session_id, request_id));
                CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    phase TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(run_id, phase));
                CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, seq INTEGER NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(run_id, seq));
                CREATE TABLE IF NOT EXISTS search_calls (run_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS run_actions (run_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, PRIMARY KEY(run_id, request_id));
            ''')

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                yield conn

    def _session(self, conn, session_id):
        row = conn.execute('SELECT body FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise QueryError(404, 'SESSION_NOT_FOUND', '分析会话不存在，请新建会话。')
        return json.loads(row['body'])

    def _write_session(self, conn, session):
        conn.execute('UPDATE sessions SET body=? WHERE id=?', (encode(session), session['session_id']))

    def create_session(self, dataset_version, view):
        session = {'session_id': uuid.uuid4().hex, 'dataset_version': dataset_version,
                   'state_revision': 0, 'view': view, 'history': [], 'messages': [],
                   'last_result': None, 'created_at': now()}
        with self.db() as conn:
            conn.execute('INSERT INTO sessions VALUES (?,?)', (session['session_id'], encode(session)))
        return session

    def session(self, session_id):
        with self.db() as conn:
            session=self._session(conn, session_id)
            rows=conn.execute('SELECT body FROM runs WHERE session_id=? ORDER BY rowid DESC LIMIT 12',(session_id,)).fetchall()
            dialogue=[]
            for row in reversed(rows):
                run=json.loads(row[0]);result=run.get('result')
                compact={key:result[key] for key in ['session_id','run_id','dataset_version','state_revision','context','result_refs','view_spec','facts','answer','view'] if key in result} if result else None
                dialogue.append({'run_id':run['run_id'],'question':run['question'],'status':run['status'],'result':compact,'error':run.get('error'),'clarification':run.get('clarification')})
            session['dialogue']=dialogue
            return session

    def normalize_session(self, session_id, normalizer):
        with self.db() as conn:
            session=self._session(conn,session_id)
            session['view']=normalizer(session['view'])
            for h in session['history']:h['view']=normalizer(h['view'])
            self._write_session(conn,session)

    def recover_interrupted(self):
        with self.db() as conn:
            for row in conn.execute('SELECT id,body FROM runs').fetchall():
                run=json.loads(row['body'])
                if run['status'] in ('queued','running','cancelling'):
                    run.update(status='interrupted',error='服务在上次分析期间重启；保留已登记的尝试，不会自动重新请求模型。',error_code='SERVICE_RESTARTED')
                    conn.execute('UPDATE runs SET body=? WHERE id=?',(encode(run),row['id']))
            for row in conn.execute('SELECT id,body FROM attempts').fetchall():
                attempt=json.loads(row['body'])
                if attempt['status']=='reserved':
                    attempt.update(status='outcome_unknown',error_code='SERVICE_RESTARTED')
                    conn.execute('UPDATE attempts SET body=? WHERE id=?',(encode(attempt),row['id']))

    @staticmethod
    def revision(session, expected):
        if session['state_revision'] != expected:
            raise QueryError(409, 'STATE_CONFLICT', '分析条件已变化，请同步当前会话后再操作。')

    def action(self, session_id, request):
        fingerprint = signature(request)
        with self.db() as conn:
            previous = conn.execute('SELECT * FROM actions WHERE session_id=? AND request_id=?', (session_id, request['client_request_id'])).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise QueryError(409, 'REQUEST_ID_REUSED', '请求标识已用于其他操作。')
                return json.loads(previous['body'])
            session = self._session(conn, session_id)
            self.revision(session, request['expected_revision'])
            if request['action'] == 'undo':
                if session['history']:
                    old = session['history'].pop()
                    session.update(view=old['view'], last_result=old['last_result'])
            else:
                session['history'] = (session['history'] + [{'view': session['view'], 'last_result': session['last_result']}])[-40:]
                session.update(view=request['view'], last_result=None)
            session['state_revision'] += 1
            self._write_session(conn, session)
            conn.execute('INSERT INTO actions VALUES (?,?,?,?)', (session_id, request['client_request_id'], fingerprint, encode(session)))
            return session

    def reserve_run(self, session_id, request):
        fingerprint = signature(request)
        with self.db() as conn:
            previous = conn.execute('SELECT * FROM runs WHERE session_id=? AND request_id=?', (session_id, request['client_request_id'])).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise QueryError(409, 'REQUEST_ID_REUSED', '请求标识已用于其他问题。')
                return json.loads(previous['body']), False
            session = self._session(conn, session_id)
            self.revision(session, request['expected_revision'])
            run = {'run_id': uuid.uuid4().hex, 'session_id': session_id, 'question': request['question'],
                   'web_search_enabled': request.get('web_search_enabled',True),
                   'expected_revision': request['expected_revision'], 'dataset_version': session['dataset_version'],
                   'view': session['view'], 'messages': session['messages'][-12:], 'status': 'queued',
                   'created_at': now(), 'cancel_requested': False, 'result': None, 'error': None}
            last=session.get('last_result')
            run['recent_analysis']=None if not last else {'context':last['context'],'title':last['view_spec']['title'],
                'queries':[{'task':r['task'],'context':r['context'],'summary':r['summary']} for r in last.get('results',[])]}
            conn.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (run['run_id'], session_id, request['client_request_id'], fingerprint, encode(run)))
            return run, True

    def supersede_clarifications(self, session_id, except_run):
        with self.db() as conn:
            for row in conn.execute('SELECT id,body FROM runs WHERE session_id=? AND id<>?',(session_id,except_run)).fetchall():
                run=json.loads(row['body'])
                if run['status']=='clarification_required':
                    run.update(status='superseded',cancel_requested=True,error='该澄清已被后续问题替代。')
                    conn.execute('UPDATE runs SET body=? WHERE id=?',(encode(run),row['id']))

    def remember_clarification(self,run_id,payload):
        with self.db() as conn:
            run=json.loads(conn.execute('SELECT body FROM runs WHERE id=?',(run_id,)).fetchone()[0])
            session=self._session(conn,run['session_id']);known=session.get('clarified_runs',[])
            if run_id not in known:
                session['messages']=(session['messages']+[{'role':'user','content':run['question']},{'role':'assistant','content':payload['question']}])[-12:]
                session['clarified_runs']=(known+[run_id])[-12:]
                self._write_session(conn,session)

    def resume(self, run_id, request):
        fingerprint=signature({'action':'resume',**request})
        with self.db() as conn:
            row=conn.execute('SELECT body FROM runs WHERE id=?',(run_id,)).fetchone()
            if row is None:raise QueryError(404,'RUN_NOT_FOUND','分析运行不存在。')
            run=json.loads(row[0]);previous=conn.execute('SELECT fingerprint FROM run_actions WHERE run_id=? AND request_id=?',(run_id,request['client_request_id'])).fetchone()
            if previous:
                if previous[0]!=fingerprint:raise QueryError(409,'REQUEST_ID_REUSED','请求标识已用于其他操作。')
                return run,False
            if run['status']!='clarification_required' or run.get('clarification',{}).get('kind')!='winter':raise QueryError(409,'RUN_NOT_WAITING','本次分析没有待选择的冬季定义。')
            self.revision(self._session(conn,run['session_id']),request['expected_revision'])
            if request['expected_revision']!=run['expected_revision']:raise QueryError(409,'STATE_CONFLICT','分析条件已改变，请基于当前条件重新提问。')
            run.update(status='queued',resume_choice=request['choice'])
            conn.execute('UPDATE runs SET body=? WHERE id=?',(encode(run),run_id))
            conn.execute('INSERT INTO run_actions VALUES (?,?,?)',(run_id,request['client_request_id'],fingerprint))
            return run,True

    def cancel(self, run_id, request_id):
        fingerprint=signature({'action':'cancel'})
        with self.db() as conn:
            row=conn.execute('SELECT body FROM runs WHERE id=?',(run_id,)).fetchone()
            if row is None:raise QueryError(404,'RUN_NOT_FOUND','分析运行不存在。')
            run=json.loads(row[0]);previous=conn.execute('SELECT fingerprint FROM run_actions WHERE run_id=? AND request_id=?',(run_id,request_id)).fetchone()
            if previous and previous[0]!=fingerprint:raise QueryError(409,'REQUEST_ID_REUSED','请求标识已用于其他操作。')
            if not previous:conn.execute('INSERT INTO run_actions VALUES (?,?,?)',(run_id,request_id,fingerprint))
            if run['status'] in ('queued','running','cancelling','clarification_required'):
                run['cancel_requested']=True
                run['status']='cancelling' if run['status'] in ('running','cancelling') else 'cancelled'
                run['error']='已取消后续分析；已发送的模型请求仍保留记账。'
                conn.execute('UPDATE runs SET body=? WHERE id=?',(encode(run),run_id))
            return run

    def recover_saved_plan(self,run_id,request):
        fingerprint=signature({'action':'recover_saved_plan',**request})
        with self.db() as conn:
            row=conn.execute('SELECT body FROM runs WHERE id=?',(run_id,)).fetchone()
            if row is None:raise QueryError(404,'RUN_NOT_FOUND','分析运行不存在。')
            run=json.loads(row[0]);previous=conn.execute('SELECT fingerprint FROM run_actions WHERE run_id=? AND request_id=?',(run_id,request['client_request_id'])).fetchone()
            if previous:
                if previous[0]!=fingerprint:raise QueryError(409,'REQUEST_ID_REUSED','请求标识已用于其他操作。')
                return run,False
            if run['status']!='failed':raise QueryError(409,'RUN_NOT_FAILED','该运行不需要重新校验。')
            self.revision(self._session(conn,run['session_id']),request['expected_revision'])
            if run['expected_revision']!=request['expected_revision']:raise QueryError(409,'STATE_CONFLICT','条件已变化，请基于当前选择重新提问。')
            run.update(status='queued',error=None,error_code=None,recovered_saved_plan=True)
            conn.execute('UPDATE runs SET body=? WHERE id=?',(encode(run),run_id))
            conn.execute('INSERT INTO run_actions VALUES (?,?,?)',(run_id,request['client_request_id'],fingerprint))
            return run,True

    def run(self, run_id):
        with self.db() as conn:
            row = conn.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None:
                raise QueryError(404, 'RUN_NOT_FOUND', '分析运行不存在。')
            return json.loads(row['body'])

    def update_run(self, run_id, **patch):
        with self.db() as conn:
            row = conn.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
            run = json.loads(row['body'])
            run.update(patch)
            conn.execute('UPDATE runs SET body=? WHERE id=?', (encode(run), run_id))
            return run

    def event(self, run_id, event, data):
        with self.db() as conn:
            row = conn.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
            run = json.loads(row['body'])
            seq = conn.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?', (run_id,)).fetchone()[0]
            body = {'event_id': seq, 'run_id': run_id, 'event': event,
                    'state_revision': data.get('state_revision',run['expected_revision']), 'data': data}
            conn.execute('INSERT INTO events VALUES (?,?,?)', (run_id, seq, encode(body)))
            return body

    def events(self, run_id, after=0):
        with self.db() as conn:
            return [json.loads(r[0]) for r in conn.execute('SELECT body FROM events WHERE run_id=? AND seq>? ORDER BY seq', (run_id, after))]

    def publish(self, run_id, bundle):
        with self.db() as conn:
            run = json.loads(conn.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()[0])
            if run['status']=='completed' and run.get('result') is not None:return run
            session = self._session(conn, run['session_id'])
            if run['cancel_requested']:
                run.update(status='cancelled', result=None)
            elif session['state_revision'] != run['expected_revision']:
                run.update(status='superseded', result=None, error='运行期间条件已变化，候选结果未覆盖当前图表。')
            else:
                session['history'] = (session['history'] + [{'view': session['view'], 'last_result': session['last_result']}])[-40:]
                session['state_revision'] += 1
                bundle['state_revision'] = session['state_revision']
                session.update(view=bundle['view'], last_result=bundle)
                session['messages'] = (session['messages'] + [{'role': 'user', 'content': run['question']}, {'role': 'assistant', 'content': bundle['answer']['text']}])[-12:]
                self._write_session(conn, session)
                run.update(status='completed', result=bundle)
            conn.execute('UPDATE runs SET body=? WHERE id=?', (encode(run), run_id))
            return run

    def attempt(self, run_id, phase, request_fingerprint, max_calls, metadata):
        with self.db() as conn:
            previous = conn.execute('SELECT * FROM attempts WHERE run_id=? AND phase=?', (run_id, phase)).fetchone()
            if previous:
                record = json.loads(previous['body'])
                if record['fingerprint'] != request_fingerprint:
                    raise QueryError(409, 'MODEL_REQUEST_CHANGED', '已有模型尝试与当前请求不一致，不会重复发送。')
                if record['status'] == 'completed':
                    return record, False
                raise QueryError(409, 'MODEL_OUTCOME_UNKNOWN', '该步骤已有一次模型尝试，结果未确定，不会自动重试。')
            used = conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
            if max_calls is not None and used >= max_calls:
                raise QueryError(429, 'AGENT_BUDGET_REACHED', '本次测试的模型预算已用完。')
            record = {'attempt_id': uuid.uuid4().hex, 'run_id': run_id, 'phase': phase,
                      'fingerprint': request_fingerprint, 'status': 'reserved', 'reserved_at': now(), **metadata}
            conn.execute('INSERT INTO attempts VALUES (?,?,?,?,?)', (record['attempt_id'], run_id, phase, request_fingerprint, encode(record)))
            return record, True

    def finish_attempt(self, record):
        with self.db() as conn:
            conn.execute('UPDATE attempts SET body=? WHERE id=?', (encode(record), record['attempt_id']))

    def attempts(self):
        with self.db() as conn:
            return [json.loads(row[0]) for row in conn.execute('SELECT body FROM attempts ORDER BY rowid')]

    def search_attempts(self):
        with self.db() as conn:
            return [json.loads(row[0]) for row in conn.execute('SELECT body FROM search_calls ORDER BY rowid')]

    def reserve_search(self,run_id,fingerprint,maximum,metadata):
        with self.db() as conn:
            previous=conn.execute('SELECT body FROM search_calls WHERE run_id=?',(run_id,)).fetchone()
            if previous:
                record=json.loads(previous[0])
                if record['fingerprint']!=fingerprint:raise QueryError(409,'SEARCH_REQUEST_CHANGED','已有搜索条件不同，不会重复请求。')
                if record['status']=='completed':return record,False
                raise QueryError(409,'SEARCH_OUTCOME_UNKNOWN','该分析已有搜索尝试，不会自动重发。')
            if maximum is not None and conn.execute('SELECT COUNT(*) FROM search_calls').fetchone()[0]>=maximum:
                raise QueryError(429,'SEARCH_BUDGET_REACHED','本次测试的搜索预算已用完。')
            record={'run_id':run_id,'fingerprint':fingerprint,'status':'reserved','reserved_at':now(),**metadata}
            conn.execute('INSERT INTO search_calls VALUES (?,?)',(run_id,encode(record)))
            return record,True

    def finish_search(self,record):
        with self.db() as conn:conn.execute('UPDATE search_calls SET body=? WHERE run_id=?',(encode(record),record['run_id']))
