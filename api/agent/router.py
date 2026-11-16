"""HTTP entry points; polling and direct actions share confirmed session state."""
import asyncio
import json
from fastapi import Request, Query
from fastapi.responses import StreamingResponse
from api.agent.schemas import ActionRequest, CancelRequest, ClarificationRequest, RecoveryRequest, RunRequest, SessionRequest


def add_routes(app, service):
    @app.get('/api/v1/analysis/status')
    def status():
        agent=service()
        return {**agent.model.status(),'web_search':agent.search.status()}

    @app.post('/api/v1/analysis/sessions')
    def create_session(payload: SessionRequest):
        return service().create_session(payload)

    @app.get('/api/v1/analysis/sessions/{session_id}')
    def get_session(session_id: str):
        return service().checked_session(session_id)

    @app.post('/api/v1/analysis/sessions/{session_id}/actions')
    def action(session_id: str, payload: ActionRequest):
        return service().action(session_id, payload)

    @app.post('/api/v1/analysis/sessions/{session_id}/runs')
    def create_run(session_id: str, payload: RunRequest):
        return service().create_run(session_id, payload)

    @app.get('/api/v1/analysis/runs/{run_id}')
    def get_run(run_id: str):
        agent = service()
        return {**agent.public_run(agent.store.run(run_id)), 'events': agent.store.events(run_id)}


    @app.post('/api/v1/analysis/runs/{run_id}/resume')
    def resume_run(run_id:str,payload:ClarificationRequest):
        return service().resume_run(run_id,payload)

    @app.post('/api/v1/analysis/runs/{run_id}/cancel')
    def cancel_run(run_id:str,payload:CancelRequest):
        return service().cancel_run(run_id,payload.client_request_id)

    @app.post('/api/v1/analysis/runs/{run_id}/recover')
    def recover_run(run_id:str,payload:RecoveryRequest):
        return service().recover_run(run_id,payload)

    @app.get('/api/v1/analysis/runs/{run_id}/events')
    async def events(run_id:str,request:Request,after:int=Query(default=0,ge=0,le=1000000)):
        agent=service();agent.store.run(run_id)
        try:cursor=max(after,int(request.headers.get('last-event-id','0')))
        except ValueError:cursor=after
        def frame(event,data,identifier=None):
            return (f'id: {identifier}\n' if identifier is not None else '')+f'event: {event}\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'
        async def stream():
            nonlocal cursor
            existing=agent.store.events(run_id)
            run=agent.public_run(agent.store.run(run_id))
            last=existing[-1]['event_id'] if existing else 0
            yield frame('snapshot',{'run':{**run,'events':existing},'last_event_id':last})
            cursor=min(cursor,last)
            ticks=0
            while True:
                if await request.is_disconnected():return
                for event in agent.store.events(run_id,cursor):
                    cursor=event['event_id'];yield frame(event['event'],event,cursor)
                run=agent.store.run(run_id)
                if run['status'] not in ('queued','running','cancelling'):
                    yield frame('snapshot',{'run':agent.public_run(run),'last_event_id':cursor})
                    return
                ticks+=1
                if ticks%20==0:yield ': keep-alive\n\n'
                await asyncio.sleep(.15)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
