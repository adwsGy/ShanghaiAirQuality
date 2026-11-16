"""HTTP endpoints for the standalone air-quality workbench."""
from functools import lru_cache
from contextlib import asynccontextmanager
from pathlib import Path
import json,logging,os,uuid
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse,Response,FileResponse
from fastapi.staticfiles import StaticFiles
from api.service import Dataset,QueryError,ROOT

def create_app(data_directory=None,agent_service=None,agent_directory=None):
    owned_agents=[]

    @asynccontextmanager
    async def lifespan(app):
        try:yield
        finally:
            for owned in owned_agents:owned.close()

    app=FastAPI(title='上海 PM2.5 交互分析',version='1.0.0',lifespan=lifespan)
    directory=Path(data_directory or os.environ.get('SHANGHAI_DATA_DIR',ROOT/'data/processed'))

    @lru_cache(maxsize=1)
    def loaded(version):
        return Dataset(directory)

    def dataset():
        try:
            status=json.loads((directory/'build_status.json').read_text(encoding='utf-8'))
            if status['status']!='complete':raise ValueError('Dataset build incomplete')
            data=loaded(status['dataset_version'])
            if data.version!=status['dataset_version']:raise ValueError('Dataset version mismatch')
            return data
        except (OSError,ValueError,KeyError) as error:
            logging.getLogger(__name__).warning('Dataset not ready: %s',error)
            raise QueryError(503,'DATASET_NOT_READY','研究数据尚未就绪，请先完成数据构建与校验。') from error

    @lru_cache(maxsize=1)
    def agent():
        if agent_service is not None:return agent_service
        from api.agent.service import AgentService
        owned=AgentService(dataset,directory=agent_directory)
        owned_agents.append(owned)
        return owned

    from api.agent.router import add_routes
    add_routes(app,agent)

    def error_response(request,status,code,message,fields=None):
        request_id=getattr(request.state,'request_id',uuid.uuid4().hex[:12])
        return JSONResponse({'error':{'code':code,'message':message,'request_id':request_id,'fields':fields or []}},status_code=status)

    @app.middleware('http')
    async def request_id(request,call_next):
        request.state.request_id=uuid.uuid4().hex[:12]
        response=await call_next(request)
        response.headers['X-Request-ID']=request.state.request_id
        return response

    @app.exception_handler(QueryError)
    async def query_error(request,error):
        return error_response(request,error.status,error.code,error.message,error.fields)

    @app.exception_handler(RequestValidationError)
    async def body_error(request,error):
        return error_response(request,422,'INVALID_QUERY','请求必须包含有效的 JSON 对象。')

    @app.exception_handler(Exception)
    async def internal_error(request,error):
        logging.getLogger(__name__).exception('Unhandled API error %s',request.state.request_id)
        return error_response(request,500,'INTERNAL_ERROR','暂时无法处理请求，请重试并保留请求编号。')

    @app.get('/api/v1/metadata')
    def metadata():return dataset().metadata()

    @app.post('/api/v1/city/analyze')
    def analyze(payload:dict):return dataset().analyze(payload)[0]

    @app.post('/api/v1/city/detail')
    def detail(payload:dict):return dataset().detail(payload)[0]

    @app.post('/api/v1/workspace/query')
    def workspace(payload:dict):return dataset().workspace.execute(payload)

    @app.post('/api/v1/observations/summary')
    def observation_summary(payload:dict):return dataset().observation_service.summary(payload)

    @app.post('/api/v1/observations/catalog')
    def observation_catalog(payload:dict):return dataset().observation_service.catalog(payload)

    @app.post('/api/v1/observations/month')
    def observation_month(payload:dict):return dataset().observation_service.monthly(payload)

    @app.post('/api/v1/observations/export')
    def observation_export(payload:dict):
        body,result=dataset().observation_service.export(payload)
        return Response(body,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="shanghai-hourly-{result["month"]}-{result["station_id"]}.csv"','X-Dataset-Version':result['dataset_version'],'X-Context-ID':result['context_id']})

    @app.post('/api/v1/stations/compare')
    def compare(payload:dict):return dataset().station_service.compare(payload)[0]

    @app.post('/api/v1/stations/trends')
    def trends(payload:dict):return dataset().station_service.trends(payload)[0]

    @app.post('/api/v1/exports')
    def export(payload:dict):
        body,result=dataset().export(payload)
        return Response(body,media_type='text/csv; charset=utf-8',headers={
            'Content-Disposition':f'attachment; filename="shanghai-{payload["result_kind"]}-{result["context_id"]}.csv"',
            'X-Dataset-Version':result['dataset_version'],'X-Context-ID':result['context_id']})

    frontend=ROOT/'frontend/dist'
    if (frontend/'assets').is_dir():
        app.mount('/assets',StaticFiles(directory=frontend/'assets'),name='assets')
    if (frontend/'geometry').is_dir():
        app.mount('/geometry',StaticFiles(directory=frontend/'geometry'),name='geometry')

    @app.get('/',include_in_schema=False)
    def index():
        if not (frontend/'index.html').is_file():
            return JSONResponse({'message':'Run the frontend build first: cd frontend; npm run build'},status_code=503)
        return FileResponse(frontend/'index.html')

    return app

app=create_app()
