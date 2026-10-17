/** 本地缓存的示范/对练音色偏好，与账号 tts_gender 同步 */
import { getCurrentUser, saveLogin } from './request'

const KEY = 'tt_tts_gender'

export function getTtsGender() {
  const u = getCurrentUser()
  if (u && (u.tts_gender === 'male' || u.tts_gender === 'female')) return u.tts_gender
  const local = uni.getStorageSync(KEY)
  return local === 'female' ? 'female' : 'male'
}

export function syncTtsGender(user) {
  if (!user) return
  const g = user.tts_gender === 'female' ? 'female' : 'male'
  uni.setStorageSync(KEY, g)
  if (user.tts_gender !== g) user.tts_gender = g
  saveLogin({ user: { ...getCurrentUser(), ...user, tts_gender: g } })
}
