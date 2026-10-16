<template>
  <view class="page">
    <view class="filters">
      <view
        v-for="f in filters"
        :key="f.key"
        class="filter"
        :class="{ on: range === f.key }"
        @tap="setRange(f.key)"
      >{{ f.label }}</view>
    </view>

    <view v-for="it in items" :key="it.id" class="card rec" @tap="open(it)">
      <view class="rec-top">
        <text class="rec-title ellipsis-2">{{ it.drill_title }}</text>
        <text class="badge" :class="it.status">{{ statusText(it) }}</text>
      </view>
      <text class="tag pressure">{{ it.pressure_level }}</text>
      <view class="rec-meta">
        <text>{{ it.started_at }}</text>
        <text v-if="it.status !== 'abandoned'" class="gap">训练 {{ durationText(it.duration_sec) }}</text>
      </view>
      <view class="divider" />
      <view class="rec-foot">
        <text class="foot-txt">{{ it.summary_line }}</text>
        <text class="link">查看报告 ›</text>
      </view>
    </view>

    <view v-if="!loading && !items.length" class="empty muted">
      还没有训练记录，去“场景”里开始第一次练习吧
    </view>
    <view v-else class="more muted">{{ loading ? '加载中…' : hasMore ? '上拉加载更多' : '没有更多记录了' }}</view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad, onPullDownRefresh, onReachBottom, onShow } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { durationText, STATUS_TEXT } from '../../utils/format'

const filters = [
  { key: 'all', label: '全部记录' },
  { key: 'week', label: '本周' },
  { key: 'month', label: '本月' }
]
const range = ref('all')
const items = ref([])
const page = ref(1)
const hasMore = ref(false)
const loading = ref(false)
let loaded = false

function statusText(it) {
  if (it.status === 'completed' && it.total_score != null) return it.total_score + ' 分'
  return STATUS_TEXT[it.status] || it.status
}

async function load(reset = true) {
  if (loading.value) return
  loading.value = true
  try {
    const p = reset ? 1 : page.value + 1
    const res = await api.sessions(range.value, p)
    items.value = reset ? res.items : items.value.concat(res.items)
    page.value = p
    hasMore.value = res.has_more
    loaded = true
  } finally {
    loading.value = false
    uni.stopPullDownRefresh()
  }
}

function setRange(k) {
  if (range.value === k) return
  range.value = k
  load(true)
}

function open(it) {
  uni.navigateTo({ url: `/pages/report/report?id=${it.id}&from=records` })
}

onLoad(() => load(true))
onShow(() => { if (loaded) load(true) })
onPullDownRefresh(() => load(true))
onReachBottom(() => { if (hasMore.value) load(false) })
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx; box-sizing: border-box; }
.filters { display: flex; gap: 20rpx; margin-bottom: 32rpx; }
.filter {
  padding: 0 34rpx;
  height: 76rpx;
  line-height: 76rpx;
  border-radius: 14rpx;
  background: #fff;
  border: 1rpx solid #E3E7ED;
  font-size: 30rpx;
  &.on { background: $tt-primary; border-color: $tt-primary; color: #fff; font-weight: 600; }
}
.rec { padding: 36rpx 36rpx 28rpx; margin-bottom: 28rpx; }
.rec-top { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22rpx; }
.rec-title { flex: 1; font-size: 34rpx; font-weight: 700; line-height: 1.5; margin-right: 20rpx; }
.badge {
  flex-shrink: 0;
  font-size: 24rpx;
  padding: 10rpx 20rpx;
  border-radius: 24rpx;
  background: #F0F2F5;
  color: $tt-text-2;
  &.completed { background: $tt-tag-bg; color: $tt-primary; }
  &.in_progress { background: #FFF4E5; color: #E68A1A; }
}
.pressure { margin-bottom: 22rpx; }
.rec-meta { font-size: 26rpx; color: $tt-text-3; display: flex; }
.gap { margin-left: 28rpx; }
.divider { height: 1rpx; background: #EEF1F5; margin: 26rpx 0 22rpx; }
.rec-foot { display: flex; align-items: center; justify-content: space-between; }
.foot-txt { flex: 1; font-size: 26rpx; color: #4A4F57; margin-right: 16rpx; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.link { color: $tt-primary; font-size: 27rpx; flex-shrink: 0; }
.empty { text-align: center; padding: 160rpx 40rpx; font-size: 28rpx; }
.more { text-align: center; padding: 20rpx 0 40rpx; font-size: 26rpx; }
</style>
