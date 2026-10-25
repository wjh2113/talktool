import { api } from './api'
import { getCurrentUser, getToken } from './request'

let registration = null
let syncing = false
const preferenceKey = () => `tt_notify_${(getCurrentUser() || {}).uid || 'anonymous'}`

export function notificationHint() {
  let hint = '当前环境不支持系统通知，站内提醒仍可使用'
  // #ifdef H5
  hint = ('serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window)
    ? '开启后，关闭页面也可接收提醒；需允许浏览器通知'
    : '请使用支持通知的浏览器；iPhone 请先将网页添加到主屏幕，再从主屏幕打开'
  // #endif
  // #ifdef APP-PLUS
  hint = '为已同步的事项安排本地提醒；其他设备改动需打开 App 同步'
  // #endif
  return hint
}

export async function setupNotifications() {
  // #ifdef H5
  if ('serviceWorker' in navigator && window.isSecureContext) {
    registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
    await navigator.serviceWorker.ready
  }
  // #endif
}

export async function enableNotifications() {
  // #ifdef H5
  if (!('Notification' in window) || !('PushManager' in window)) throw new Error(notificationHint())
  // 请求权限必须直接源于用户点击，不能先 await 网络请求。
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('通知权限未开启，请到浏览器的网站设置中允许通知')
  await setupNotifications()
  const config = await api.notificationConfig()
  const bytes = Uint8Array.from(atob(config.public_key.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - config.public_key.length % 4) % 4)), c => c.charCodeAt(0))
  let subscription = await registration.pushManager.getSubscription()
  if (!subscription) {
    let timer
    try {
      subscription = await Promise.race([
        registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes }),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('推送服务连接超时，请检查网络后重试')), 20000) })
      ])
    } finally { clearTimeout(timer) }
  }
  await api.subscribePush(subscription.toJSON())
  uni.setStorageSync(preferenceKey(), true)
  return
  // #endif
  // #ifdef APP-PLUS
  if (!plus.push) throw new Error('当前安装包未包含通知模块，请更新安装包')
  if (typeof uni.getAppAuthorizeSetting === 'function') {
    const auth = uni.getAppAuthorizeSetting()
    if (['denied', 'not determined'].includes(auth.notificationAuthorized)) {
      uni.openAppAuthorizeSetting({})
      throw new Error('请先在系统设置中允许通知，再回来开启')
    }
  }
  uni.setStorageSync(preferenceKey(), true)
  await syncNotifications()
  return
  // #endif
  // #ifndef H5
  // #ifndef APP-PLUS
  throw new Error(notificationHint())
  // #endif
  // #endif
}

export async function disableNotifications() {
  uni.removeStorageSync(preferenceKey())
  // #ifdef H5
  if ('serviceWorker' in navigator) {
    const reg = registration || await navigator.serviceWorker.getRegistration('/')
    const subscription = reg && await reg.pushManager.getSubscription()
    if (subscription) {
      const endpoint = subscription.endpoint
      await subscription.unsubscribe()
      if (getToken()) await api.unsubscribePush(endpoint)
    }
  }
  // #endif
  // #ifdef APP-PLUS
  if (plus.push) plus.push.clear()
  // #endif
}

export async function notificationEnabled() {
  // #ifdef H5
  if (!('Notification' in window) || Notification.permission !== 'granted' || !('serviceWorker' in navigator)) return false
  const reg = registration || await navigator.serviceWorker.getRegistration('/')
  return !!(reg && reg.pushManager && await reg.pushManager.getSubscription()) && !!uni.getStorageSync(preferenceKey())
  // #endif
  // #ifndef H5
  return !!uni.getStorageSync(preferenceKey())
  // #endif
}

export async function syncNotifications() {
  if (syncing || !getToken() || !uni.getStorageSync(preferenceKey())) return
  syncing = true
  try {
    // #ifdef H5
    const reg = registration || await navigator.serviceWorker.getRegistration('/')
    const subscription = reg && reg.pushManager && await reg.pushManager.getSubscription()
    if (subscription && Notification.permission === 'granted') await api.subscribePush(subscription.toJSON())
    // #endif
    // #ifdef APP-PLUS
    if (!plus.push) return
    const reminders = await api.reminders()
    plus.push.clear()
    for (const reminder of reminders.slice(0, 50)) {
      const at = new Date(reminder.due_at.replace(' ', 'T') + '+08:00').getTime()
      // 过期事项只在站内展示，避免每次开 App 重复弹通知。
      if (at <= Date.now()) continue
      plus.push.createMessage('你有事项需要跟进，打开查看并记录进展。', JSON.stringify({ consult_id: reminder.consult_id }), {
        title: '智囊跟进提醒', delay: Math.ceil((at - Date.now()) / 1000), cover: false
      })
    }
    // #endif
  } finally { syncing = false }
}
