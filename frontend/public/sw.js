/* 仅负责通知，不缓存私有接口或语音内容。 */
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))
self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title || '智囊跟进提醒', {
    body: data.body || '你有事项需要跟进，打开查看。',
    icon: '/pwa-icon.svg', badge: '/pwa-icon.svg',
    tag: data.tag || 'talktool-reminder',
    data: { url: data.url || '/#/pages/advisor/advisor' }
  }))
})
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const raw = event.notification.data && event.notification.data.url
  const target = new URL(raw || '/#/pages/advisor/advisor', self.location.origin)
  if (target.origin !== self.location.origin) return
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (windows) => {
    for (const window of windows) {
      if (window.url.startsWith(self.location.origin)) {
        await window.navigate(target.href)
        return window.focus()
      }
    }
    return self.clients.openWindow(target.href)
  }))
})
