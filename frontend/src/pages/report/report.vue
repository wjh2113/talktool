<template>
  <view v-if="s" class="page">
    <!-- 概要 -->
    <view class="card summary">
      <text class="s-title">{{ s.drill.title }}</text>
      <view class="s-meta">
        <text class="tag">{{ s.drill.pressure_level }}训练</text>
        <text class="meta-txt">{{ durationText(s.duration_sec) }}</text>
        <text class="meta-txt">{{ s.status === 'in_progress' ? '训练进行中' : '已完成训练' }}</text>
      </view>
      <text class="muted">{{ s.started_at }}</text>
    </view>

    <!-- 正常报告 -->
    <block v-if="s.status === 'completed' && r">
      <view class="card score-card">
        <view class="total">
          <text class="total-num">{{ r.total_score }}</text>
          <text class="total-unit">分</text>
        </view>
        <text class="total-sum">{{ r.summary }}</text>
        <view class="dims">
          <view v-for="(v, k) in r.scores" :key="k" class="dim">
            <text class="dim-k">{{ k }}</text>
            <view class="bar"><view class="bar-in" :style="{ width: v * 10 + '%' }" /></view>
            <text class="dim-v">{{ v }}</text>
          </view>
        </view>
      </view>

      <view v-if="r.highlights.length" class="card block">
        <text class="block-title">做得好的地方</text>
        <view v-for="(h, i) in r.highlights" :key="i" class="item">
          <text class="dot good">✓</text>
          <text class="item-txt">{{ h }}</text>
        </view>
      </view>

      <view v-if="r.improvements.length" class="card block">
        <text class="block-title">改进建议</text>
        <view v-for="(h, i) in r.improvements" :key="i" class="item">
          <text class="dot tip">{{ i + 1 }}</text>
          <text class="item-txt">{{ h }}</text>
        </view>
      </view>

      <view v-if="r.detail_comment" class="card block">
        <text class="block-title">详细点评</text>
        <rich-text :nodes="mdToHtml(r.detail_comment)" />
      </view>
    </block>

    <!-- 报告生成失败 -->
    <view v-else-if="s.status === 'completed'" class="card empty">
      <image class="empty-icon" src="/static/icons/clock.png" />
      <text class="empty-title">报告生成失败</text>
      <text class="empty-sub">网关暂时不可用，可以重新生成。</text>
      <view class="retry" @tap="retry">重新生成报告</view>
    </view>

    <!-- 时长过短 / 主动放弃 -->
    <view v-else class="card empty">
      <view class="empty-icon-wrap">
        <image class="empty-icon" :src="s.status === 'abandoned' ? '/static/icons/flag.png' : '/static/icons/clock.png'" />
      </view>
      <text class="empty-title">{{ s.status === 'abandoned' ? '主动放弃' : s.status === 'too_short' ? '时长过短' : '训练进行中' }}</text>
      <text class="empty-sub">{{ s.summary_line }}</text>
    </view>

    <!-- 对话回放 -->
    <view v-if="userTurns > 0" class="card block">
      <view class="replay-head" @tap="showTranscript = !showTranscript">
        <text class="block-title no-mb">对话回放（{{ s.transcript.length }} 句）</text>
        <text class="muted">{{ showTranscript ? '收起' : '展开' }}</text>
      </view>
      <view v-if="showTranscript" class="transcript">
        <view v-for="(t, i) in s.transcript" :key="i" class="line" :class="t.role">
          <text class="who">{{ t.role === 'ai' ? '对方' : '我' }}</text>
          <text class="bubble">{{ t.text }}</text>
        </view>
      </view>
    </view>

    <view class="actions">
      <view class="btn-plain" @tap="toRecords">返回训练记录</view>
      <view class="btn-primary again" @tap="again">再练一次</view>
    </view>
    <text class="disclaimer">本次结果仅反映这一次训练中的表现。</text>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { durationText, mdToHtml } from '../../utils/format'

const s = ref(null)
const from = ref('')
const showTranscript = ref(false)
const r = computed(() => s.value && s.value.report)
const userTurns = computed(() => (s.value ? s.value.transcript.filter((t) => t.role === 'user').length : 0))

async function retry() {
  uni.showLoading({ title: '生成中', mask: true })
  try {
    s.value = await api.retryReport(s.value.id)
  } finally {
    uni.hideLoading()
  }
}

function toRecords() {
  if (from.value === 'records') return uni.navigateBack()
  uni.redirectTo({ url: '/pages/records/records' })
}

function again() {
  uni.redirectTo({ url: `/pages/drill/drill?id=${s.value.drill_id}` })
}

onLoad(async (q) => {
  from.value = q.from || ''
  s.value = await api.session(q.id)
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx 32rpx calc(40rpx + env(safe-area-inset-bottom)); box-sizing: border-box; }
.summary { padding: 36rpx; display: flex; flex-direction: column; margin-bottom: 28rpx; }
.s-title { font-size: 34rpx; font-weight: 700; line-height: 1.5; margin-bottom: 20rpx; }
.s-meta { display: flex; align-items: center; gap: 24rpx; margin-bottom: 20rpx; }
.meta-txt { font-size: 26rpx; color: $tt-text-2; }
.score-card { padding: 40rpx 36rpx; margin-bottom: 28rpx; display: flex; flex-direction: column; align-items: center; }
.total { display: flex; align-items: baseline; }
.total-num { font-size: 96rpx; font-weight: 800; color: $tt-primary; line-height: 1.1; }
.total-unit { font-size: 28rpx; color: $tt-primary; margin-left: 8rpx; }
.total-sum { font-size: 28rpx; color: $tt-text-2; margin: 16rpx 0 36rpx; text-align: center; }
.dims { width: 100%; }
.dim { display: flex; align-items: center; margin-bottom: 22rpx; }
.dim-k { width: 140rpx; font-size: 26rpx; color: #4A4F57; }
.bar { flex: 1; height: 16rpx; background: #EEF2F7; border-radius: 8rpx; overflow: hidden; }
.bar-in { height: 100%; background: $tt-primary; border-radius: 8rpx; }
.dim-v { width: 50rpx; text-align: right; font-size: 28rpx; font-weight: 700; color: $tt-text; }
.block { padding: 36rpx; margin-bottom: 28rpx; }
.block-title { display: block; font-size: 30rpx; font-weight: 700; margin-bottom: 20rpx; }
.no-mb { margin-bottom: 0; }
.item { display: flex; margin-bottom: 18rpx; }
.dot {
  width: 40rpx; height: 40rpx; border-radius: 50%; flex-shrink: 0; margin-right: 18rpx;
  font-size: 22rpx; line-height: 40rpx; text-align: center; margin-top: 4rpx;
}
.good { background: #E7F7EE; color: #22A060; }
.tip { background: $tt-tag-bg; color: $tt-primary; }
.item-txt { flex: 1; font-size: 28rpx; line-height: 1.7; color: #333; }
.empty { padding: 70rpx 40rpx; display: flex; flex-direction: column; align-items: center; margin-bottom: 28rpx; }
.empty-icon-wrap {
  width: 120rpx; height: 120rpx; border-radius: 50%; background: $tt-tag-bg;
  display: flex; align-items: center; justify-content: center; margin-bottom: 36rpx;
}
.empty-icon { width: 64rpx; height: 64rpx; }
.empty-title { font-size: 34rpx; font-weight: 700; margin-bottom: 24rpx; }
.empty-sub { font-size: 27rpx; color: $tt-text-2; text-align: center; line-height: 1.6; }
.retry { margin-top: 32rpx; color: $tt-primary; font-size: 28rpx; }
.replay-head { display: flex; justify-content: space-between; align-items: center; }
.transcript { margin-top: 24rpx; }
.line { display: flex; margin-bottom: 20rpx; }
.who { width: 70rpx; flex-shrink: 0; font-size: 24rpx; color: $tt-text-3; padding-top: 14rpx; }
.bubble { flex: 1; padding: 14rpx 20rpx; border-radius: 14rpx; font-size: 27rpx; line-height: 1.65; background: #F3F6FA; }
.line.user .bubble { background: $tt-tag-bg; }
.actions { display: flex; gap: 24rpx; margin-top: 12rpx; }
.actions .btn-plain { flex: 1; }
.again { flex: 1; }
.disclaimer { display: block; text-align: center; font-size: 24rpx; color: $tt-text-3; margin-top: 32rpx; }
</style>
