"""Bounded DeepSeek Search: external references, separate accounting, no numeric substitution."""
import time
from urllib.parse import urlsplit
import httpx
from api.config import configuration
from api.service import QueryError, invalid
from api.workspace import signature


class WebSearch:
    def __init__(self,store,transport=None,config_loader=configuration,maximum=None):
        self.store=store;self.transport=transport;self.config_loader=config_loader;self.maximum=maximum

    def status(self):
        cfg=self.config_loader()
        return {'default_enabled':True,'configured':cfg['ready'] and cfg['host']=='api.deepseek.com',
                'used_calls':len(self.store.search_attempts()),'max_calls':self.maximum,'provider':'DeepSeek Search'}

    def validate(self,run,arguments):
        if not run.get('web_search_enabled',True):invalid('本次问题已关闭网络搜索。')
        if set(arguments)-{'query','count'}:invalid('搜索参数包含未知字段。')
        query=arguments.get('query');count=arguments.get('count',3)
        if not isinstance(query,str) or not 1<=len(query.strip())<=128:invalid('搜索词需要在1—128个字符之间。')
        if not isinstance(count,int) or isinstance(count,bool) or not 1<=count<=5:invalid('每次搜索返回1—5条资料。')
        return {'query':query.strip(),'count':count,'need_content':True}

    def execute(self,run,arguments):
        body=self.validate(run,arguments);cfg=self.config_loader()
        if not cfg['ready'] or cfg['host']!='api.deepseek.com':
            raise QueryError(503,'SEARCH_NOT_CONFIGURED','联网搜索需要已有的 DeepSeek API 配置。')
        record,send=self.store.reserve_search(run['run_id'],signature(body),self.maximum,{'request':body,'provider_host':'api.deepseek.com'})
        if not send:return record['result']
        started=time.perf_counter()
        try:
            # Search is a fixed provider endpoint; no arbitrary URLs are fetched by this process.
            with httpx.Client(timeout=min(cfg['timeout'],30),transport=self.transport,follow_redirects=False) as client:
                response=client.post('https://api.deepseek.com/v1/tools/search',json=body,headers={'Authorization':'Bearer '+cfg['key']})
            record['http_status']=response.status_code
            if response.status_code!=200:raise QueryError(502,'SEARCH_HTTP_ERROR',f'搜索服务返回 HTTP {response.status_code}，不会自动重发。')
            values=response.json()['results']
            if not isinstance(values,list):raise ValueError('invalid results')
            sources=[]; evidence_sources=[]
            for item in values[:body['count']]:
                if not isinstance(item,dict):continue
                url=item.get('url','');parts=urlsplit(url)
                if parts.scheme not in ('https','http') or not parts.hostname or parts.username or parts.password:continue
                source={'title':str(item.get('title') or parts.hostname)[:300],'url':url[:8192],
                    'snippet':str(item.get('snippet') or item.get('summary') or '')[:700],
                    'date':item.get('date') if isinstance(item.get('date'),str) else None}
                sources.append(source)
                content=str(item.get('content') or '')
                evidence_sources.append({**source,'summary':str(item.get('summary') or '')[:1200],
                    'content_excerpt':content[:3500],'content_characters':len(content),
                    'content_truncated':len(content)>3500,'authority':item.get('authority')})
            result={'result_id':signature({'run_id':run['run_id'],'sources':evidence_sources}), 'query':body['query'],
                    'sources':sources,'evidence_sources':evidence_sources}
            record.update(status='completed',result=result)
            return result
        except httpx.TransportError as error:
            record.update(status='outcome_unknown',error_code='SEARCH_NETWORK_ERROR')
            raise QueryError(502,'SEARCH_NETWORK_ERROR','搜索连接未完成，已保留尝试记录，不会自动重发。') from error
        except QueryError as error:
            record.update(status='failed',error_code=error.code);raise
        except (ValueError,KeyError,TypeError) as error:
            record.update(status='invalid_response',error_code='SEARCH_RESPONSE_INVALID')
            raise QueryError(502,'SEARCH_RESPONSE_INVALID','搜索响应格式无效，当前图表保持原条件。') from error
        finally:
            record['elapsed_ms']=round((time.perf_counter()-started)*1000,1);self.store.finish_search(record)
