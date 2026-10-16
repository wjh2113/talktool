// 统一请求封装：API 地址、登录令牌、401 跳登录、错误提示
let base = ''
// #ifdef H5
base = import.meta.env.VITE_API_BASE || '' // 同源，由 vite 代理到后端
// #endif
// #ifndef H5
base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
// #endif
export const API_BASE = base.replace(/\/$/, '')

const TOKEN_KEY = 'tt_token'
const USER_KEY = 'tt_user'
const DEVICE_KEY = 'tt_uid' // 旧版匿名设备 ID：注册时用来把这台设备上的历史记录归到新账号

export function getDeviceId() {
  return uni.getStorageSync(DEVICE_KEY) || ''
}

export function getToken() {
  return uni.getStorageSync(TOKEN_KEY) || ''
}

export function getCurrentUser() {
  return uni.getStorageSync(USER_KEY) || null
}

export function saveLogin({ token, user }) {
  if (token) uni.setStorageSync(TOKEN_KEY, token)
  if (user) uni.setStorageSync(USER_KEY, user)
}

export function clearLogin() {
  uni.removeStorageSync(TOKEN_KEY)
  uni.removeStorageSync(USER_KEY)
}

const LOGIN_PAGE = '/pages/login/login'
let redirecting = false
export function goLogin() {
  if (redirecting) return
  const pages = getCurrentPages()
  const cur = pages.length ? '/' + pages[pages.length - 1].route : ''
  if (cur === LOGIN_PAGE) return
  redirecting = true
  uni.reLaunch({ url: LOGIN_PAGE, complete: () => setTimeout(() => (redirecting = false), 500) })
}

function authHeader() {
  const t = getToken()
  return t ? { Authorization: 'Bearer ' + t } : {}
}

function handleUnauthorized(msg, silent) {
  clearLogin()
  if (!silent) uni.showToast({ title: msg || '请先登录', icon: 'none' })
  goLogin()
}

/** 后端返回的相对地址（/media/...）补全为可访问的绝对地址 */
export function absUrl(url) {
  if (!url) return ''
  if (/^https?:\/\//.test(url)) return url
  // #ifdef H5
  if (!API_BASE) return location.origin + url
  // #endif
  return API_BASE + url
}

export function request(url, { method = 'GET', data, silent = false, timeout = 90000 } = {}) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: API_BASE + url,
      method,
      data,
      timeout,
      header: { ...authHeader(), 'Content-Type': 'application/json' },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(res.data)
        const msg = (res.data && res.data.detail) || `请求失败（${res.statusCode}）`
        if (res.statusCode === 401) handleUnauthorized(msg, silent)
        else if (!silent) uni.showToast({ title: String(msg).slice(0, 40), icon: 'none', duration: 2500 })
        const err = new Error(msg)
        err.status = res.statusCode
        reject(err)
      },
      fail(err) {
        if (!silent) uni.showToast({ title: '网络异常，请检查后端是否启动', icon: 'none' })
        reject(err)
      }
    })
  })
}

/** 上传一段录音。H5：PCM ArrayBuffer；小程序：录音临时文件路径 */
export function uploadAudio(url, rec, extra = {}) {
  const form = { format: rec.format, sample_rate: String(rec.sampleRate || 16000) }
  Object.keys(extra).forEach((k) => {
    if (extra[k] !== undefined && extra[k] !== null) form[k] = String(extra[k])
  })
  const fail = (status, detail, fallback) => {
    if (status === 401) handleUnauthorized(detail)
    const e = new Error(detail || fallback)
    e.status = status
    return e
  }
  // #ifdef H5
  const fd = new FormData()
  fd.append('audio', new Blob([rec.data], { type: 'application/octet-stream' }), 'audio.' + rec.format)
  Object.keys(form).forEach((k) => fd.append(k, form[k]))
  return fetch(API_BASE + url, { method: 'POST', body: fd, headers: authHeader() }).then(async (r) => {
    const js = await r.json().catch(() => ({}))
    if (!r.ok) throw fail(r.status, js.detail, `上传失败（${r.status}）`)
    return js
  })
  // #endif
  // #ifndef H5
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: API_BASE + url,
      filePath: rec.filePath,
      name: 'audio',
      formData: form,
      timeout: 90000,
      header: authHeader(),
      success(res) {
        let js = {}
        try { js = JSON.parse(res.data) } catch (e) {}
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(js)
        else reject(fail(res.statusCode, js.detail, `上传失败（${res.statusCode}）`))
      },
      fail: reject
    })
  })
  // #endif
}
