import { request, uploadAudio } from './request'

export const api = {
  health: () => request('/api/health', { silent: true }),
  ping: () => request('/api/ping', { silent: true, timeout: 5000 }),
  categories: () => request('/api/categories'),
  scenario: (id) => request(`/api/scenarios/${id}`),
  drill: (id) => request(`/api/drills/${id}`),
  startSession: (drillId) => request('/api/sessions', { method: 'POST', data: { drill_id: Number(drillId) } }),
  turn: (sessionId, rec) => uploadAudio(`/api/sessions/${sessionId}/turn`, rec),
  endSession: (sessionId, reason = 'finish') =>
    request(`/api/sessions/${sessionId}/end`, { method: 'POST', data: { reason }, timeout: 120000 }),
  retryReport: (sessionId) => request(`/api/sessions/${sessionId}/report/retry`, { method: 'POST', timeout: 120000 }),
  sessions: (range = 'all', page = 1) => request(`/api/sessions?range=${range}&page=${page}&page_size=20`),
  session: (id) => request(`/api/sessions/${id}`),
  stats: () => request('/api/stats', { silent: true })
}
