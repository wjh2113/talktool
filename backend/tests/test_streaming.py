"""流式正文、字段投影、持久化续读与失败草稿回归。"""
import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(), GATEWAY_API_KEY='', MOCK_MODE='true')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx
from app import db, config
from app.services import consult, jobs, gateway, generation_stream as gs, sessions, my_advisors
from app.services.sessions import NotFound


def test_projection():
    # 每一个字符边界都能投影，不将 Unicode 半个转义或代理项写入 SQLite。
    data = {'headline': '先核实“情况”😀', 'actions': [{'text': '先听\n再说'}], 'summary': '内部记忆不展示'}
    raw = json.dumps(data, ensure_ascii=True)
    for end in range(len(raw) + 1):
        blocks = gs.preview(raw[:end], 'council.upward')
        json.dumps(blocks, ensure_ascii=False).encode('utf-8')
        assert all('内部记忆' not in b['text'] for b in blocks)
    blocks = gs.preview(raw, 'council.upward')
    assert [b['text'] for b in blocks] == [data['headline'], '先听\n再说']
    partial = gs.preview('{"headline":"逐字显示', 'council.upward')
    assert partial == [{'id': 'headline', 'label': '锦囊要点', 'text': '逐字显示'}]
    assert gs.preview('{"reply":"先稳住","plan":{"headline":"再推进', 'followup')[-1]['text'] == '再推进'
    assert not gs.preview('{"reasoning_content":"hidden"}', 'roundtable')
    assert gs.preview('{"speeches":[{"advisor":"a","text":"不同意见"}]}', 'roundtable', {'a': '谋士甲'})[0]['label'] == '谋士甲'
    assert gs.preview('```json\n{"headline":"围栏兼容"}', 'council.general')[0]['text'] == '围栏兼容'


class Chunks(httpx.AsyncByteStream):
    def __init__(self, text, pause=None, missing_done=False, error=False):
        self.text, self.pause, self.missing_done, self.error = text, pause, missing_done, error

    async def __aiter__(self):
        # 首段已包含未闭合的 headline，网关随后仍在生成。
        split = self.text.index('先核实') + len('先核实')
        for i, part in enumerate((self.text[:split], self.text[split:])):
            frame = ('data: ' + json.dumps({'choices': [{'delta': {'content': part, 'reasoning_content': '不要展示推理'}}]}, ensure_ascii=False) + '\r\n\r\n').encode()
            for start in range(0, len(frame), 7):
                yield frame[start:start + 7]
            if i == 0 and self.pause:
                await self.pause.wait()
        if self.error:
            yield b'data: {"error":"provider failed"}\n\n'
        elif not self.missing_done:
            yield b'data: {"gateway":{"requestId":"test"}}\n\ndata: [DONE]\n\n'


async def main():
    test_projection()
    db.init_db()
    c = await consult.create('u1', '王总总在会上否定我的方案，我想争取下季度的项目负责人')
    cid = c['id']
    job = jobs.submit('u1', 'stream-plan-first', 'plan', cid)
    private = my_advisors.create('u2', {'name': '其他账号谋士', 'persona': '这是只属于另一个账号的私人谋士'})
    assert private['code'] not in gs.Capture(job['id']).names

    raw = json.dumps({'headline': '先核实情况，再私下沟通', 'actions': [{'text': '约一次私下沟通', 'when': '今天'}]}, ensure_ascii=False)
    resume = asyncio.Event()
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body['stream'] is True and body['thinking']['type'] == 'disabled'
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, stream=Chunks(raw, resume))

    config.MOCK = False
    # 后台记忆另行测试，不额外调用网关。
    async def remember(*a, **kw): pass
    with patch.object(gateway, '_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))), patch.object(consult, '_remember', remember):
        task = asyncio.create_task(jobs.execute(job['id']))
        for _ in range(100):
            batch = jobs.events('u1', job['id'])
            if any(e['blocks'] for e in batch['events']): break
            await asyncio.sleep(0.01)
        assert jobs.get('u1', job['id'])['status'] == 'running'
        assert batch['events'][-1]['blocks'][0]['text'] == '先核实'
        assert consult.get_detail('u1', cid)['plan'] is None
        cursor = batch['cursor']
        # 新读取方从头恢复同一份已保存的草稿，游标重复读取不再产生内容。
        assert jobs.events('u1', job['id'])['events'] == batch['events']
        assert jobs.events('u1', job['id'], cursor)['events'] == []
        try: jobs.events('u2', job['id'])
        except NotFound: pass
        else: raise AssertionError('必须隔离不同账号的草稿')
        resume.set()
        await task
    final = jobs.events('u1', job['id'], cursor)
    assert final['terminal'] and final['status'] == 'done'
    assert consult.get_detail('u1', cid)['plan']['content']['headline'] == '先核实情况，再私下沟通'
    assert len(requests) == 1
    with db.get_conn() as conn:
        persisted = ''.join(r[0] for r in conn.execute('SELECT delta FROM generation_event WHERE job_id=? ORDER BY id', (job['id'],)))
        assert persisted == raw

    # 上游传了正文后报错：任务失败，草稿保留，不能提交成正式计划或自动再调用一次。
    failed = jobs.submit('u1', 'stream-plan-failed', 'plan', cid)
    async def bad(request):
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, stream=Chunks(raw, error=True))
    with patch.object(gateway, '_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(bad))):
        await jobs.execute(failed['id'])
    batch = jobs.events('u1', failed['id'])
    assert batch['status'] == 'failed' and batch['events'][-1]['blocks']
    assert consult.get_detail('u1', cid)['plan']['version'] == 1

    # 无 [DONE] 的提前 EOF 也必须报错。
    async def truncated(request):
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, stream=Chunks(raw, missing_done=True))
    with patch.object(gateway, '_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(truncated))):
        try:
            async for _ in gateway.stream_chat([]): pass
        except gateway.GatewayError: pass
        else: raise AssertionError('中断流不能误报完成')

    # 真正执行一次 JSON 截断重试，失败草稿和重试草稿使用不同代次。
    retry = jobs.submit('u1', 'stream-json-retry', 'plan', cid)
    calls = []
    async def retry_handler(request):
        calls.append(json.loads(request.content))
        text = '{"headline":"先核实' if len(calls) == 1 else raw
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, stream=Chunks(text))
    with patch.object(gateway, '_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(retry_handler))), patch.object(consult, '_remember', remember):
        await jobs.execute(retry['id'])
    assert jobs.get('u1', retry['id'])['status'] == 'done'
    assert len(calls) == 2 and calls[0]['idempotencyKey'] != calls[1]['idempotencyKey']
    replay = jobs.events('u1', retry['id'])['events']
    assert [(r['kind'], r['attempt']) for r in replay if r['kind'] == 'reset'] == [('reset', 0), ('reset', 1)]
    assert consult.get_detail('u1', cid)['plan']['version'] == 2

    # JSON 校验重试前写 reset；客户端不会拼接新旧两份草稿。
    reset = jobs.submit('u1', 'stream-reset-test', 'plan', cid)
    with gs.Capture(reset['id']) as capture:
        capture.begin('council.upward', 0)
        capture.feed('{"headline":"旧草稿', force=True)
        capture.begin('council.upward', 1)
        capture.feed('{"headline":"新草稿"}', force=True)
    rows = jobs.events('u1', reset['id'])['events']
    assert [r['kind'] for r in rows] == ['reset', 'update', 'reset', 'update']
    assert rows[-1]['blocks'][0]['text'] == '新草稿'
    with db.get_conn() as conn:
        conn.execute("UPDATE generation_job SET status='running' WHERE id=?", (reset['id'],))
    jobs.recover()
    recovered = jobs.events('u1', reset['id'])
    assert recovered['terminal'] and recovered['status'] == 'failed'
    assert recovered['events'][-1]['blocks'][0]['text'] == '新草稿'
    # 长回答超过单批 100 个事件时，终态也必须先读完所有剩余事件。
    with db.get_conn() as conn:
        conn.executemany("INSERT INTO generation_event(job_id,node,attempt,kind,delta,blocks,created_at) VALUES (?,?,0,'update','',?,?)",
                         [(reset['id'], 'council.upward', '[]', db.now_str()) for _ in range(205)])
    cursor, total = 0, 0
    while True:
        page = jobs.events('u1', reset['id'], cursor)
        total += len(page['events'])
        assert page['cursor'] > cursor
        cursor = page['cursor']
        if page['terminal']: break
    assert total == 209
    assert jobs.events('u1', reset['id'], cursor)['events'] == []


    await sessions.drain_tasks()
    print('ALL STREAMING TESTS PASSED')


if __name__ == '__main__':
    asyncio.run(main())
