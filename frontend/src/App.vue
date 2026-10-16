<script setup>
import { onLaunch } from '@dcloudio/uni-app'
import { getUserId } from './utils/request'

onLaunch(() => {
  getUserId() // 首次启动生成设备用户 ID（MVP 不做登录）
})
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
