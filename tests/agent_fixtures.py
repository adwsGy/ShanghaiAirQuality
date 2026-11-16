"""Provider-shaped offline answer from the evidence submitted to synthesis."""
import json
import httpx


def analysis_response(body):
    if 'tools' in body:return None
    payload=json.loads(body['messages'][-1]['content'])
    facts=payload['facts']
    content={'text':'根据本次查询，'+(facts[0]['text'] if facts else '外部资料仅供背景参考。'),
             'fact_ids':[facts[0]['id']] if facts else []}
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{
        'role':'assistant','content':json.dumps(content,ensure_ascii=False)}}]})
