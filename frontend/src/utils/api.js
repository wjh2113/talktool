import { request, uploadAudio, uploadForm } from './request'

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
  adminCatalogImport: (fileOrPath, mode = 'upsert') => {
    // #ifdef H5
    return uploadForm('/api/admin/catalog/import', { file: fileOrPath, fields: { mode } })
    // #endif
    // #ifndef H5
    return uploadForm('/api/admin/catalog/import', { filePath: fileOrPath, fields: { mode } })
    // #endif
  },

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

  // AI 智囊团
  transcribe: (rec) => uploadAudio('/api/transcribe', rec),
  advisorHome: () => request('/api/advisor/home'),
  councils: () => request('/api/councils'),
  strategies: (school = '', domain = '', q = '') => {
    const qs = []
    if (school) qs.push('school=' + encodeURIComponent(school))
    if (domain) qs.push('domain=' + encodeURIComponent(domain))
    if (q) qs.push('q=' + encodeURIComponent(q))
    return request('/api/strategies' + (qs.length ? '?' + qs.join('&') : ''))
  },
  strategy: (code) => request(`/api/strategies/${encodeURIComponent(code)}`),
  createConsult: (text, council, advisors) =>
    request('/api/consults', { method: 'POST', data: { text, council: council || null, advisors: advisors || null }, timeout: 90000 }),
  advisorDue: () => request('/api/advisor/due'),
  consults: () => request('/api/consults'),
  consult: (id, version) => request(`/api/consults/${id}` + (version ? `?version=${version}` : '')),
  consultMessage: (id, text, kind = 'ask') =>
    request(`/api/consults/${id}/messages`, { method: 'POST', data: { text, kind }, timeout: 150000 }),
  makePlan: (id, council) =>
    request(`/api/consults/${id}/plan`, { method: 'POST', data: { council: council || null }, timeout: 150000 }),
  rehearse: (id) => request(`/api/consults/${id}/rehearse`, { method: 'POST' }),
  deleteConsult: (id) => request(`/api/consults/${id}`, { method: 'DELETE' }),
  updateAction: (id, data) => request(`/api/plan-actions/${id}`, { method: 'PUT', data }),
  roundtable: (id, topic) => request(`/api/consults/${id}/roundtable`, { method: 'POST', data: { topic: topic || '' }, timeout: 150000 }),
  setConsultAdvisors: (id, codes) => request(`/api/consults/${id}/advisors`, { method: 'PUT', data: { codes } }),
  snoozeConsult: (id, days) => request(`/api/consults/${id}/snooze`, { method: 'POST', data: { days } }),
  stopFollow: (id) => request(`/api/consults/${id}/stop-follow`, { method: 'POST' }),
  ratePlan: (id, rating, reason) => request(`/api/plans/${id}/rating`, { method: 'PUT', data: { rating, reason: reason || '' } }),
  myAdvisors: () => request('/api/my-advisors'),
  createMyAdvisor: (data) => request('/api/my-advisors', { method: 'POST', data }),
  updateMyAdvisor: (code, data) => request(`/api/my-advisors/${code}`, { method: 'PUT', data }),
  deleteMyAdvisor: (code) => request(`/api/my-advisors/${code}`, { method: 'DELETE' }),

  // 长期记忆
  memory: () => request('/api/memory'),
  memoryAddProfile: (text) => request('/api/memory/profile', { method: 'POST', data: { text } }),
  memoryUpdateItem: (id, data) => request(`/api/memory/items/${id}`, { method: 'PUT', data }),
  memoryDeleteItem: (id) => request(`/api/memory/items/${id}`, { method: 'DELETE' }),
  memoryUpdateSubject: (id, data) => request(`/api/memory/subjects/${id}`, { method: 'PUT', data }),
  memoryMergeSubject: (id, into) => request(`/api/memory/subjects/${id}/merge`, { method: 'POST', data: { into } }),
  memoryDeleteSubject: (id) => request(`/api/memory/subjects/${id}`, { method: 'DELETE' }),
  memoryCompact: (id) => request(`/api/memory/subjects/${id}/compact`, { method: 'POST', timeout: 90000 }),
  memoryPause: (paused) => request('/api/memory/pause', { method: 'POST', data: { paused } }),
  memoryClear: () => request('/api/memory/clear', { method: 'POST' }),

  // 管理员：提示词 / 智囊团
  adminPrompts: () => request('/api/admin/prompts'),
  adminPrompt: (key) => request(`/api/admin/prompts/${encodeURIComponent(key)}`),
  adminSavePrompt: (key, data) => request(`/api/admin/prompts/${encodeURIComponent(key)}`, { method: 'PUT', data }),
  adminTestPrompt: (key, message, draft) =>
    request(`/api/admin/prompts/${encodeURIComponent(key)}/test`, { method: 'POST', data: { message, draft: draft || null }, timeout: 180000 }),
  adminPublishPrompt: (key) => request(`/api/admin/prompts/${encodeURIComponent(key)}/publish`, { method: 'POST' }),
  adminRollbackPrompt: (key, version) =>
    request(`/api/admin/prompts/${encodeURIComponent(key)}/rollback`, { method: 'POST', data: { version } }),
  adminResetPrompt: (key) => request(`/api/admin/prompts/${encodeURIComponent(key)}/reset`, { method: 'POST' }),
  adminCouncils: () => request('/api/admin/councils'),
  adminSaveCouncil: (code, data) => request(`/api/admin/councils/${code}`, { method: 'PUT', data }),
  adminCreateCouncil: (data) => request('/api/admin/councils', { method: 'POST', data }),
  adminAdvisorStats: (days = 30) => request(`/api/admin/advisor-stats?days=${days}`),

  // 自定义场景
  customDrills: () => request('/api/custom-drills'),
  createCustom: (description, pressure_level) =>
    request('/api/custom-drills', { method: 'POST', data: { description, pressure_level }, timeout: 120000 }),
  deleteCustom: (id) => request(`/api/custom-drills/${id}`, { method: 'DELETE' })
}
