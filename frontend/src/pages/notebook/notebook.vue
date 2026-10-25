<template>
  <view class="page">
    <view class="filters">
      <view v-for="f in filters" :key="f.key" class="filter" :class="{ on: kind === f.key }" @tap="setKind(f.key)">
        {{ f.label }}
      </view>
    </view>

    <view v-for="n in items" :key="n.id" class="card note">
      <view class="note-head">
        <text class="kind" :class="n.kind">{{ KIND_TEXT[n.kind] }}</text>
        <text v-if="n.best_score != null" class="best">跟读最高 {{ n.best_score }} 分</text>
        <text class="del" @tap="remove(n)">删除</text>
      </view>
      <text class="note-txt">{{ n.text }}</text>
      <text v-if="n.source_text" class="source">原话：{{ n.source_text }}</text>
      <view class="note-foot">
        <text class="muted">{{ n.drill_title || '训练' }} · {{ n.created_at.slice(0, 10) }}</text>
        <text v-if="n.drill_id" class="link" @tap="openDrill(n)">去练这个场景 ›</text>
      </view>
      <ReadAloud v-if="n.kind !== 'tip' && n.kind !== 'plan'" :text="n.text" :note-id="n.id" :best="n.best_score" @scored="onScored(n, $event)" />
    </view>

    <view v-if="!loading && !items.length" class="card empty">
      <text class="empty-title">练习本还是空的</text>
      <text class="empty-sub">在训练报告的“逐句复盘”里点 ☆ 收藏更好的说法，或在跟读模式里收藏示范稿，之后可以在这里反复跟读。</text>
      <view class="btn-primary go" @tap="goScenes">去训练</view>
    </view>
    <view v-else-if="loading" class="more muted">加载中…</view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow, onPullDownRefresh } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import ReadAloud from '../../components/ReadAloud/ReadAloud.vue'

const KIND_TEXT = { phrase: '话术', tip: '建议', script: '示范稿', plan: '锦囊' }
const filters = [
  { key: '', label: '全部' },
  { key: 'phrase', label: '话术' },
  { key: 'tip', label: '建议' },
  { key: 'script', label: '示范稿' },
  { key: 'plan', label: '锦囊' }
]
const kind = ref('')
const items = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = await api.notes(kind.value)
  } finally {
    loading.value = false
    uni.stopPullDownRefresh()
  }
}

function setKind(k) {
  if (kind.value === k) return
  kind.value = k
  load()
}

function remove(n) {
  uni.showModal({
    title: '删除这条收藏？',
    success: async (r) => {
      if (!r.confirm) return
      await api.deleteNote(n.id)
      items.value = items.value.filter((x) => x.id !== n.id)
    }
  })
}

function onScored(n, res) {
  if (typeof res.score === 'number') n.best_score = Math.max(n.best_score || 0, res.score)
}

const openDrill = (n) => uni.navigateTo({ url: `/pages/drill/drill?id=${n.drill_id}` })
const goScenes = () => uni.switchTab({ url: '/pages/scenes/scenes' })

onShow(load)
onPullDownRefresh(load)
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx; box-sizing: border-box; }
.filters { display: flex; gap: 18rpx; margin-bottom: 28rpx; }
.filter {
  padding: 0 28rpx; height: 68rpx; line-height: 68rpx; border-radius: 14rpx;
  background: #fff; border: 1rpx solid #E3E7ED; font-size: 28rpx;
  &.on { background: $tt-primary; border-color: $tt-primary; color: #fff; font-weight: 600; }
}
.note { padding: 32rpx; margin-bottom: 24rpx; }
.note-head { display: flex; align-items: center; margin-bottom: 16rpx; }
.kind {
  font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 8rpx; background: $tt-tag-bg; color: $tt-primary;
  &.tip { background: #FFF4E5; color: #E68A1A; }
  &.script { background: #E7F7EE; color: #22A060; }
  &.plan { background: #EEF0FF; color: #5B5BD6; }
}
.best { font-size: 22rpx; color: $tt-text-3; margin-left: 16rpx; }
.del { margin-left: auto; font-size: 24rpx; color: $tt-text-3; }
.note-txt { display: block; font-size: 30rpx; line-height: 1.75; color: $tt-text; }
.source { display: block; font-size: 24rpx; color: $tt-text-3; line-height: 1.6; margin-top: 12rpx; }
.note-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 16rpx; }
.link { font-size: 24rpx; color: $tt-primary; }
.empty { padding: 70rpx 44rpx; display: flex; flex-direction: column; align-items: center; text-align: center; }
.empty-title { font-size: 34rpx; font-weight: 700; margin-bottom: 20rpx; }
.empty-sub { font-size: 27rpx; color: $tt-text-2; line-height: 1.7; margin-bottom: 40rpx; }
.go { width: 320rpx; }
.more { text-align: center; padding: 40rpx 0; }
</style>
