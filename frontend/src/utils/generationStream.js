import { API_BASE, getToken, request, goLogin } from './request'

/** 浏览器使用鉴权 SSE；其他端与不支持流读取的浏览器使用带游标的长轮询。 */
export function followGeneration(jobId, callbacks, startCursor = 0) {
  let cursor = startCursor
  let stopped = false
  let controller = null
  const base = `/api/advisor/jobs/${encodeURIComponent(jobId)}`

  function accept(event) {
    if (stopped || !Number.isSafeInteger(event.id) || event.id <= cursor) return
    cursor = event.id
    callbacks.onUpdate(event, cursor)
  }

  async function poll() {
    const batch = await request(`${base}/events?after=${cursor}&wait=10000`, { silent: true, timeout: 15000 })
    if (stopped) return false
    for (const event of batch.events) accept(event)
    if (batch.terminal) {
      callbacks.onTerminal(batch.status)
      return true
    }
    return false
  }

  async function sse() {
    // #ifdef H5
    controller = new AbortController()
    const response = await fetch(`${API_BASE}${base}/stream?after=${cursor}`, {
      headers: { Authorization: 'Bearer ' + getToken(), Accept: 'text/event-stream' }, signal: controller.signal
    })
    if (!response.ok) {
      const error = new Error('暂时无法读取生成进度')
      error.status = response.status
      throw error
    }
    if (!response.body || typeof response.body.getReader !== 'function') return poll()
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      while (!stopped) {
        const { done, value } = await reader.read()
        if (done) throw new Error('生成进度连接已断开，正在续读')
        buffer += decoder.decode(value, { stream: true })
        buffer = buffer.replace(/\r\n/g, '\n')
        let end
        while ((end = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, end)
          buffer = buffer.slice(end + 2)
          const lines = frame.split('\n')
          const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
          if (!data) continue
          const event = JSON.parse(data)
          if (lines.some(line => line === 'event: terminal')) {
            if (!stopped) callbacks.onTerminal(event.status)
            return true
          }
          accept(event)
        }
      }
      return false
    } finally {
      await reader.cancel().catch(() => {})
    }
    // #endif
    // #ifndef H5
    return poll()
    // #endif
  }

  async function run() {
    while (!stopped) {
      try {
        let complete
        // #ifdef H5
        complete = typeof AbortController !== 'undefined' && typeof ReadableStream !== 'undefined' ? await sse() : await poll()
        // #endif
        // #ifndef H5
        complete = await poll()
        // #endif
        if (complete) { stopped = true; return }
      } catch (error) {
        if (stopped) return
        if (error.status === 401) { stopped = true; goLogin(); return }
        if (error.status === 404) { stopped = true; callbacks.onError(error); return }
        callbacks.onError(error)
        await new Promise(resolve => setTimeout(resolve, 1000))
      }
    }
  }
  run()
  return () => { stopped = true; if (controller) controller.abort() }
}
