<template>
  <view v-if="s" class="page">
    <view class="head">
      <text class="cat">{{ s.school_name }}{{ s.sub ? ' · ' + s.sub : '' }}</text>
      <text class="title">{{ s.name }}</text>
      <text v-if="s.caution" class="caution">慎用：智囊只用它帮你识别和防范，不教你用它对付别人</text>
    </view>

    <template v-if="s.origin">
      <text class="block-title">原文</text>
      <view class="card box origin"><text class="txt">{{ s.origin }}</text></view>
    </template>

    <text class="block-title">白话</text>
    <view class="card box"><text class="txt">{{ s.plain }}</text></view>

    <text class="block-title">{{ s.caution ? '怎么识别和防范' : '怎么做' }}</text>
    <view class="card box">
      <view v-for="(d, i) in s.how_to_do" :key="i" class="step">
        <text class="step-no">{{ i + 1 }}</text>
        <text class="txt">{{ d }}</text>
      </view>
    </view>

    <text class="block-title">怎么说</text>
    <view class="card box say-box">
      <text class="say">“{{ s.how_to_say }}”</text>
      <ReadAloud v-if="!s.how_to_say.startsWith('（')" :text="s.how_to_say" />
    </view>

    <template v-if="s.misuses">
      <text class="block-title">常见误用</text>
      <view class="card box"><view class="line"><text class="x">✕</text><text class="txt">{{ s.misuses }}</text></view></view>
    </template>

    <template v-if="s.frameworks.length">
      <text class="block-title">配合这些表达框架</text>
      <view v-for="f in s.frameworks" :key="f.code" class="card box fw" @tap="openFw(f.code)">
        <view class="fw-head"><text class="fw-name">{{ f.name }}</text><text class="chevron">›</text></view>
        <text class="muted">{{ f.summary }}</text>
      </view>
    </template>

    <view class="tags">
      <text class="muted">适用：</text>
      <text v-for="d in s.domains" :key="d" class="dm">{{ d }}</text>
    </view>

    <view class="footer">
      <view class="btn-primary go" @tap="ask">带着这一计去问智囊</view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import ReadAloud from '../../components/ReadAloud/ReadAloud.vue'

const s = ref(null)

const openFw = (code) => uni.navigateTo({ url: `/pages/framework/framework?key=${code}` })

function ask() {
  uni.showModal({
    title: `用「${s.value.name}」解决什么问题？`,
    editable: true,
    placeholderText: '说说你遇到的情况',
    success: (r) => {
      if (r.confirm && r.content && r.content.trim().length >= 2) {
        const council = (s.value.councils[0] || {}).code || ''
        uni.setStorageSync('tt_pending_consult', { text: `${r.content.trim()}（我想参考「${s.value.name}」的思路）`, council })
        uni.navigateTo({ url: '/pages/consult/consult' })
      }
    }
  })
}

onLoad(async (q) => {
  s.value = await api.strategy(q.code)
  uni.setNavigationBarTitle({ title: s.value.name })
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding-bottom: 180rpx; }
.head { background: linear-gradient(135deg, $tt-hero-from, $tt-hero-to); padding: 40rpx 40rpx 48rpx; display: flex; flex-direction: column; color: #fff; }
.cat { font-size: 24rpx; opacity: 0.85; }
.title { font-size: 44rpx; font-weight: 800; margin-top: 10rpx; }
.caution { margin-top: 16rpx; font-size: 23rpx; background: rgba(255, 255, 255, 0.18); padding: 10rpx 16rpx; border-radius: 10rpx; }
.block-title { display: block; font-size: 31rpx; font-weight: 700; margin: 36rpx 32rpx 18rpx; }
.box { margin: 0 32rpx 16rpx; padding: 28rpx 32rpx; display: flex; flex-direction: column; }
.txt { font-size: 28rpx; line-height: 1.85; color: $tt-text; flex: 1; }
.origin { background: #FFFDF5; }
.origin .txt { font-style: italic; color: $tt-text-2; }
.step { display: flex; gap: 18rpx; padding: 8rpx 0; }
.step-no {
  width: 40rpx; height: 40rpx; line-height: 40rpx; text-align: center; border-radius: 50%; background: $tt-primary; color: #fff;
  font-size: 22rpx; flex-shrink: 0; margin-top: 8rpx;
}
.say { font-size: 30rpx; font-weight: 600; line-height: 1.7; }
.line { display: flex; gap: 12rpx; }
.x { color: #E5564B; font-size: 24rpx; line-height: 1.9; }
.fw-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6rpx; }
.fw-name { font-size: 29rpx; font-weight: 700; color: $tt-primary; }
.chevron { color: $tt-text-3; }
.tags { display: flex; flex-wrap: wrap; align-items: center; gap: 10rpx; margin: 28rpx 32rpx; }
.dm { font-size: 22rpx; color: $tt-primary; background: $tt-tag-bg; padding: 4rpx 14rpx; border-radius: 8rpx; }
.footer { position: fixed; left: 0; right: 0; bottom: 0; background: #fff; padding: 20rpx 40rpx calc(20rpx + env(safe-area-inset-bottom)); }
.go { width: 100%; }
</style>
