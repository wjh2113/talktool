<script setup>
import { onLaunch, onShow, onHide } from '@dcloudio/uni-app'
import { setupNotifications, syncNotifications } from './utils/notifications'
import { getToken, goLogin } from './utils/request'

onLaunch(() => {
  for (const name of ['navigateTo', 'navigateBack', 'redirectTo', 'reLaunch', 'switchTab']) {
    uni.addInterceptor(name, { invoke: () => { uni.$emit('tt:page-hide') } })
  }
  // 没登录 → 去登录页（令牌过期由接口 401 统一处理）
  if (!getToken()) setTimeout(goLogin, 0)
  setupNotifications().catch(() => {})
  // #ifdef APP-PLUS
  if (plus.push) plus.push.addEventListener('click', (message) => {
    try {
      const payload = typeof message.payload === 'string' ? JSON.parse(message.payload) : message.payload
      if (payload && Number(payload.consult_id)) uni.navigateTo({ url: '/pages/consult/consult?id=' + Number(payload.consult_id) + '&review=1' })
    } catch (_) {}
  })
  // #endif
})
onShow(() => syncNotifications().catch(() => {}))
onHide(() => uni.$emit('tt:page-hide'))
</script>

<style lang="scss">
page {
  background: $tt-bg;
  color: $tt-text;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', 'Microsoft YaHei', sans-serif;
  font-size: 28rpx;
}
.card {
  background: $tt-card;
  border-radius: $tt-radius;
  box-shadow: 0 4rpx 20rpx rgba(31, 35, 41, 0.05);
  border: 1rpx solid #EEF1F5;
}
.tag {
  display: inline-flex;
  align-items: center;
  height: 52rpx;
  padding: 0 22rpx;
  border-radius: 26rpx;
  font-size: 24rpx;
  background: $tt-tag-bg;
  color: $tt-primary;
}
.tag-gray { background: #F0F2F5; color: $tt-text-2; }
.tag-mid { background: #FFF4E5; color: #E68A1A; }
.tag-high { background: #FDECEC; color: #E5484D; }
.chevron { color: #9AA0A6; font-size: 40rpx; line-height: 1; }
.btn-primary {
  background: $tt-primary;
  color: #fff;
  border-radius: 20rpx;
  height: 96rpx;
  line-height: 96rpx;
  text-align: center;
  font-size: 32rpx;
  font-weight: 600;
}
.btn-primary:active { background: $tt-primary-deep; }
.btn-plain {
  background: #fff;
  color: $tt-text;
  border: 1rpx solid #E3E7ED;
  border-radius: 20rpx;
  height: 96rpx;
  line-height: 96rpx;
  text-align: center;
  font-size: 32rpx;
  font-weight: 600;
}
.ellipsis-2 {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.muted { color: $tt-text-3; font-size: 24rpx; }
</style>

<style lang="scss">
@media (min-width: 900px) {
  uni-page-body > .page { max-width: 1120px; margin-left: auto; margin-right: auto; box-sizing: border-box; }
  uni-page-body { background: #e8f0ed; min-height: 100vh; }
}
</style>
