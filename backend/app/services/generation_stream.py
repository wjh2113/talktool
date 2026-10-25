"""持久化模型正文增量；仅投影面向用户的字段，不显示 JSON、推理或内部记忆。"""
import asyncio
import contextvars
import json
import os
import time

from ..db import dumps, get_conn, now_str

_current = contextvars.ContextVar('generation_stream', default=None)
LABELS = {'headline': '锦囊要点', 'situation': '局势研判', 'their_concerns': '对方的顾虑',
          'best': '最好结果', 'acceptable': '可接受结果', 'bottom': '底线',
          'reply': '智囊回复', 'intro': '补充了解', 'q': '问题', 'why': '说法解析'}


def visible_node(key):
    return key.startswith('council.') or key in ('followup', 'roundtable', 'clarify', 'safety')


def preview(raw, node, names=None):
    """读完整和未闭合字符串，保留转义边界；不把半截 JSON 当作有效计划。"""
    if node == 'safety':
        return [{'id': 'reply', 'label': '智囊回复', 'text': raw}] if raw else []
    pos, values, blocks = 0, {}, []
    names = names or {}

    def whitespace():
        nonlocal pos
        while pos < len(raw) and raw[pos].isspace():
            pos += 1

    def string():
        nonlocal pos
        begin = pos
        pos += 1
        end = pos
        closed = False
        while pos < len(raw):
            char = raw[pos]
            if char == '"':
                end = pos
                pos += 1
                closed = True
                break
            if char == '\\':
                if pos + 1 >= len(raw):
                    break
                size = 6 if raw[pos + 1] == 'u' else 2
                if pos + size > len(raw):
                    break
                pos += size
            else:
                pos += 1
            end = pos
        try:
            text = json.loads(raw[begin:end] + '"')
            # 截在 UTF-16 高代理项时，等待后面的低代理项，而不是写入无效 Unicode。
            if text and 0xD800 <= ord(text[-1]) <= 0xDBFF:
                text = text[:-1]
            text = text.encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')
        except (ValueError, UnicodeError):
            text = ''
        return text, closed

    def collect(path, text):
        values[path] = text
        p = path[1:] if path[:1] == ('plan',) else path
        label = None
        if len(p) == 1 and p[0] in ('headline', 'situation', 'their_concerns', 'reply', 'intro'):
            label = LABELS[p[0]]
        elif len(p) == 2 and p[0] == 'goal' and p[1] in LABELS:
            label = LABELS[p[1]]
        elif len(p) == 3 and isinstance(p[1], int):
            group, index, field = p
            if group == 'strategies' and field == 'use': label = f'谋略 {index + 1}'
            elif group == 'actions' and field == 'text': label = f'行动 {index + 1}'
            elif group == 'lines' and field == 'text': label = f'话术 {index + 1}'
            elif group == 'risks' and field in ('if', 'then'): label = '如果…' if field == 'if' else '应对方式'
            elif group in ('advisor_views', 'speeches') and field in ('view', 'text'):
                who = values.get(path[:-1] + ('advisor',), '')
                label = names.get(who, '谋士观点')
            elif group == 'questions' and field == 'q': label = f'问题 {index + 1}'
        elif len(p) == 2 and p[0] == 'donts': label = '避免这样做'
        elif len(p) == 2 and p[0] == 'verdict' and p[1] in ('text', 'watch'):
            label = '军师裁决' if p[1] == 'text' else '需要留意'
        elif len(p) == 3 and p[:2] == ('verdict', 'adopt'): label = '采纳建议'
        if text and label:
            blocks.append({'id': '/'.join(map(str, path)), 'label': label, 'text': text})

    def value(path, depth=0):
        nonlocal pos
        if depth > 25:
            pos = len(raw)
            return False
        whitespace()
        if pos >= len(raw): return False
        char = raw[pos]
        if char == '"':
            text, closed = string()
            collect(path, text)
            return closed
        if char == '{':
            pos += 1
            while pos < len(raw):
                whitespace()
                if pos >= len(raw): return False
                if raw[pos] == '}': pos += 1; return True
                if raw[pos] != '"': return False
                key, closed = string()
                if not closed: return False
                whitespace()
                if pos >= len(raw) or raw[pos] != ':': return False
                pos += 1
                if not value(path + (key,), depth + 1): return False
                whitespace()
                if pos < len(raw) and raw[pos] == ',': pos += 1
                elif pos >= len(raw) or raw[pos] != '}': return False
            return False
        if char == '[':
            pos += 1
            index = 0
            while pos < len(raw):
                whitespace()
                if pos >= len(raw): return False
                if raw[pos] == ']': pos += 1; return True
                if not value(path + (index,), depth + 1): return False
                index += 1
                whitespace()
                if pos < len(raw) and raw[pos] == ',': pos += 1
                elif pos >= len(raw) or raw[pos] != ']': return False
            return False
        start = pos
        while pos < len(raw) and raw[pos] not in ',]} \r\n\t': pos += 1
        return pos > start and pos < len(raw)

    # 兼容模型在 JSON 外包一层 Markdown 围栏。
    if raw.lstrip().startswith('```'):
        pos = raw.find('{')
        if pos < 0: return []
    value(())
    return blocks


class Capture:
    def __init__(self, job_id):
        self.job_id = job_id
        self.raw, self.pending, self.node = '', '', ''
        self.attempt = 0
        self.last_flush = 0
        with get_conn() as c:
            self.names = {r[0]: r[1] for r in c.execute('SELECT code,name FROM advisor WHERE owner_id IS NULL OR owner_id=(SELECT user_id FROM generation_job WHERE id=?)', (job_id,))}

    def __enter__(self):
        self.token = _current.set(self)
        return self

    def __exit__(self, *_):
        _current.reset(self.token)

    def _write(self, kind, delta, blocks):
        with get_conn() as c:
            c.execute('INSERT INTO generation_event(job_id,node,attempt,kind,delta,blocks,created_at) VALUES (?,?,?,?,?,?,?)',
                      (self.job_id, self.node, self.attempt, kind, delta, dumps(blocks), now_str()))

    def begin(self, node, attempt):
        self.raw, self.pending, self.node = '', '', node
        self.attempt = attempt
        self.last_flush = 0
        self._write('reset', '', [])

    def feed(self, delta, force=False):
        if len(self.raw) + len(delta) > 128000:
            raise ValueError('模型输出过长，已停止接收')
        self.raw += delta
        self.pending += delta
        if self.pending and (force or time.monotonic() - self.last_flush >= 0.08 or len(self.pending) >= 512):
            self._write('update', self.pending, preview(self.raw, self.node, self.names))
            self.pending = ''
            self.last_flush = time.monotonic()


def capture_for(key):
    return _current.get() if visible_node(key) else None


async def mock(key, data):
    sink = capture_for(key)
    if not sink: return
    sink.begin(key, 0)
    raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    for offset in range(0, len(raw), 48):
        sink.feed(raw[offset:offset + 48])
        await asyncio.sleep(float(os.getenv('MOCK_STREAM_DELAY', '0.02')))
    sink.feed('', force=True)
