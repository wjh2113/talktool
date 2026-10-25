<template>
  <view class="page">
    <view class="ranges">
      <text v-for="d in [7, 30, 90]" :key="d" class="range" :class="{ on: days === d }" @tap="setDays(d)">近 {{ d }} 天</text>
    </view>

    <view v-if="s" class="card box totals">
      <view class="t"><text class="t-v">{{ s.total.consults }}</text><text class="t-k">问计</text></view>
      <view class="t"><text class="t-v">{{ s.total.plans }}</text><text class="t-k">锦囊</text></view>
      <view class="t"><text class="t-v">{{ pct(s.total.up_rate) }}</text><text class="t-k">有用率（{{ s.total.rated }} 评）</text></view>
      <view class="t"><text class="t-v">{{ pct(s.total.rehearse_rate) }}</text><text class="t-k">去演练</text></view>
      <view class="t"><text class="t-v">{{ pct(s.total.review_rate) }}</text><text class="t-k">回来复盘</text></view>
      <view class="t"><text class="t-v">{{ pct(s.total.action_rate) }}</text><text class="t-k">行动完成</text></view>
    </view>

    <template v-if="s">
      <text class="block-title">按智囊团</text>
      <view v-for="c in s.councils" :key="c.code" class="card box">
        <view class="c-head">
          <text class="c-name">{{ c.name }}</text>
          <text class="muted">{{ c.consults }} 次问计 · {{ c.plans }} 份锦囊</text>
        </view>
        <view class="bars">
          <view v-for="m in metrics" :key="m.k" class="bar-row">
            <text class="bar-k">{{ m.n }}</text>
            <view class="bar"><view class="bar-in" :class="m.k" :style="{ width: (c[m.k] || 0) * 100 + '%' }" /></view>
            <text class="bar-v">{{ pct(c[m.k]) }}</text>
          </view>
        </view>
        <text class="muted">👍 {{ c.up }} · 👎 {{ c.down }} · 圆桌 {{ c.roundtables }} 次</text>
      </view>
      <text v-if="!s.councils.length" class="empty muted">这段时间还没有人问计</text>

      <text class="block-title">按提示词版本</text>
      <text class="hint muted">同一个提示词的不同版本出的锦囊，被用户评为“有用”的比例。评价数太少时（少于 10）仅供参考。</text>
      <view class="card box">
        <view v-for="p in s.prompts" :key="p.key + p.version" class="p-row" @tap="openPrompt(p.key)">
          <text class="p-key">{{ promptName(p.key) }}</text>
          <text class="p-ver">{{ p.label }}</text>
          <text class="p-n muted">{{ p.plans }} 份 / {{ p.rated }} 评</text>
          <text class="p-rate" :class="{ low: p.up_rate !== null && p.up_rate < 0.5 }">{{ pct(p.up_rate) }}</text>
        </view>
        <text v-if="!s.prompts.length" class="muted">暂无数据</text>
      </view>

      <text class="block-title">“没用”的反馈</text>
      <view class="card box">
        <view v-for="(f, i) in s.feedback" :key="i" class="fb">
          <text class="fb-text">{{ f.reason }}</text>
          <text class="muted">{{ f.council }} · {{ (f.at || '').slice(5, 16) }}</text>
        </view>
        <text v-if="!s.feedback.length" class="muted">暂无</text>
      </view>
      <text class="foot muted">只统计数量和比例，看不到用户的问计内容；反馈原文是用户评价时自己写的。</text>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow, onPullDownRefresh } from '@dcloudio/uni-app'
import { api } from '../../utils/api'

const s = ref(null)
const days = ref(30)
const names = ref({})
const metrics = [
  { k: 'up_rate', n: '有用率' },
  { k: 'rehearse_rate', n: '去演练' },
  { k: 'review_rate', n: '回来复盘' },
  { k: 'action_rate', n: '行动完成' }
]

const pct = (v) => (v === null || v === undefined ? '--' : Math.round(v * 100) + '%')
const promptName = (key) => names.value[key] || key

async function load() {
  s.value = await api.adminAdvisorStats(days.value)
  if (!Object.keys(names.value).length) {
    api.adminPrompts().then((r) => {
      const m = {}
      r.forEach((p) => (m[p.key] = p.name))
      names.value = m
    }).catch(() => {})
  }
}

function setDays(d) {
  days.value = d
  load()
}

const openPrompt = (key) => uni.navigateTo({ url: `/pages/admin-prompts/admin-prompts?key=${key}` })

onShow(() => load().catch(() => {}))
onPullDownRefresh(async () => {
  try { await load() } finally { uni.stopPullDownRefresh() }
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 24rpx 28rpx 80rpx; box-sizing: border-box; }
.ranges { display: flex; gap: 14rpx; margin-bottom: 20rpx; }
.range { flex: 1; text-align: center; font-size: 25rpx; padding: 14rpx 0; border-radius: 12rpx; background: #fff; color: $tt-text-2; }
.range.on { background: $tt-primary; color: #fff; }
.box { padding: 26rpx 28rpx; margin-bottom: 16rpx; display: flex; flex-direction: column; }
.totals { flex-direction: row; flex-wrap: wrap; row-gap: 24rpx; }
.t { width: 33.33%; display: flex; flex-direction: column; align-items: center; }
.t-v { font-size: 38rpx; font-weight: 800; color: $tt-primary; }
.t-k { font-size: 21rpx; color: $tt-text-3; margin-top: 4rpx; text-align: center; }
.block-title { display: block; font-size: 30rpx; font-weight: 700; margin: 28rpx 4rpx 14rpx; }
.hint { display: block; margin: -4rpx 4rpx 14rpx; line-height: 1.6; }
.c-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12rpx; }
.c-name { font-size: 29rpx; font-weight: 700; }
.bars { margin-bottom: 10rpx; }
.bar-row { display: flex; align-items: center; gap: 14rpx; margin: 8rpx 0; }
.bar-k { width: 120rpx; font-size: 23rpx; color: $tt-text-2; }
.bar { flex: 1; height: 14rpx; border-radius: 7rpx; background: $tt-bg; overflow: hidden; }
.bar-in { height: 100%; border-radius: 7rpx; background: $tt-primary; }
.bar-in.rehearse_rate { background: #4A90D9; }
.bar-in.review_rate { background: #E8A13A; }
.bar-in.action_rate { background: #7C6FD6; }
.bar-v { width: 72rpx; text-align: right; font-size: 23rpx; font-weight: 600; }
.p-row { display: flex; align-items: center; gap: 14rpx; padding: 14rpx 0; border-bottom: 1rpx solid #F0F2F1; }
.p-row:last-child { border-bottom: none; }
.p-key { flex: 1; font-size: 26rpx; }
.p-ver { font-size: 22rpx; color: $tt-primary; background: $tt-tag-bg; padding: 2rpx 12rpx; border-radius: 8rpx; }
.p-n { font-size: 22rpx; }
.p-rate { width: 80rpx; text-align: right; font-size: 26rpx; font-weight: 700; color: $tt-primary; }
.p-rate.low { color: #E5564B; }
.fb { padding: 12rpx 0; border-bottom: 1rpx solid #F0F2F1; display: flex; flex-direction: column; gap: 4rpx; }
.fb:last-child { border-bottom: none; }
.fb-text { font-size: 27rpx; line-height: 1.6; }
.empty { display: block; text-align: center; padding: 40rpx 0; }
.foot { display: block; text-align: center; margin-top: 20rpx; line-height: 1.6; }
</style>
