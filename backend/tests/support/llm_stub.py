"""Local deterministic OpenAI-compatible fixture for E2E and load-tool checks.

Never use its timings, token counts or scores as real model performance/accuracy.
Run: python -m tests.support.llm_stub --port 19090
"""
import argparse
import asyncio
import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from tests.support.factories import model_response

app = FastAPI()


@app.post('/chat/completions')
async def completion(request: Request):
    body = await request.json()
    messages = body.get('messages', [])
    system = next((row['content'] for row in messages if row['role'] == 'system'), '')
    prompt = '\n'.join(row['content'] for row in messages if row['role'] == 'user')
    if body.get('stream'):
        planned = re.search(r'<planned>(.*?)</planned>', system, re.S)
        text = planned[1] if planned else '你如何验证这个方案的结果，并说明尚未验证的边界？'
        async def stream():
            for chunk in (text[:8], text[8:]):
                await asyncio.sleep(0.1)
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': chunk}}]}, ensure_ascii=False) + '\n\n'
            yield 'data: [DONE]\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream')
    if body.get('max_tokens') == 1:
        result = 'OK'
    else:
        result = json.dumps(await model_response(system, prompt), ensure_ascii=False)
    return {'choices': [{'message': {'content': result}}]}


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=19090)
    args = parser.parse_args()
    uvicorn.run(app, host='127.0.0.1', port=args.port)
