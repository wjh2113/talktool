<template>
  <view class="page">
    <view class="hero">
      <text class="hello">沟通的健身房</text>
      <text class="slogan">AI 扮演对手角色，在真实场景里练习说话</text>
      <view class="stats">
        <view class="stat">
          <text class="stat-v">{{ stats.total }}</text>
          <text class="stat-k">训练次数</text>
        </view>
        <view class="stat">
          <text class="stat-v">{{ stats.minutes }}</text>
          <text class="stat-k">累计分钟</text>
        </view>
        <view class="stat">
          <text class="stat-v">{{ stats.avg_score == null ? '--' : stats.avg_score }}</text>
          <text class="stat-k">平均得分</text>
        </view>
      </view>
    </view>

    <view class="card quick" @tap="goScenes">
      <view>
        <text class="quick-title">开始训练</text>
        <text class="quick-sub">{{ countText }}</text>
      </view>
      <text class="chevron">›</text>
    </view>

    <view class="duo">
      <view class="card mini" @tap="goCustom">
        <text class="mini-title">自定义场景</text>
        <text class="mini-sub">说说你的真实情况，AI 生成专属训练</text>
      </view>
      <view class="card mini" @tap="goNotebook">
        <text class="mini-title">练习本<text v-if="stats.notes" class="mini-count"> {{ stats.notes }}</text></text>
        <text class="mini-sub">收藏的话术，随时跟读</text>
      </view>
    </view>

    <view class="card quick fw-entry" @tap="goFrameworks">
      <view>
        <text class="quick-title">表达框架库</text>
        <text class="quick-sub">汇报、拒绝、谈判、即兴发言… {{ fwTotal || '' }}{{ fwTotal ? ' 个' : '' }}说话套路，附示例和误区</text>
      </view>
      <text class="chevron">›</text>
    </view>

    <view class="sec-head">
      <text class="sec-title">推荐练习</text>
    </view>
    <view v-for="p in picks" :key="p.id" class="card pick" @tap="openScenario(p)">
      <view class="pick-cover" :style="coverStyle(p.category)">
        <text>{{ p.title.slice(0, 2) }}</text>
      </view>
      <view class="pick-body">
        <text class="pick-title">{{ p.title }}</text>
        <text class="pick-sub">{{ p.subtitle }}</text>
      </view>
      <text class="chevron">›</text>
    </view>

    <view class="card quick records" @tap="goRecords">
      <view>
        <text class="quick-title">训练记录</text>
        <text class="quick-sub">回看每一次训练的报告</text>
      </view>
      <text class="chevron">›</text>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { coverStyle } from '../../utils/format'

const stats = ref({ total: 0, minutes: 0, avg_score: null, notes: 0 })
const picks = ref([])
const counts = ref({ cats: 0, drills: 0 })
const countText = computed(() =>
  counts.value.cats ? `${counts.value.cats} 大分类 · ${counts.value.drills} 个场景，选一个开练` : '选一个场景开练'
)
const fwTotal = ref(0)
const PICK_TITLES = ['临时点名发言', '自我介绍', '平息客户怒火', '争取利益']

async function load() {
  api.stats().then((s) => (stats.value = s)).catch(() => {})
  if (picks.value.length) return
  api.frameworks().then((r) => (fwTotal.value = r.total)).catch(() => {})
  const cats = await api.categories()
  const all = []
  cats.forEach((c) => c.scenarios.forEach((s) => all.push({ ...s, category: c.name })))
  counts.value = { cats: cats.length, drills: all.reduce((n, s) => n + (s.drill_count || 0), 0) }
  picks.value = PICK_TITLES.map((t) => all.find((s) => s.title === t)).filter(Boolean)
}

const goScenes = () => uni.switchTab({ url: '/pages/scenes/scenes' })
const goCustom = () => uni.navigateTo({ url: '/pages/custom/custom' })
const goNotebook = () => uni.switchTab({ url: '/pages/notebook/notebook' })
const goFrameworks = () => uni.navigateTo({ url: '/pages/frameworks/frameworks' })
const goRecords =() => uni.navigateTo({ url: '/pages/records/records' })
const openScenario = (s) => uni.navigateTo({ url: `/pages/scenario/scenario?id=${s.id}` })

onShow(load)
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx; box-sizing: border-box; }
.hero {
  border-radius: 28rpx;
  padding: 44rpx 40rpx 36rpx;
  background: linear-gradient(135deg, #5AAEFA 0%, #3B85E0 100%);
  color: #fff;
  display: flex;
  flex-direction: column;
  margin-bottom: 28rpx;
}
.hello { font-size: 44rpx; font-weight: 800; margin-bottom: 12rpx; }
.slogan { font-size: 26rpx; opacity: 0.85; margin-bottom: 40rpx; }
.stats { display: flex; }
.stat { flex: 1; display: flex; flex-direction: column; }
.stat-v { font-size: 44rpx; font-weight: 800; }
.stat-k { font-size: 24rpx; opacity: 0.8; margin-top: 4rpx; }
.quick { display: flex; align-items: center; justify-content: space-between; padding: 36rpx; margin-bottom: 28rpx; }
.quick > view { display: flex; flex-direction: column; }
.quick-title { font-size: 34rpx; font-weight: 700; margin-bottom: 10rpx; }
.quick-sub { font-size: 26rpx; color: $tt-text-2; }
.records { margin-top: 12rpx; }
.duo { display: flex; gap: 20rpx; margin-bottom: 28rpx; }
.mini { flex: 1; padding: 30rpx 28rpx; display: flex; flex-direction: column; }
.mini-title { font-size: 30rpx; font-weight: 700; margin-bottom: 10rpx; }
.mini-count { color: $tt-primary; }
.mini-sub { font-size: 24rpx; color: $tt-text-2; line-height: 1.5; }
.sec-head { padding: 16rpx 4rpx 24rpx; }
.sec-title { font-size: 32rpx; font-weight: 700; }
.pick { display: flex; align-items: center; padding: 28rpx; margin-bottom: 20rpx; }
.pick-cover {
  width: 96rpx; height: 96rpx; border-radius: 16rpx; margin-right: 24rpx; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 700; font-size: 28rpx;
}
.pick-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.pick-title { font-size: 30rpx; font-weight: 700; margin-bottom: 8rpx; }
.pick-sub { font-size: 25rpx; color: $tt-text-2; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
</style>
