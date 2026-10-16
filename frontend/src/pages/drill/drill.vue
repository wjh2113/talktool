<template>
  <view v-if="d" class="page">
    <!-- 顶部大图 + 渐变 + 标题 -->
    <view class="hero">
      <image v-if="d.cover_image" class="hero-img" :src="d.cover_image" mode="aspectFill" />
      <view v-else class="hero-img" :style="coverStyle(d.category_name)">
        <text class="hero-deco">{{ d.scenario_title }}</text>
      </view>
      <view class="hero-mask" />
      <view class="nav" :style="{ paddingTop: statusBar + 'px' }">
        <view class="back" @tap="back">‹</view>
        <text class="nav-title">场景介绍</text>
        <view class="back" />
      </view>
      <view class="hero-text">
        <text class="hero-cat">{{ d.scenario_title }}</text>
        <text class="hero-title">{{ d.title }}</text>
      </view>
    </view>

    <view class="card pills">
      <view class="pill">
        <text class="pill-v">{{ d.pressure_level }}</text>
        <text class="pill-k">压力等级</text>
      </view>
      <view class="pill">
        <text class="pill-v">约 {{ d.duration_min }} 分钟</text>
        <text class="pill-k">预计时长</text>
      </view>
      <view class="pill">
        <text class="pill-v">{{ d.mode }}</text>
        <text class="pill-k">训练方式</text>
      </view>
    </view>

    <text class="block-title">场景描述</text>
    <view class="card desc">
      <text>{{ d.description }}</text>
    </view>

    <text class="block-title">训练目标</text>
    <view class="card desc goal">
      <text>{{ d.training_goal }}</text>
      <text class="muted role">你的角色：{{ d.user_role }}</text>
    </view>

    <view class="footer">
      <view class="btn-primary" @tap="start">开始训练</view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { coverStyle } from '../../utils/format'
import { unlockAudio } from '../../utils/voice'

const d = ref(null)
const statusBar = ref(uni.getSystemInfoSync().statusBarHeight || 20)

function back() {
  uni.navigateBack({ fail: () => uni.switchTab({ url: '/pages/scenes/scenes' }) })
}

function start() {
  unlockAudio() // H5：在用户点击中解锁音频，保证进入训练页后 AI 语音能自动播放
  uni.navigateTo({ url: `/pages/train/train?drillId=${d.value.id}` })
}

onLoad(async (q) => {
  d.value = await api.drill(q.id)
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding-bottom: 200rpx; }
.hero { position: relative; height: 520rpx; overflow: hidden; }
.hero-img { position: absolute; top: 0; left: 0; right: 0; bottom: 0; width: 100%; height: 100%; display: flex; align-items: flex-end; justify-content: flex-end; }
.hero-deco {
  font-size: 150rpx;
  font-weight: 900;
  color: rgba(255, 255, 255, 0.14);
  margin: 0 -20rpx 140rpx 0;
  white-space: nowrap;
}
.hero-mask { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(180deg, rgba(0,0,0,0.15) 0%, rgba(0,0,0,0) 40%, rgba(0,0,0,0.45) 100%); }
.nav {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 88rpx;
  padding: 0 24rpx;
  box-sizing: content-box;
}
.back { width: 64rpx; color: #fff; font-size: 56rpx; line-height: 88rpx; }
.nav-title { color: #fff; font-size: 34rpx; font-weight: 600; }
.hero-text { position: absolute; left: 44rpx; right: 44rpx; bottom: 56rpx; display: flex; flex-direction: column; }
.hero-cat { color: rgba(255, 255, 255, 0.85); font-size: 26rpx; margin-bottom: 14rpx; }
.hero-title { color: #fff; font-size: 44rpx; font-weight: 800; line-height: 1.45; }
.pills {
  display: flex;
  gap: 20rpx;
  margin: 32rpx 32rpx 0;
  padding: 36rpx;
}
.pill {
  flex: 1;
  background: #F3F6FA;
  border-radius: 16rpx;
  padding: 26rpx 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.pill-v { color: $tt-primary; font-size: 32rpx; font-weight: 700; margin-bottom: 10rpx; }
.pill-k { color: $tt-text-3; font-size: 24rpx; }
.block-title { display: block; font-size: 34rpx; font-weight: 700; margin: 48rpx 32rpx 24rpx; }
.desc {
  margin: 0 32rpx;
  padding: 40rpx;
  font-size: 30rpx;
  line-height: 1.85;
  color: #333;
}
.goal { display: flex; flex-direction: column; }
.role { margin-top: 16rpx; }
.footer {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 24rpx 40rpx calc(24rpx + env(safe-area-inset-bottom));
  background: #fff;
  box-shadow: 0 -4rpx 20rpx rgba(0, 0, 0, 0.04);
}
</style>
