<template>
  <view class="page">
    <view class="card user">
      <view class="avatar">练</view>
      <view class="user-info">
        <text class="name">训练者</text>
        <text class="muted">ID：{{ uid }}</text>
      </view>
    </view>

    <view class="card menu">
      <view class="row" @tap="go('/pages/records/records')">
        <text>训练记录</text>
        <text class="chevron">›</text>
      </view>
      <view class="row">
        <text>服务状态</text>
        <text class="muted">{{ healthText }}</text>
      </view>
      <view class="row">
        <text>报告最短时长</text>
        <text class="muted">{{ minSec ? minSec + ' 秒' : '--' }}</text>
      </view>
    </view>
    <text class="foot muted">训练结果仅反映单次练习表现，仅供参考</text>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { getUserId } from '../../utils/request'

const uid = ref(getUserId())
const healthText = ref('检测中…')
const minSec = ref(0)

const go = (url) => uni.navigateTo({ url })

onShow(async () => {
  try {
    const h = await api.health()
    healthText.value = h.mock ? '在线 · Mock 模式' : '在线 · 已连接网关'
    minSec.value = h.min_duration_sec
  } catch (e) {
    healthText.value = '后端未连接'
  }
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx; box-sizing: border-box; }
.user { display: flex; align-items: center; padding: 40rpx 36rpx; margin-bottom: 28rpx; }
.avatar {
  width: 112rpx; height: 112rpx; border-radius: 50%; background: $tt-tag-bg; color: $tt-primary;
  font-size: 44rpx; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-right: 28rpx;
}
.user-info { display: flex; flex-direction: column; }
.name { font-size: 34rpx; font-weight: 700; margin-bottom: 8rpx; }
.menu { padding: 0 36rpx; }
.row {
  display: flex; justify-content: space-between; align-items: center;
  height: 108rpx; font-size: 30rpx; border-bottom: 1rpx solid #EEF1F5;
  &:last-child { border-bottom: none; }
}
.foot { display: block; text-align: center; margin-top: 40rpx; }
</style>
