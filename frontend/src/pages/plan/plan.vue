<template>
  <view v-if="p" class="page">
    <view class="head">
      <view class="head-top">
        <text class="head-council">{{ c.council ? c.council.icon + ' ' + c.council.name : '智囊团' }}</text>
        <view v-if="p.versions.length > 1" class="vers">
          <text v-for="v in p.versions" :key="v" class="ver" :class="{ on: v === p.version }" @tap="loadVersion(v)">v{{ v }}</text>
        </view>
      </view>
      <text class="headline">{{ k.headline }}</text>
      <text class="head-title">{{ c.title }}</text>
    </view>

    <text class="block-title">局势研判</text>
    <view class="card box">
      <text class="txt">{{ k.situation }}</text>
      <view v-if="k.their_concerns" class="concern">
        <text class="concern-k">对方的顾虑</text>
        <text class="txt">{{ k.their_concerns }}</text>
      </view>
    </view>

    <template v-if="k.goal && (k.goal.best || k.goal.bottom)">
      <text class="block-title">目标与底线</text>
      <view class="card box goals">
        <view class="goal"><text class="goal-k best">最好</text><text class="txt">{{ k.goal.best }}</text></view>
        <view class="goal"><text class="goal-k ok">可接受</text><text class="txt">{{ k.goal.acceptable }}</text></view>
        <view class="goal"><text class="goal-k bottom">底线</text><text class="txt">{{ k.goal.bottom }}</text></view>
      </view>
    </template>

    <template v-if="k.strategies.length">
      <text class="block-title">用哪几计</text>
      <view v-for="s in k.strategies" :key="s.code" class="card box strat" @tap="openStrategy(s.code)">
        <view class="strat-head">
          <text class="strat-school">{{ s.school_name }}</text>
          <text class="strat-name">{{ s.name || s.code }}</text>
          <text v-if="s.caution" class="caution">慎用</text>
          <text class="chevron">›</text>
        </view>
        <text v-if="s.origin" class="origin">{{ s.origin }}</text>
        <text class="txt">{{ s.use }}</text>
      </view>
    </template>

    <text class="block-title">怎么做</text>
    <view class="card box">
      <view v-for="a in p.actions" :key="a.id" class="action">
        <view class="check" :class="{ on: a.done }" @tap="toggle(a)"><text v-if="a.done">✓</text></view>
        <view class="action-body">
          <text class="action-text" :class="{ done: a.done }">{{ a.text }}</text>
          <view class="action-meta">
            <text v-if="a.due_hint" class="muted">{{ a.due_hint }}</text>
            <picker v-if="!a.done" mode="date" :value="a.remind_at || today" :start="today" @change="(e) => setRemind(a, e.detail.value)">
              <text class="remind" :class="{ on: a.remind_at }">{{ a.remind_at ? '⏰ ' + a.remind_at.slice(5) + ' 提醒' : '⏰ 设提醒' }}</text>
            </picker>
            <text v-if="a.remind_at && !a.done" class="remind-x" @tap="setRemind(a, '')">取消</text>
          </view>
          <text v-if="a.result" class="action-result">结果：{{ a.result }}</text>
          <text v-else-if="a.done" class="link small" @tap="writeResult(a)">写一句结果</text>
        </view>
      </view>
    </view>

    <text class="block-title">怎么说</text>
    <view v-for="(ln, i) in k.lines" :key="i" class="card box line">
      <view class="line-head">
        <text class="moment">{{ ln.moment || '关键时刻' }}</text>
        <text v-if="ln.framework" class="fw-chip" @tap="openFramework(ln.framework)">{{ ln.framework_name || ln.framework }} ›</text>
      </view>
      <text class="say">“{{ ln.text }}”</text>
      <text v-if="ln.why" class="why">{{ ln.why }}</text>
      <ReadAloud :text="ln.text.slice(0, 480)" />
      <text class="link small" @tap="save(ln.text, 'phrase', ln.moment)">{{ saved[ln.text] ? '✓ 已收藏' : '＋ 收藏到练习本' }}</text>
    </view>

    <template v-if="k.risks.length">
      <text class="block-title">如果……就……</text>
      <view class="card box">
        <view v-for="(r, i) in k.risks" :key="i" class="risk">
          <text class="risk-if">如果{{ r.if }}</text>
          <text class="txt">→ {{ r.then }}</text>
        </view>
      </view>
    </template>

    <template v-if="k.donts.length">
      <text class="block-title">不要做</text>
      <view class="card box">
        <view v-for="(d, i) in k.donts" :key="i" class="dont"><text class="x">✕</text><text class="txt">{{ d }}</text></view>
      </view>
    </template>

    <template v-if="k.advisor_views.length">
      <view class="block-row">
        <text class="block-title inline">各位谋士怎么看</text>
        <text class="link" @tap="debate">让他们辩一辩 ›</text>
      </view>
      <view class="card box">
        <view v-for="v in k.advisor_views" :key="v.advisor" class="view">
          <text class="view-avatar">{{ v.avatar }}</text>
          <view class="view-body">
            <text class="view-name">{{ v.name }}</text>
            <text class="txt">{{ v.view }}</text>
          </view>
        </view>
      </view>
    </template>

    <view class="card box rate">
      <text class="rate-q">这份锦囊对你有用吗？</text>
      <view class="rate-btns">
        <text class="rate-btn" :class="{ on: p.rating === 1 }" @tap="rate(1)">👍 有用</text>
        <text class="rate-btn bad" :class="{ on: p.rating === -1 }" @tap="rate(-1)">👎 没用</text>
      </view>
      <text v-if="p.rating === -1 && p.rating_reason" class="muted">你说：{{ p.rating_reason }}</text>
      <text v-if="c.follow_up_at" class="muted follow">智囊会在 {{ c.follow_up_at.slice(5, 10) }} 提醒你回来复盘</text>
    </view>

    <view v-if="p.memory_refs.length" class="refs">
      <text>参考了：{{ p.memory_refs.map((r) => r.label).join('、') }}</text>
    </view>
    <text class="disclaimer">智囊建议仅供参考，重要决定请结合实际情况{{ c.council && c.council.code === 'finance' ? '；不构成投资建议' : '' }}。</text>

    <view class="footer">
      <view class="btn-plain" @tap="ask">继续问</view>
      <view class="btn-plain" @tap="savePlan">{{ planSaved ? '已收藏' : '收藏锦囊' }}</view>
      <view class="btn-primary go" @tap="rehearse">去演练</view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import ReadAloud from '../../components/ReadAloud/ReadAloud.vue'

const c = ref(null)
const p = ref(null)
const saved = ref({})
const planSaved = ref(false)
let cid = 0
let version = 0

const k = computed(() => (p.value ? p.value.content : {}))
const pad = (n) => String(n).padStart(2, '0')
const d0 = new Date()
const today = `${d0.getFullYear()}-${pad(d0.getMonth() + 1)}-${pad(d0.getDate())}`

async function setRemind(a, date) {
  const old = a.remind_at
  a.remind_at = date || null
  try {
    await api.updateAction(a.id, { remind_at: date || '' })
    if (date) uni.showToast({ title: `${date.slice(5)} 会在智囊页提醒你`, icon: 'none' })
  } catch (e) {
    a.remind_at = old
  }
}

async function rate(v) {
  const next = p.value.rating === v ? 0 : v
  let reason = ''
  if (next === -1) {
    reason = await new Promise((resolve) => uni.showModal({
      title: '哪里没帮上忙？',
      editable: true,
      placeholderText: '例如：太空泛 / 不符合我的情况 / 话术太生硬（可不填）',
      success: (r) => resolve(r.confirm ? (r.content || '').trim() : null)
    }))
    if (reason === null) return
  }
  await api.ratePlan(p.value.id, next, reason)
  p.value.rating = next || null
  p.value.rating_reason = reason
  uni.showToast({ title: next === 1 ? '谢谢反馈' : next === -1 ? '收到，智囊会改进' : '已撤销', icon: 'none' })
  if (next === -1) {
    uni.showModal({
      title: '换个角度试试？',
      content: '可以回到对话里说说你的真实情况，让智囊调整锦囊，或者开一场圆桌会议听听不同意见。',
      confirmText: '去调整',
      cancelText: '先不用',
      success: (r) => r.confirm && ask()
    })
  }
}

function debate() {
  uni.redirectTo({ url: `/pages/consult/consult?id=${cid}&roundtable=1` })
}

async function load() {
  c.value = await api.consult(cid, version || undefined)
  p.value = c.value.plan
}

function loadVersion(v) {
  version = v
  load()
}

async function toggle(a) {
  const done = !a.done
  a.done = done
  try {
    await api.updateAction(a.id, { done })
    if (done) uni.showToast({ title: '已记到事件线', icon: 'none' })
  } catch (e) {
    a.done = !done
  }
}

function writeResult(a) {
  uni.showModal({
    title: '这一步的结果',
    editable: true,
    placeholderText: '例如：约上了，周三聊',
    success: async (r) => {
      if (r.confirm && r.content) {
        await api.updateAction(a.id, { done: true, result: r.content })
        a.result = r.content
      }
    }
  })
}

async function save(text, kind, source) {
  if (saved.value[text]) return
  await api.addNote({ kind, text, source_text: `锦囊 · ${c.value.title}${source ? ' · ' + source : ''}` })
  saved.value = { ...saved.value, [text]: true }
  uni.showToast({ title: '已收藏到练习本', icon: 'none' })
}

function planText() {
  const x = k.value
  const parts = [`【${c.value.title}】${x.headline}`]
  if (p.value.actions.length) parts.push('怎么做：' + p.value.actions.map((a, i) => `${i + 1}. ${a.text}`).join(' '))
  if (x.lines.length) parts.push('怎么说：' + x.lines.map((l) => `${l.moment}：“${l.text}”`).join(' '))
  if (x.donts.length) parts.push('不要做：' + x.donts.join('；'))
  return parts.join('\n').slice(0, 1900)
}

async function savePlan() {
  if (planSaved.value) return
  await api.addNote({ kind: 'plan', text: planText(), source_text: `锦囊 v${p.value.version}` })
  planSaved.value = true
  uni.showToast({ title: '已收藏到练习本', icon: 'none' })
}

function ask() {
  uni.navigateBack({ fail: () => uni.redirectTo({ url: `/pages/consult/consult?id=${cid}` }) })
}

async function rehearse() {
  uni.showLoading({ title: '生成演练场景', mask: true })
  try {
    const d = await api.rehearse(cid)
    uni.hideLoading()
    uni.navigateTo({ url: `/pages/drill/drill?id=${d.id}` })
  } catch (e) {
    uni.hideLoading()
  }
}

const openStrategy = (code) => uni.navigateTo({ url: `/pages/strategy/strategy?code=${code}` })
const openFramework = (code) => uni.navigateTo({ url: `/pages/framework/framework?key=${code}` })

onLoad((q) => {
  cid = q.id
  version = Number(q.version) || 0
  load()
})
onShow(() => {
  if (p.value) load().catch(() => {})
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding-bottom: 200rpx; }
.head { background: linear-gradient(135deg, $tt-hero-from, $tt-hero-to); padding: 36rpx 40rpx 48rpx; display: flex; flex-direction: column; color: #fff; }
.head-top { display: flex; align-items: center; justify-content: space-between; }
.head-council { font-size: 25rpx; opacity: 0.85; }
.vers { display: flex; gap: 10rpx; }
.ver { font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 16rpx; background: rgba(255, 255, 255, 0.18); }
.ver.on { background: #fff; color: $tt-primary-deep; }
.headline { font-size: 38rpx; font-weight: 800; line-height: 1.5; margin-top: 16rpx; }
.head-title { font-size: 24rpx; opacity: 0.8; margin-top: 12rpx; }
.block-title { display: block; font-size: 31rpx; font-weight: 700; margin: 36rpx 32rpx 18rpx; }
.box { margin: 0 32rpx 18rpx; padding: 28rpx 32rpx; display: flex; flex-direction: column; }
.txt { font-size: 27rpx; line-height: 1.8; color: $tt-text; flex: 1; }
.concern { margin-top: 18rpx; background: $tt-bg; border-radius: 12rpx; padding: 16rpx 20rpx; display: flex; flex-direction: column; }
.concern-k { font-size: 22rpx; color: $tt-text-3; margin-bottom: 4rpx; }
.goals { gap: 14rpx; }
.goal { display: flex; align-items: flex-start; gap: 16rpx; }
.goal-k { flex-shrink: 0; width: 96rpx; text-align: center; font-size: 22rpx; padding: 4rpx 0; border-radius: 8rpx; margin-top: 6rpx; }
.goal-k.best { background: $tt-tag-bg; color: $tt-primary; }
.goal-k.ok { background: #FFF6E5; color: #B7791F; }
.goal-k.bottom { background: #FDECEA; color: #C0392B; }
.strat-head { display: flex; align-items: center; gap: 12rpx; margin-bottom: 10rpx; }
.strat-school { font-size: 22rpx; color: $tt-primary; background: $tt-tag-bg; padding: 2rpx 12rpx; border-radius: 6rpx; }
.strat-name { font-size: 29rpx; font-weight: 700; flex: 1; }
.caution { font-size: 20rpx; color: #C0392B; border: 1rpx solid #E8A39B; padding: 0 10rpx; border-radius: 6rpx; }
.chevron { color: $tt-text-3; }
.origin { font-size: 24rpx; color: $tt-text-3; line-height: 1.7; margin-bottom: 8rpx; font-style: italic; }
.action { display: flex; gap: 18rpx; padding: 14rpx 0; border-bottom: 1rpx solid #F0F2F1; }
.action:last-child { border-bottom: none; }
.check {
  width: 40rpx; height: 40rpx; border-radius: 10rpx; border: 2rpx solid $tt-soft-border; flex-shrink: 0; margin-top: 4rpx;
  display: flex; align-items: center; justify-content: center; color: #fff; font-size: 24rpx;
}
.check.on { background: $tt-primary; border-color: $tt-primary; }
.action-body { flex: 1; display: flex; flex-direction: column; gap: 4rpx; }
.action-text { font-size: 28rpx; line-height: 1.6; }
.action-text.done { color: $tt-text-3; text-decoration: line-through; }
.action-result { font-size: 24rpx; color: $tt-primary; }
.link { color: $tt-primary; font-size: 26rpx; }
.link.small { font-size: 24rpx; margin-top: 10rpx; }
.line-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10rpx; }
.moment { font-size: 23rpx; color: $tt-text-3; }
.fw-chip { font-size: 22rpx; color: $tt-primary; background: $tt-tag-bg; padding: 4rpx 14rpx; border-radius: 16rpx; }
.say { font-size: 30rpx; font-weight: 600; line-height: 1.7; color: $tt-text; }
.why { font-size: 24rpx; color: $tt-text-2; margin-top: 8rpx; line-height: 1.6; }
.risk { padding: 10rpx 0; display: flex; flex-direction: column; }
.risk-if { font-size: 26rpx; font-weight: 600; }
.dont { display: flex; gap: 12rpx; padding: 6rpx 0; }
.x { color: #E5564B; font-size: 24rpx; line-height: 1.9; }
.view { display: flex; gap: 18rpx; padding: 12rpx 0; }
.view-avatar { width: 56rpx; height: 56rpx; line-height: 56rpx; text-align: center; border-radius: 50%; background: $tt-primary; color: #fff; font-weight: 700; flex-shrink: 0; }
.view-body { flex: 1; display: flex; flex-direction: column; }
.view-name { font-size: 25rpx; font-weight: 700; }
.refs { margin: 24rpx 32rpx 0; font-size: 23rpx; color: $tt-text-3; }
.action-meta { display: flex; align-items: center; gap: 18rpx; flex-wrap: wrap; }
.remind { font-size: 22rpx; color: $tt-text-3; padding: 2rpx 12rpx; border-radius: 16rpx; background: $tt-bg; }
.remind.on { color: #B7791F; background: #FFF6E5; }
.remind-x { font-size: 22rpx; color: $tt-text-3; }
.block-row { display: flex; align-items: center; justify-content: space-between; margin: 36rpx 32rpx 18rpx; }
.block-title.inline { margin: 0; }
.rate { margin-top: 36rpx; gap: 14rpx; }
.rate-q { font-size: 28rpx; font-weight: 700; }
.rate-btns { display: flex; gap: 20rpx; }
.rate-btn { flex: 1; text-align: center; font-size: 27rpx; padding: 16rpx 0; border-radius: 14rpx; background: $tt-bg; color: $tt-text-2; }
.rate-btn.on { background: $tt-primary; color: #fff; }
.rate-btn.bad.on { background: #E5564B; }
.follow { margin-top: 4rpx; }
.disclaimer { display: block; margin: 12rpx 32rpx; font-size: 22rpx; color: $tt-text-3; }
.footer {
  position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 16rpx; background: #fff;
  padding: 20rpx 32rpx calc(20rpx + env(safe-area-inset-bottom)); box-shadow: 0 -4rpx 20rpx rgba(0, 0, 0, 0.04);
}
.footer .btn-plain { width: 180rpx; flex-shrink: 0; }
.footer .go { flex: 1; }
</style>
