import { request, uploadAudio } from './request'

export const api = {
  health: () => request('/api/health', { silent: true }),
  ping: () => request('/api/ping', { silent: true, timeout: 5000 }),
  categories: () => request('/api/categories'),
  scenario: (id) => request(`/api/scenarios/${id}`),
  drill: (id) => request(`/api/drills/${id}`),
  drillScript: (id) => request(`/api/drills/${id}/script`, { timeout: 90000 }),

  // 训练
  startSession: (drillId) => request('/api/sessions', { method: 'POST', data: { drill_id: Number(drillId) } }),
  turn: (sessionId, rec) => uploadAudio(`/api/sessions/${sessionId}/turn`, rec),
  endSession: (sessionId, reason = 'finish') =>
    request(`/api/sessions/${sessionId}/end`, { method: 'POST', data: { reason }, timeout: 120000 }),
  retryReport: (sessionId) => request(`/api/sessions/${sessionId}/report/retry`, { method: 'POST', timeout: 120000 }),
  sessions: (range = 'all', page = 1) => request(`/api/sessions?range=${range}&page=${page}&page_size=20`),
  session: (id) => request(`/api/sessions/${id}`),
  stats: () => request('/api/stats', { silent: true }),

  // 示范朗读 & 跟读评测
  tts: (text) => request('/api/tts', { method: 'POST', data: { text } }),
  pronounce: (rec, text, noteId) => uploadAudio('/api/pronounce', rec, { text, note_id: noteId }),

  // 练习本
  notes: (kind) => request('/api/notes' + (kind ? `?kind=${kind}` : '')),
  addNote: (data) => request('/api/notes', { method: 'POST', data }),
  deleteNote: (id) => request(`/api/notes/${id}`, { method: 'DELETE' }),

  // 自定义场景
  customDrills: () => request('/api/custom-drills'),
  createCustom: (description, pressure_level) =>
    request('/api/custom-drills', { method: 'POST', data: { description, pressure_level }, timeout: 120000 }),
  deleteCustom: (id) => request(`/api/custom-drills/${id}`, { method: 'DELETE' })
}
