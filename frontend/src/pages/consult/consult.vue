<template>
  <view class="page">
    <view v-if="c && c.council" class="council-bar">
      <text class="cb-name">{{ c.council.icon }} {{ c.council.name }}</text>
      <view class="cb-avatars">
        <text v-for="a in c.council.advisors" :key="a.code" class="cb-avatar">{{ a.avatar }}</text>
        <text v-for="a in c.extra_advisors" :key="a.code" class="cb-avatar mine">{{ a.avatar }}</text>
      </view>
      <text class="cb-switch" @tap="openSeats">{{ c.extra_advisors && c.extra_advisors.length ? '列席' : '+谋士' }}</text>
      <text v-if="c.plan" class="cb-switch" @tap="showSwitch = true">换个团</text>
    </view>

    <scroll-view class="list" scroll-y :scroll-into-view="bottomId" scroll-with-animation>
      <view v-if="!c && !busy" class="empty muted">加载中…</view>
      <template v-if="c">
        <view v-for="m in c.messages" :id="'m' + m.id" :key="m.id" class="msg" :class="m.role">
          <!-- 用户 -->
          <view v-if="m.role === 'user'" class="bubble me">
            <text v-if="m.kind === 'review'" class="tag">复盘</text>
            <text v-if="m.kind === 'roundtable_ask'" class="tag">圆桌</text>
            <text>{{ m.text }}</text>
          </view>

          <!-- 分派 -->
          <view v-else-if="m.kind === 'route'" class="route">
            <text>{{ m.text }}</text>
            <view v-if="m.data.candidates && m.data.candidates.length > 1 && !c.plan" class="chips">
              <view v-for="code in m.data.candidates" :key="code" class="chip" @tap="plan(code)">{{ councilName(code) }}</view>
            </view>
          </view>

          <!-- 追问 -->
          <view v-else-if="m.kind === 'clarify'" class="bubble adv">
            <text class="adv-intro">{{ m.text }}</text>
            <view v-for="(q, qi) in m.data.questions" :key="qi" class="q">
              <text class="q-text">{{ qi + 1 }}. {{ q.q }}</text>
              <view class="chips">
                <view v-for="o in q.options" :key="o" class="chip" :class="{ on: picked[qi] === o }" @tap="pickOption(qi, q.q, o)">{{ o }}</view>
              </view>
            </view>
            <text v-if="c.status === 'clarifying'" class="skip" @tap="skip">跳过，直接出主意 ›</text>
          </view>

          <!-- 锦囊 -->
          <view v-else-if="m.kind === 'plan'" class="plan-card" @tap="openPlan(m.data.version)">
            <text class="plan-label">锦囊 v{{ m.data.version }}</text>
            <text class="plan-head">{{ m.text }}</text>
            <view class="plan-actions">
              <text class="link">打开锦囊 ›</text>
              <text class="link" @tap.stop="rehearse">去演练 ›</text>
              <text class="link" @tap.stop="roundtable('')">开圆桌 ›</text>
            </view>
          </view>

          <!-- 圆桌会议 -->
          <view v-else-if="m.kind === 'roundtable'" class="rt-card">
            <text class="rt-label">圆桌会议</text>
            <text v-if="m.data.question" class="rt-q">{{ m.data.question }}</text>
            <view v-for="(sp, i) in m.data.speeches" :key="i" class="rt-sp" :class="{ r2: sp.round === 2 }">
              <text class="rt-avatar">{{ sp.name.slice(0, 1) }}</text>
              <view class="rt-body">
                <text class="rt-name">{{ sp.name }}<text v-if="sp.reply_to_name" class="rt-reply">  反驳 {{ sp.reply_to_name }}</text></text>
                <text v-if="sp.stance" class="rt-stance">{{ sp.stance }}</text>
                <text class="rt-text">{{ sp.text }}</text>
              </view>
            </view>
            <view class="rt-verdict">
              <text class="rt-v-title">{{ m.data.moderator_name || '军师' }}裁决</text>
              <text class="rt-text">{{ m.data.verdict.text }}</text>
              <text v-for="(a, i) in m.data.verdict.adopt" :key="'a' + i" class="rt-adopt">✓ {{ a }}</text>
              <text v-if="m.data.verdict.watch" class="rt-watch">留意：{{ m.data.verdict.watch }}</text>
            </view>
            <text v-if="m.data.consensus && m.data.consensus.length" class="rt-consensus">共识：{{ m.data.consensus.join('；') }}</text>
            <text class="link rt-adopt-btn" @tap="adoptVerdict(m)">按裁决调整锦囊 ›</text>
          </view>

          <!-- 安全 -->
          <view v-else-if="m.kind === 'safety'" class="bubble safety">
            <text>{{ m.text }}</text>
          </view>

          <!-- 出错 -->
          <view v-else-if="m.kind === 'error'" class="route err">
            <text>{{ m.text }}</text>
            <text class="link" @tap="retry">重新生成</text>
          </view>

          <!-- 普通回复 -->
          <view v-else class="bubble adv"><text>{{ m.text }}</text></view>
        </view>

        <view v-if="streamBlocks.length" class="live-preview">
          <view class="live-heading">
            <text>{{ busy ? (streamAttempt ? '正在重新整理草稿' : '正在生成') : '未完成的草稿' }}</text>
            <text class="muted">{{ streamHint || (busy ? '内容持续更新，完成后显示正式结果' : '草稿已保留，请重试生成') }}</text>
          </view>
          <view v-for="block in streamBlocks" :key="block.id" class="live-block">
            <text class="live-label">{{ block.label }}</text>
            <text class="live-text">{{ block.text }}</text>
          </view>
        </view>

        <view v-if="busy" id="busy" class="msg advisor">
          <view class="thinking">
            <view class="dots"><view class="dot" /><view class="dot" /><view class="dot" /></view>
            <text>{{ busyText }}</text>
          </view>
        </view>
      </template>
      <view id="bottom" class="bottom-space" />
    </scroll-view>

    <view v-if="generationError" class="generation-error">
      <text>{{ generationError }}</text>
      <text v-if="failedGeneration" class="link" @tap="retry">重试这次生成</text>
      <text v-else class="link" @tap="sync">重新连接</text>
    </view>
    <view v-if="c && c.status !== 'safety'" class="input-bar">
      <view v-if="c.plan" class="modes">
        <text class="mode" :class="{ on: kind === 'ask' }" @tap="kind = 'ask'">继续问</text>
        <text class="mode" :class="{ on: kind === 'review' }" @tap="kind = 'review'">回来复盘</text>
        <text class="mode" :class="{ on: kind === 'roundtable' }" @tap="kind = 'roundtable'">圆桌辩论</text>
      </view>
      <view class="bar">
        <VoiceInput :disabled="busy" @text="onVoice" />
        <textarea v-model="draft" class="input" auto-height :maxlength="kind === 'roundtable' ? 100 : 2000" :placeholder="placeholder" :disabled="busy" />
        <view class="send" :class="{ off: busy || (kind !== 'roundtable' && draft.trim().length < 1) }" @tap="sendMsg">{{ kind === 'roundtable' ? '开会' : '发送' }}</view>
      </view>
    </view>

    <view v-if="showSeats" class="mask" @tap="showSeats = false">
      <view class="sheet" @tap.stop>
        <text class="sheet-title">请私人谋士列席（最多 2 位）</text>
        <text class="muted sheet-sub">列席的谋士会参与出锦囊和圆桌会议，按你给他写的人设发言。</text>
        <view v-for="a in myAdvisors" :key="a.code" class="sw-row" :class="{ cur: seatPick.includes(a.code) }" @tap="toggleSeat(a.code)">
          <text class="sw-icon mine">{{ a.avatar }}</text>
          <view class="sw-body">
            <text class="sw-name">{{ a.name }}<text v-if="a.style" class="muted"> · {{ a.style }}</text></text>
            <text class="muted persona">{{ a.persona }}</text>
          </view>
          <text class="check">{{ seatPick.includes(a.code) ? '✓' : '' }}</text>
        </view>
        <view v-if="!myAdvisors.length" class="muted empty-seat">还没有私人谋士。可以把你信任的前辈、朋友、家人设成谋士，让他们帮你一起出主意。</view>
        <view class="seat-btns">
          <view class="btn-plain" @tap="goMyAdvisors">管理我的谋士</view>
          <view v-if="myAdvisors.length" class="btn-primary" @tap="saveSeats">确定</view>
        </view>
      </view>
    </view>

    <view v-if="showSwitch" class="mask" @tap="showSwitch = false">
      <view class="sheet" @tap.stop>
        <text class="sheet-title">换一个智囊团重新出主意</text>
        <view v-for="x in councils" :key="x.code" class="sw-row" :class="{ cur: c.council && x.code === c.council.code }" @tap="switchTo(x.code)">
          <text class="sw-icon">{{ x.icon }}</text>
          <view class="sw-body">
            <text class="sw-name">{{ x.name }}</text>
            <text class="muted">{{ x.description }}</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { onLoad, onShow, onHide, onUnload } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { followGeneration } from '../../utils/generationStream'
import { getCurrentUser } from '../../utils/request'
import { syncNotifications } from '../../utils/notifications'
import { createGeneration, pendingGeneration, saveGeneration } from '../../utils/generation'
import VoiceInput from '../../components/VoiceInput/VoiceInput.vue'

const c = ref(null)
const councils = ref([])
const busy = ref(false)
const busyText = ref('')
const draft = ref('')
const kind = ref('ask')
const picked = ref({})
const answers = ref({})
const bottomId = ref('bottom')
const showSwitch = ref(false)
const generationError = ref('')
const failedGeneration = ref(null)
let timer = null
let visible = false
let initialized = false
let syncing = false
let resyncRequested = false
let consultId = 0
let active = null
const streamBlocks = ref([])
const streamHint = ref('')
const streamAttempt = ref(0)
let streamJobId = ''
let streamCursor = 0
let stopStream = null
let streamTerminal = false

function closeStream() {
  if (stopStream) stopStream()
  stopStream = null
}

function watchStream(job) {
  if (streamJobId !== job.id) {
    closeStream()
    streamJobId = job.id
    streamCursor = 0
    streamBlocks.value = []
    streamAttempt.value = 0
    streamHint.value = ''
    streamTerminal = false
  }
  if (stopStream || streamTerminal || !visible) return
  stopStream = followGeneration(job.id, {
    onUpdate(event, cursor) {
      if (!visible || streamJobId !== job.id) return
      const first = !streamBlocks.value.length
      streamCursor = cursor
      streamAttempt.value = event.attempt
      streamBlocks.value = event.blocks || []
      streamHint.value = ''
      if (first && streamBlocks.value.length) scrollBottom()
    },
    onTerminal() {
      streamTerminal = true
      stopStream = null
      sync()
    },
    onError() { streamHint.value = '进度连接暂时中断，正在续读；后台生成仍会继续' }
  }, streamCursor)
}


function keyboardSend(e) {
  if (!visible || !e.target || !e.target.closest('.input-bar textarea')) return
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    sendMsg()
  }
}

const showSeats = ref(false)
const myAdvisors = ref([])
const seatPick = ref([])

const placeholder = computed(() => {
  if (!c.value) return ''
  if (c.value.status === 'clarifying') return '点上面的选项，或者直接补充情况'
  if (kind.value === 'review') return '说说你照做之后的结果，智囊帮你调整下一步'
  if (kind.value === 'roundtable') return '想让谋士们争论什么？如：要不要当面摊牌（可不填）'
  if (c.value.plan) return '对锦囊有疑问？比如：如果他当场拒绝怎么办'
  return '补充一下情况'
})

const councilName = (code) => (councils.value.find((x) => x.code === code) || {}).name || code

async function scrollBottom() {
  await nextTick()
  bottomId.value = ''
  await nextTick()
  bottomId.value = 'bottom'
}

async function run(text, kind, payload = {}) {
  if (busy.value) return
  generationError.value = ''
  closeStream()
  streamBlocks.value = []
  failedGeneration.value = null
  active = createGeneration(kind, consultId || (c.value && c.value.id), payload)
  busy.value = true
  busyText.value = text
  await scrollBottom()
  await sync()
}

function plan(council) {
  return run('智囊团正在生成锦囊，离开后可回来查看…', 'plan', { council: council || null })
}

function retry() {
  if (busy.value) return
  const old = failedGeneration.value
  if (old) return run('正在重新处理…', old.kind, old.payload)
  return plan()
}

async function sync() {
  if (!visible || !initialized) return
  if (syncing) { resyncRequested = true; return }
  syncing = true
  try {
    active = active || pendingGeneration()
    // 其他问计的本地任务不影响当前对话；在对应对话或首页恢复。
    if (active && consultId && active.consult_id && Number(active.consult_id) !== consultId) active = null
    let job = active ? await api.findGeneration(active.request_key) : (consultId ? await api.findGeneration('', consultId) : null)
    if (!job && active) job = await api.submitGeneration(active)
    if (job && job.consult_id) {
      consultId = Number(job.consult_id)
      if (active) { active.consult_id = consultId; saveGeneration(active) }
      // #ifdef H5
      const u = new URL(location.href)
      u.hash = '/pages/consult/consult?id=' + consultId
      history.replaceState(history.state, '', u)
      // #endif
    }
    busy.value = !!job && ['queued', 'running'].includes(job.status)
    if (job && job.status !== 'done') watchStream(job)
    busyText.value = job ? job.stage + '，离开后可回来查看…' : ''
    generationError.value = ''
    if (job && job.status === 'failed') {
      failedGeneration.value = active || { kind: job.kind, payload: job.payload || {} }
      generationError.value = job.error || '生成中断，请重试'
    }
    if (job && !busy.value) {
      if (active && job.status === 'done') syncNotifications().catch(() => {})
      if (active && pendingGeneration() && pendingGeneration().request_key === active.request_key) saveGeneration(null)
      active = null
    }
    if (consultId) {
      const result = await api.consult(consultId)
      // 周期刷新保留草稿与当前阅读位置；仅新消息到达时滚动。
      const oldLast = c.value && c.value.messages && c.value.messages.slice(-1)[0]
      const last = result.messages.slice(-1)[0]
      c.value = result
      if (job && job.status === 'done') { closeStream(); streamBlocks.value = []; streamHint.value = '' }
      uni.setNavigationBarTitle({ title: result.title || '问计' })
      if ((!oldLast || !last || oldLast.id !== last.id) && visible) await scrollBottom()
      if (!busy.value && !generationError.value && result.status === 'routed' && !result.plan) {
        const choose = last && last.data && last.data.candidates && last.data.candidates.length > 1
        if (!choose) await plan()
      }
    }
  } catch (e) {
    // 请求确认丢失时保留原请求标识，恢复网络后只查询/重放同一次提交。
    generationError.value = e.status === 401 ? '登录已过期，请重新登录后查看结果' : (e.status === 400 ? e.message : '连接暂时中断，正在恢复；无需重复提交')
    if (e.status === 400) {
      busy.value = false
      if (active && !active.consult_id) failedGeneration.value = active
      active = null
      saveGeneration(null)
    }
  } finally {
    syncing = false
    if (resyncRequested) { resyncRequested = false; if (visible) setTimeout(sync, 0) }
  }
}

function showPage() {
  visible = true
  if (!timer) timer = setInterval(sync, 3000)
  sync()
}
function hidePage() {
  visible = false
  closeStream()
  clearInterval(timer)
  timer = null
}

function switchTo(code) {
  showSwitch.value = false
  if (c.value.council && code === c.value.council.code) return
  plan(code)
}

function pickOption(qi, q, o) {
  picked.value = { ...picked.value, [qi]: o }
  answers.value = { ...answers.value, [qi]: `${q.replace(/[？?]$/, '')}：${o}` }
  draft.value = Object.keys(answers.value).sort().map((k) => answers.value[k]).join('；')
}

function onVoice(t) {
  draft.value = draft.value ? `${draft.value}，${t}` : t
}

function roundtable(topic) {
  if (busy.value) return
  kind.value = 'ask'
  return run('谋士们正在圆桌上争论，通常需要 20–40 秒…', 'roundtable', { topic })
}

function adoptVerdict(m) {
  if (busy.value) return
  const v = m.data.verdict || {}
  const text = `请按圆桌会议的裁决调整锦囊：${v.text || ''}${v.adopt && v.adopt.length ? '（采纳：' + v.adopt.join('；') + '）' : ''}`
  run('智囊在按裁决调整锦囊…', 'message', { text: text.slice(0, 1900), kind: 'ask' })
}

async function openSeats() {
  if (busy.value) return
  showSeats.value = true
  seatPick.value = (c.value.extra_advisors || []).map((a) => a.code)
  try {
    myAdvisors.value = (await api.myAdvisors()).items
  } catch (e) {
    myAdvisors.value = []
  }
}

function toggleSeat(code) {
  const i = seatPick.value.indexOf(code)
  if (i >= 0) seatPick.value.splice(i, 1)
  else if (seatPick.value.length < 2) seatPick.value.push(code)
  else uni.showToast({ title: '最多请 2 位', icon: 'none' })
}

async function saveSeats() {
  showSeats.value = false
  const before = (c.value.extra_advisors || []).map((a) => a.code).sort().join()
  if (before === [...seatPick.value].sort().join()) return
  c.value = await api.setConsultAdvisors(c.value.id, seatPick.value)
  if (c.value.plan && seatPick.value.length) {
    uni.showModal({
      title: '请他们重新出一份锦囊？',
      content: '列席的谋士会一起商议，生成新版本锦囊；也可以先开圆桌听听他们的意见。',
      confirmText: '重新出',
      cancelText: '先不用',
      success: (r) => r.confirm && plan()
    })
  }
}

function goMyAdvisors() {
  showSeats.value = false
  uni.navigateTo({ url: '/pages/my-advisors/my-advisors' })
}

function sendMsg() {
  const text = draft.value.trim()
  if (busy.value) return
  if (kind.value === 'roundtable' && c.value.plan) {
    draft.value = ''
    return roundtable(text)
  }
  if (!text) return
  const k = c.value.status === 'clarifying' && !c.value.plan ? 'answer' : kind.value
  draft.value = ''
  picked.value = {}
  answers.value = {}
  const tip = k === 'answer' ? '智囊在重新理解你的情况…' : k === 'review' ? '智囊在根据结果调整锦囊…' : '智囊在思考…'
  run(tip, 'message', { text, kind: k })
  kind.value = 'ask'
}

function skip() {
  run('智囊在分派…', 'message', { text: '', kind: 'skip' })
}

function openPlan(version) {
  uni.navigateTo({ url: `/pages/plan/plan?id=${c.value.id}&version=${version || ''}` })
}

async function rehearse() {
  uni.showLoading({ title: '生成演练场景', mask: true })
  try {
    const d = await api.rehearse(c.value.id)
    uni.hideLoading()
    uni.navigateTo({ url: `/pages/drill/drill?id=${d.id}` })
  } catch (e) {
    uni.hideLoading()
  }
}

onLoad(async (q) => {
  api.councils().then((r) => (councils.value = r)).catch(() => {})
  consultId = Number(q.id) || 0
  if (q.review) kind.value = 'review'
  if (!consultId) {
    const stored = uni.getStorageSync('tt_pending_consult')
    const pending = stored && stored.user_id === (getCurrentUser() || {}).uid ? stored : null
    active = pendingGeneration()
    if (pending && pending.text) {
      if (active) {
        uni.showToast({ title: '先恢复尚未完成的问计，请完成后再发起新的问计', icon: 'none' })
      } else {
        active = createGeneration('create', null, pending)
      }
      uni.removeStorageSync('tt_pending_consult')
    }
    if (active) {
      consultId = Number(active.consult_id) || 0
      c.value = { id: consultId, status: 'asking', messages: [], plan: null }
      busy.value = true
    } else return uni.navigateBack()
  }
  initialized = true
  visible = true
  await sync()
  showPage()
  if (q.roundtable && c.value && c.value.plan && !busy.value) roundtable('')
})
onShow(showPage)
onHide(hidePage)
onUnload(hidePage)
// #ifdef H5
function updateViewport() {
  document.documentElement.style.setProperty('--tt-visible-height', (window.visualViewport ? window.visualViewport.height : window.innerHeight) + 'px')
}
updateViewport()
if (window.visualViewport) window.visualViewport.addEventListener('resize', updateViewport)
function becameVisible() { if (document.hidden) hidePage(); else { updateViewport(); showPage() } }
document.addEventListener('keydown', keyboardSend)
window.addEventListener('online', sync)
document.addEventListener('visibilitychange', becameVisible)
onUnload(() => { document.removeEventListener('keydown', keyboardSend); if (window.visualViewport) window.visualViewport.removeEventListener('resize', updateViewport); window.removeEventListener('online', sync); document.removeEventListener('visibilitychange', becameVisible) })
// #endif

</script>

<style lang="scss" scoped>
.page { position: fixed; top: var(--window-top, 0px); left: 0; right: 0; bottom: auto; height: calc(var(--tt-visible-height, 100dvh) - var(--window-top, 0px) - var(--window-bottom, 0px)); display: flex; flex-direction: column; background: $tt-bg; }
.council-bar {
  display: flex; align-items: center; gap: 16rpx; padding: 18rpx 32rpx; background: #fff;
  border-bottom: 1rpx solid #EEF2F0; flex-shrink: 0;
}
.cb-name { font-size: 28rpx; font-weight: 700; }
.cb-avatars { display: flex; flex: 1; }
.cb-avatar {
  width: 44rpx; height: 44rpx; line-height: 44rpx; text-align: center; border-radius: 50%; margin-left: -8rpx;
  background: $tt-primary; color: #fff; font-size: 22rpx; border: 3rpx solid #fff;
}
.cb-switch { font-size: 25rpx; color: $tt-primary; margin-left: 8rpx; }
.cb-avatar.mine, .sw-icon.mine { background: #E8A13A; color: #fff; }
.persona { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.check { color: $tt-primary; font-size: 32rpx; width: 40rpx; text-align: center; }
.sheet-sub { display: block; margin: -8rpx 0 16rpx; line-height: 1.6; }
.empty-seat { padding: 30rpx 8rpx; line-height: 1.7; }
.seat-btns { display: flex; gap: 16rpx; margin-top: 24rpx; }
.seat-btns > view { flex: 1; }
.rt-card { width: 92%; background: #fff; border-radius: 24rpx; padding: 26rpx 28rpx; display: flex; flex-direction: column; border-top: 8rpx solid #E8A13A; }
.rt-label { font-size: 22rpx; color: #B7791F; font-weight: 700; }
.rt-q { font-size: 30rpx; font-weight: 700; margin: 8rpx 0 14rpx; line-height: 1.5; }
.rt-sp { display: flex; gap: 16rpx; padding: 14rpx 0; border-bottom: 1rpx dashed #EEF0EF; }
.rt-sp.r2 { padding-left: 36rpx; }
.rt-avatar {
  width: 52rpx; height: 52rpx; line-height: 52rpx; text-align: center; border-radius: 50%; flex-shrink: 0;
  background: $tt-soft; color: $tt-primary; font-size: 24rpx; font-weight: 700;
}
.rt-body { flex: 1; display: flex; flex-direction: column; gap: 4rpx; }
.rt-name { font-size: 25rpx; font-weight: 700; }
.rt-reply { color: #E5564B; font-weight: 400; font-size: 22rpx; }
.rt-stance { font-size: 24rpx; color: $tt-primary; }
.rt-text { font-size: 27rpx; line-height: 1.7; color: $tt-text; }
.rt-verdict { margin-top: 18rpx; background: #FFF8EC; border-radius: 16rpx; padding: 20rpx 22rpx; display: flex; flex-direction: column; gap: 8rpx; }
.rt-v-title { font-size: 25rpx; font-weight: 800; color: #B7791F; }
.rt-adopt { font-size: 26rpx; color: $tt-text; line-height: 1.6; }
.rt-watch { font-size: 24rpx; color: #E5564B; line-height: 1.6; }
.rt-consensus { font-size: 24rpx; color: $tt-text-2; margin-top: 14rpx; line-height: 1.6; }
.rt-adopt-btn { margin-top: 16rpx; font-weight: 600; }
.list { flex: 1; min-height: 0; padding: 24rpx 28rpx 0; box-sizing: border-box; }
.empty { text-align: center; padding: 120rpx 0; }
.msg { display: flex; margin-bottom: 24rpx; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 82%; padding: 22rpx 26rpx; border-radius: 20rpx; font-size: 28rpx; line-height: 1.7; white-space: pre-wrap; }
.bubble.me { background: $tt-primary; color: #fff; border-top-right-radius: 6rpx; }
.bubble.adv { background: #fff; color: $tt-text; border-top-left-radius: 6rpx; }
.bubble.safety { background: #FFF4F2; color: $tt-text; border: 2rpx solid #F5C6C0; }
.tag { font-size: 20rpx; background: rgba(255, 255, 255, 0.25); padding: 2rpx 10rpx; border-radius: 6rpx; margin-right: 10rpx; }
.route { width: 100%; text-align: center; font-size: 24rpx; color: $tt-text-3; display: flex; flex-direction: column; align-items: center; gap: 14rpx; }
.route.err { color: #E5564B; }
.chips { display: flex; flex-wrap: wrap; gap: 14rpx; margin-top: 12rpx; }
.route .chips { justify-content: center; }
.chip { font-size: 25rpx; padding: 10rpx 22rpx; border-radius: 30rpx; background: $tt-soft; color: $tt-primary; }
.chip.on { background: $tt-primary; color: #fff; }
.adv-intro { display: block; margin-bottom: 12rpx; }
.q { margin-top: 16rpx; }
.q-text { font-size: 27rpx; font-weight: 600; }
.skip { display: block; margin-top: 20rpx; font-size: 25rpx; color: $tt-text-3; }
.plan-card {
  width: 88%; background: linear-gradient(135deg, $tt-hero-from, $tt-hero-to); color: #fff; border-radius: 24rpx;
  padding: 28rpx 30rpx; display: flex; flex-direction: column;
}
.plan-label { font-size: 22rpx; opacity: 0.8; }
.plan-head { font-size: 31rpx; font-weight: 700; line-height: 1.6; margin: 10rpx 0 18rpx; }
.plan-actions { display: flex; gap: 40rpx; }
.plan-card .link { color: #fff; font-size: 26rpx; font-weight: 600; }
.link { color: $tt-primary; font-size: 25rpx; }
.thinking { display: flex; align-items: center; gap: 16rpx; background: #fff; padding: 22rpx 26rpx; border-radius: 20rpx; font-size: 26rpx; color: $tt-text-2; }
.dots { display: flex; gap: 8rpx; }
.dot { width: 12rpx; height: 12rpx; border-radius: 50%; background: $tt-primary; animation: blink 1.2s infinite ease-in-out; }
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.25; } 40% { opacity: 1; } }
.bottom-space { height: 40rpx; }
.input-bar { background: #fff; padding: 14rpx 24rpx calc(14rpx + env(safe-area-inset-bottom)); flex-shrink: 0; border-top: 1rpx solid #EEF2F0; }
.modes { display: flex; gap: 16rpx; margin-bottom: 12rpx; }
.mode { font-size: 23rpx; padding: 6rpx 18rpx; border-radius: 20rpx; background: $tt-bg; color: $tt-text-2; }
.mode.on { background: $tt-tag-bg; color: $tt-primary; }
.bar { display: flex; align-items: flex-end; gap: 16rpx; }
.input { flex: 1; min-height: 76rpx; max-height: 240rpx; padding: 18rpx 20rpx; box-sizing: border-box; background: $tt-bg; border-radius: 16rpx; font-size: 28rpx; line-height: 1.5; }
.send { height: 76rpx; line-height: 76rpx; padding: 0 28rpx; border-radius: 16rpx; background: $tt-primary; color: #fff; font-size: 28rpx; flex-shrink: 0; }
.send.off { opacity: 0.45; }
.mask { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0, 0, 0, 0.45); z-index: 50; display: flex; align-items: flex-end; }
.sheet { width: 100%; max-height: 80vh; overflow-y: auto; background: #fff; border-radius: 32rpx 32rpx 0 0; padding: 36rpx 32rpx calc(36rpx + env(safe-area-inset-bottom)); box-sizing: border-box; }
.sheet-title { display: block; font-size: 32rpx; font-weight: 800; margin-bottom: 20rpx; }
.sw-row { display: flex; align-items: center; gap: 20rpx; padding: 20rpx 12rpx; border-bottom: 1rpx solid #F0F2F1; }
.sw-row.cur { background: $tt-soft; border-radius: 12rpx; }
.sw-icon { width: 60rpx; height: 60rpx; line-height: 60rpx; text-align: center; border-radius: 50%; background: $tt-soft; color: $tt-primary; font-weight: 700; flex-shrink: 0; }
.sw-body { flex: 1; display: flex; flex-direction: column; }
.sw-name { font-size: 28rpx; font-weight: 600; }
</style>

<style lang="scss" scoped>
.generation-error { padding: 18rpx 28rpx; background: #fff3df; color: #8c5b17; font-size: 26rpx; display: flex; gap: 20rpx; flex-wrap: wrap; }
@media (min-width: 900px) {
  .page { max-width: 1000px; margin: auto; border-left: 1px solid #dfe9e5; border-right: 1px solid #dfe9e5; }
  .list { padding: 24px 40px 0; }
  .bubble { max-width: 72%; }
  .sheet { max-width: 680px; }
}
</style>

<style lang="scss" scoped>
.live-preview { background: #fff; border-left: 6rpx solid $tt-primary; padding: 24rpx; margin: 12rpx 0 24rpx; border-radius: 12rpx; }
.live-heading { display: flex; flex-direction: column; gap: 8rpx; margin-bottom: 20rpx; color: $tt-primary; font-size: 26rpx; }
.live-block { margin-bottom: 20rpx; display: flex; flex-direction: column; gap: 6rpx; }
.live-label { color: $tt-text-3; font-size: 23rpx; }
.live-text { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 28rpx; line-height: 1.8; color: $tt-text; }
</style>
