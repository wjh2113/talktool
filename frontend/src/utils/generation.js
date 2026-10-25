import { getCurrentUser } from './request'

const storageKey = () => `tt_generation_${(getCurrentUser() || {}).uid || 'anonymous'}`
export function pendingGeneration() { return uni.getStorageSync(storageKey()) || null }
export function saveGeneration(value) {
  if (value) uni.setStorageSync(storageKey(), value)
  else uni.removeStorageSync(storageKey())
}
export function createGeneration(kind, consultId, payload) {
  const key = `job-${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
  const value = { request_key: key, kind, consult_id: consultId || null, payload }
  saveGeneration(value)
  return value
}
