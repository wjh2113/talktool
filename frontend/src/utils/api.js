import { request, uploadAudio } from './request'

export const api = {
  // 账号
  login: (username, password) => request('/api/auth/login', { method: 'POST', data: { username, password } }),
  register: (data) => request('/api/auth/register', { method: 'POST', data }),
  logout: () => request('/api/auth/logout', { method: 'POST', silent: true }),
  me: () => request('/api/auth/me', { silent: true }),
  changePassword: (old_password, new_password) =>
    request('/api/auth/password', { method: 'POST', data: { old_password, new_password } }),
  updateProfile: (nickname) => request('/api/auth/profile', { method: 'PUT', data: { nickname } }),
  updateTtsGender: (tts_gender) => request('/api/auth/tts-gender', { method: 'PUT', data: { tts_gender } }),

  // 管理员
  adminInvites: () => request('/api/admin/invites'),
  adminCreateInvites: (data) => request('/api/admin/invites', { method: 'POST', data }),
  adminDisableInvite: (code) => request(`/api/admin/invites/${code}/disable`, { method: 'POST' }),
  adminUsers: () => request('/api/admin/users'),
  adminSetUserStatus: (id, status) => request(`/api/admin/users/${id}/status`, { method: 'POST', data: { status } }),
  adminResetPassword: (id) => request(`/api/admin/users/${id}/reset-password`, { method: 'POST' }),

  health: () => request('/api/health', { silent: true }),
  ping: () => request('/api/ping', { silent: true, timeout: 5000 }),
  categories: () => request('/api/categories'),
  scenario: (id) => request(`/api/scenarios/${id}`),
  drill: (id) => request(`/api/drills/${id}`),
  drillScript: (id) => request(`/api/drills/${id}/script`, { timeout: 90000 }),

  // 表达框架库
  frameworks: (category = '', q = '') => {
    const qs = []
    if (category) qs.push('category=' + encodeURIComponent(category))
    if (q) qs.push('q=' + encodeURIComponent(q))
    return request('/api/frameworks' + (qs.length ? '?' + qs.join('&') : ''))
  },
  framework: (key) => request(`/api/frameworks/${encodeURIComponent(key)}`),

  // 训练
  startSession: (drillId) => request('/api/sessions', { method: 'POST', data: { drill_id: Number(drillId) } }),
  turn: (sessionId, rec) => uploadAudio(`/api/sessions/${sessionId}/turn`, rec),
  endSession: (sessionId, reason = 'finish') =>
    request(`/api/sessions/${sessionId}/end`, { method: 'POST', data: { reason }, timeout: 120000 }),
  turnReviews: (sessionId) => request(`/api/sessions/${sessionId}/turn-reviews`, { method: 'POST', timeout: 90000 }),
  retryReport: (sessionId) => request(`/api/sessions/${sessionId}/report/retry`, { method: 'POST', timeout: 120000 }),
  sessions: (range = 'all', page = 1) => request(`/api/sessions?range=${range}&page=${page}&page_size=20`),
  session: (id) => request(`/api/sessions/${id}`),
  stats: () => request('/api/stats', { silent: true }),

  // 示范朗读 & 跟读评测
  tts: (text, opts = {}) => request('/api/tts', { method: 'POST', data: { text, preview: !!opts.preview } }),
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
