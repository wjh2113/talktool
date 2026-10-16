<template>
  <view v-if="s" class="page">
    <!-- 概要 -->
    <view class="card summary">
      <text class="s-title">{{ s.drill.title }}</text>
      <view class="s-meta">
        <text class="tag">{{ s.drill.pressure_level }}训练</text>
        <text v-if="s.drill.is_custom" class="tag tag-gray">自定义</text>
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
          <text v-if="totalDelta !== null" class="delta" :class="deltaClass(totalDelta)">{{ deltaText(totalDelta) }}</text>
        </view>
        <text v-if="s.previous" class="prev-line">上次 {{ s.previous.total_score }} 分 · {{ s.previous.started_at.slice(5, 16) }}</text>
        <text class="total-sum">{{ r.summary }}</text>
        <view class="dims">
          <view v-for="(v, k) in r.scores" :key="k" class="dim">
            <text class="dim-k">{{ k }}</text>
            <view class="bar">
              <view v-if="prevScore(k) !== null" class="bar-prev" :style="{ width: prevScore(k) * 10 + '%' }" />
              <view class="bar-in" :style="{ width: v * 10 + '%' }" />
            </view>
            <text class="dim-v">{{ v }}</text>
            <text class="dim-d" :class="deltaClass(dimDelta(k, v))">{{ dimDelta(k, v) === null ? '' : deltaText(dimDelta(k, v)) }}</text>
          </view>
        </view>
        <view v-if="s.previous" class="legend">
          <view class="lg"><view class="lg-dot now" /><text>本次</text></view>
          <view class="lg"><view class="lg-dot prev" /><text>上次</text></view>
        </view>
      </view>
    </block>

    <!-- 表达数据（不依赖大模型，只要说过话就有） -->
    <view v-if="m && m.turns" class="card block">
      <text class="block-title">表达数据</text>
      <view class="metrics">
        <view class="mt">
          <text class="mt-v">{{ m.rate || '--' }}<text class="mt-u"> 字/分</text></text>
          <text class="mt-k">语速 <text v-if="m.rate_level" :class="'lv ' + levelClass(m.rate_level)">{{ m.rate_level }}</text></text>
        </view>
        <view class="mt">
          <text class="mt-v">{{ m.reaction_ms == null ? '--' : (m.reaction_ms / 1000).toFixed(1) }}<text class="mt-u"> 秒</text></text>
          <text class="mt-k">开口反应 <text v-if="m.reaction_level" :class="'lv ' + levelClass(m.reaction_level)">{{ m.reaction_level }}</text></text>
        </view>
        <view class="mt">
          <text class="mt-v">{{ m.filler_total }}<text class="mt-u"> 次</text></text>
          <text class="mt-k">口头禅</text>
        </view>
        <view class="mt">
          <text class="mt-v">{{ m.pauses }}<text class="mt-u"> 次</text></text>
          <text class="mt-k">长停顿（≥0.8 秒）</text>
        </view>
      </view>
      <view v-if="m.filler_top && m.filler_top.length" class="fillers">
        <text class="muted">高频口头禅：</text>
        <text v-for="f in m.filler_top" :key="f.word" class="filler">“{{ f.word }}” × {{ f.count }}</text>
      </view>
      <text class="muted metric-foot">共发言 {{ m.turns }} 次 · {{ m.chars }} 字 · 有效说话 {{ m.speech_sec }} 秒。参考：日常对话 140–270 字/分较舒适。</text>
    </view>

    <block v-if="s.status === 'completed' && r">
      <!-- 逐句复盘 + 示范 + 跟读 -->
      <view v-if="r.turn_reviews && r.turn_reviews.length" class="card block">
        <text class="block-title">逐句复盘</text>
        <view v-for="tr in r.turn_reviews" :key="tr.turn" class="review">
          <text v-if="contextOf(tr.turn)" class="ctx">对方：{{ contextOf(tr.turn) }}</text>
          <view class="said">
            <text class="said-label">我说</text>
            <text class="said-txt">{{ tr.user_text }}</text>
          </view>
          <text v-if="turnMetricText(tr.turn)" class="turn-metric">{{ turnMetricText(tr.turn) }}</text>
          <view class="better">
            <view class="better-head">
              <text class="better-label">更好的说法</text>
              <text class="star" :class="{ on: isSaved(tr.better) }" @tap="toggleSave('phrase', tr.better, tr.user_text)">
                {{ isSaved(tr.better) ? '★ 已收藏' : '☆ 收藏' }}
              </text>
            </view>
            <text class="better-txt">{{ tr.better }}</text>
            <text v-if="tr.tip" class="better-tip">💡 {{ tr.tip }}</text>
            <ReadAloud :text="tr.better" :note-id="savedId(tr.better)" />
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
          <text class="star small" :class="{ on: isSaved(h) }" @tap="toggleSave('tip', h, '')">{{ isSaved(h) ? '★' : '☆' }}</text>
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
import ReadAloud from '../../components/ReadAloud/ReadAloud.vue'

const s = ref(null)
const from = ref('')
const showTranscript = ref(false)
const saved = ref({}) // text -> note id

const r = computed(() => s.value && s.value.report)
const m = computed(() => s.value && s.value.metrics)
const userTurns = computed(() => (s.value ? s.value.transcript.filter((t) => t.role === 'user').length : 0))
const totalDelta = computed(() =>
  r.value && s.value.previous ? r.value.total_score - s.value.previous.total_score : null
)

// 第 n 句用户发言，及它前面那句 AI 的话
const userEntries = computed(() => {
  const out = []
  if (!s.value) return out
  let lastAi = ''
  s.value.transcript.forEach((t) => {
    if (t.role === 'ai') lastAi = t.text
    else out.push({ ...t, context: lastAi })
  })
  return out
})
const contextOf = (turn) => (userEntries.value[turn - 1] || {}).context || ''
function turnMetricText(turn) {
  const mm = (userEntries.value[turn - 1] || {}).metrics
  if (!mm) return ''
  const parts = []
  if (mm.rate) parts.push(`语速 ${mm.rate} 字/分`)
  if (mm.reaction_ms != null) parts.push(`反应 ${(mm.reaction_ms / 1000).toFixed(1)} 秒`)
  if (mm.pauses) parts.push(`长停顿 ${mm.pauses} 次`)
  const f = Object.keys(mm.fillers || {})
  if (f.length) parts.push('口头禅 ' + f.map((k) => `${k}×${mm.fillers[k]}`).join(' '))
  return parts.join(' · ')
}

const prevScore = (k) => (s.value.previous && s.value.previous.scores[k] != null ? s.value.previous.scores[k] : null)
const dimDelta = (k, v) => (prevScore(k) === null ? null : v - prevScore(k))
const deltaText = (d) => (d > 0 ? `↑${d}` : d < 0 ? `↓${-d}` : '持平')
const deltaClass = (d) => (d === null ? '' : d > 0 ? 'up' : d < 0 ? 'down' : 'flat')
const levelClass = (lv) => (lv === '适中' || lv === '迅速' || lv === '正常' ? 'good' : 'warn')

const isSaved = (text) => !!saved.value[text]
const savedId = (text) => saved.value[text] || null

async function toggleSave(kind, text, source) {
  const id = saved.value[text]
  if (id) {
    await api.deleteNote(id)
    const next = { ...saved.value }
    delete next[text]
    saved.value = next
    uni.showToast({ title: '已取消收藏', icon: 'none' })
  } else {
    const n = await api.addNote({ kind, text, source_text: source, session_id: s.value.id })
    saved.value = { ...saved.value, [text]: n.id }
    uni.showToast({ title: '已收进练习本', icon: 'none' })
  }
}

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
  const map = {}
  ;(s.value.saved_notes || []).forEach((n) => (map[n.text] = n.id))
  saved.value = map
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx 32rpx calc(40rpx + env(safe-area-inset-bottom)); box-sizing: border-box; }
.summary { padding: 36rpx; display: flex; flex-direction: column; margin-bottom: 28rpx; }
.s-title { font-size: 34rpx; font-weight: 700; line-height: 1.5; margin-bottom: 20rpx; }
.s-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 20rpx; margin-bottom: 20rpx; }
.meta-txt { font-size: 26rpx; color: $tt-text-2; }
.score-card { padding: 40rpx 36rpx; margin-bottom: 28rpx; display: flex; flex-direction: column; align-items: center; }
.total { display: flex; align-items: baseline; }
.total-num { font-size: 96rpx; font-weight: 800; color: $tt-primary; line-height: 1.1; }
.total-unit { font-size: 28rpx; color: $tt-primary; margin-left: 8rpx; }
.delta { font-size: 28rpx; font-weight: 700; margin-left: 18rpx; padding: 4rpx 14rpx; border-radius: 20rpx; }
.up { color: #22A060; background: #E7F7EE; }
.down { color: #E5484D; background: #FDECEC; }
.flat { color: $tt-text-3; background: #F0F2F5; }
.prev-line { font-size: 24rpx; color: $tt-text-3; margin-top: 8rpx; }
.total-sum { font-size: 28rpx; color: $tt-text-2; margin: 16rpx 0 36rpx; text-align: center; }
.dims { width: 100%; }
.dim { display: flex; align-items: center; margin-bottom: 22rpx; }
.dim-k { width: 140rpx; font-size: 26rpx; color: #4A4F57; }
.bar { position: relative; flex: 1; height: 16rpx; background: #EEF2F7; border-radius: 8rpx; overflow: hidden; }
.bar-prev { position: absolute; left: 0; top: 0; height: 100%; background: #C9D3DF; border-radius: 8rpx; }
.bar-in { position: relative; height: 100%; background: $tt-primary; border-radius: 8rpx; opacity: 0.92; }
.dim-v { width: 50rpx; text-align: right; font-size: 28rpx; font-weight: 700; color: $tt-text; }
.dim-d { width: 76rpx; text-align: right; font-size: 22rpx; background: transparent; padding: 0; }
.legend { display: flex; gap: 28rpx; align-self: flex-end; font-size: 22rpx; color: $tt-text-3; }
.lg { display: flex; align-items: center; }
.lg-dot { width: 18rpx; height: 18rpx; border-radius: 4rpx; margin-right: 8rpx; }
.lg-dot.now { background: $tt-primary; }
.lg-dot.prev { background: #C9D3DF; }
.block { padding: 36rpx; margin-bottom: 28rpx; }
.block-title { display: block; font-size: 30rpx; font-weight: 700; margin-bottom: 20rpx; }
.no-mb { margin-bottom: 0; }
.metrics { display: flex; flex-wrap: wrap; margin: 0 -10rpx; }
.mt { width: 50%; padding: 10rpx; box-sizing: border-box; display: flex; flex-direction: column; }
.mt-v { font-size: 44rpx; font-weight: 800; color: $tt-text; }
.mt-u { font-size: 22rpx; font-weight: 400; color: $tt-text-3; }
.mt-k { font-size: 24rpx; color: $tt-text-2; margin-top: 4rpx; }
.lv { font-size: 22rpx; padding: 2rpx 10rpx; border-radius: 8rpx; margin-left: 6rpx; }
.lv.good { background: #E7F7EE; color: #22A060; }
.lv.warn { background: #FFF4E5; color: #E68A1A; }
.fillers { margin-top: 18rpx; display: flex; flex-wrap: wrap; align-items: center; gap: 12rpx; }
.filler { font-size: 24rpx; color: #E68A1A; background: #FFF4E5; padding: 4rpx 14rpx; border-radius: 10rpx; }
.metric-foot { display: block; margin-top: 18rpx; line-height: 1.6; }
.review { padding: 24rpx 0; border-top: 1rpx solid #EEF1F5; &:first-of-type { border-top: none; padding-top: 0; } }
.ctx { display: block; font-size: 24rpx; color: $tt-text-3; line-height: 1.6; margin-bottom: 12rpx; }
.said { display: flex; }
.said-label { flex-shrink: 0; font-size: 22rpx; color: $tt-text-3; background: #F0F2F5; border-radius: 8rpx; padding: 2rpx 10rpx; margin: 4rpx 14rpx 0 0; height: 34rpx; line-height: 34rpx; }
.said-txt { flex: 1; font-size: 27rpx; line-height: 1.65; color: #4A4F57; }
.turn-metric { display: block; font-size: 22rpx; color: $tt-text-3; margin: 8rpx 0 0 72rpx; }
.better { margin-top: 18rpx; padding: 22rpx 24rpx; border-radius: 16rpx; background: #F4F9FF; border: 1rpx solid #DCEBFC; }
.better-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10rpx; }
.better-label { font-size: 24rpx; color: $tt-primary; font-weight: 600; }
.better-txt { display: block; font-size: 29rpx; line-height: 1.7; color: $tt-text; }
.better-tip { display: block; font-size: 24rpx; color: $tt-text-2; margin-top: 10rpx; }
.star { font-size: 24rpx; color: $tt-text-3; &.on { color: #E6A23C; } }
.star.small { font-size: 34rpx; margin-left: 12rpx; }
.item { display: flex; align-items: flex-start; margin-bottom: 18rpx; }
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
