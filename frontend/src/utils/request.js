// 统一请求封装：API 地址、设备用户 ID、错误提示
let base = ''
// #ifdef H5
base = import.meta.env.VITE_API_BASE || '' // 同源，由 vite 代理到后端
// #endif
// #ifndef H5
base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
// #endif
export const API_BASE = base.replace(/\/$/, '')

const UID_KEY = 'tt_uid'
export function getUserId() {
  let id = uni.getStorageSync(UID_KEY)
  if (!id) {
    id = 'u_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
    uni.setStorageSync(UID_KEY, id)
  }
  return id
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
      header: { 'X-User-Id': getUserId(), 'Content-Type': 'application/json' },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(res.data)
        const msg = (res.data && res.data.detail) || `请求失败（${res.statusCode}）`
        if (!silent) uni.showToast({ title: String(msg).slice(0, 40), icon: 'none', duration: 2500 })
        reject(new Error(msg))
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
  // #ifdef H5
  const fd = new FormData()
  fd.append('audio', new Blob([rec.data], { type: 'application/octet-stream' }), 'audio.' + rec.format)
  Object.keys(form).forEach((k) => fd.append(k, form[k]))
  return fetch(API_BASE + url, { method: 'POST', body: fd, headers: { 'X-User-Id': getUserId() } }).then(async (r) => {
    const js = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(js.detail || `上传失败（${r.status}）`)
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
      header: { 'X-User-Id': getUserId() },
      success(res) {
        let js = {}
        try { js = JSON.parse(res.data) } catch (e) {}
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(js)
        else reject(new Error(js.detail || `上传失败（${res.statusCode}）`))
      },
      fail: reject
    })
  })
  // #endif
}
