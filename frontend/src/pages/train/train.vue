<template>
  <view class="page">
    <view class="nav" :style="{ paddingTop: statusBar + 'px' }">
      <view class="back" @tap="onBack">‹</view>
      <view class="nav-center">
        <text class="nav-title">{{ drill ? drill.title : '训练准备中' }}</text>
        <text class="nav-sub">{{ drill ? drill.pressure_level + '模式' : '' }} · {{ timeText }}</text>
      </view>
      <view class="back" />
    </view>

    <view v-if="mock" class="mock-tag">Mock 模式 · 未配置网关 Key</view>

    <view class="center">
      <view class="mic-area" @tap="onMicTap">
        <view class="ring ring1" :class="{ wave: waving }" />
        <view class="ring ring2" :class="{ wave: waving }" />
        <view class="ring ring3" :style="{ transform: `scale(${levelScale})` }" />
        <view class="mic-btn" :class="{ live: canTalk }">
          <image class="mic-icon" :src="canTalk ? '/static/icons/mic-white.png' : '/static/icons/mic-off.png'" />
        </view>
      </view>

      <text class="state-title">{{ stateTitle }}</text>
      <text class="state-sub">训练过程仅用语音表达，不提供文字输入</text>
      <text class="latency">{{ latency !== null ? latency + ' ms' : '-- ms' }}</text>
      <text class="hint">{{ hintText }}</text>

      <view v-if="showCaption && caption" class="caption">
        <text>{{ caption }}</text>
      </view>
    </view>

    <view class="bottom">
      <view class="cap-toggle" @tap="showCaption = !showCaption">
        <text>{{ showCaption ? '隐藏字幕' : '显示字幕' }}</text>
      </view>
      <view class="end-btn" @tap="finish">结束训练</view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad, onUnload } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { absUrl } from '../../utils/request'
import { mmss } from '../../utils/format'
import { createRecorder, playAudio, stopAudio, simulateSpeaking } from '../../utils/voice'

/**
 * 状态机：connecting → ai（AI 讲话中）→ listen（可以说话）→ user（用户讲话中）
 *        → thinking（识别 + AI 思考）→ ai → … 直到点击“结束训练”
 */
const statusBar = ref(uni.getSystemInfoSync().statusBarHeight || 20)
const drill = ref(null)
const state = ref('connecting')
const elapsed = ref(0)
const latency = ref(null)
const level = ref(0)
const caption = ref('')
const showCaption = ref(false)
const mock = ref(false)

let sessionId = null
let alive = true
let ended = false
let manualStop = false
let startTs = 0
let timer = null
let pinger = null

const recorder = createRecorder({
  onSpeechStart: () => { if (state.value === 'listen') state.value = 'user' },
  onLevel: (rms) => { level.value = rms }
})

const timeText = computed(() => mmss(elapsed.value))
const canTalk = computed(() => state.value === 'listen' || state.value === 'user')
const waving = computed(() => ['ai', 'listen', 'user'].includes(state.value))
const levelScale = computed(() => (state.value === 'user' || state.value === 'listen' ? 1 + Math.min(0.5, level.value * 8) : 1))
const stateTitle = computed(() => ({
  connecting: '正在进入场景…',
  ai: 'AI 讲话中，请稍候',
  listen: '可以说话了',
  user: '正在聆听…',
  thinking: 'AI 思考中…',
  ending: '正在生成报告…',
  error: '连接中断'
}[state.value]))
const hintText = computed(() => ({
  connecting: '请稍候，马上开始',
  ai: '请等提示“可以说话”后再回答',
  listen: '直接开口说话，说完停顿片刻会自动发送',
  user: '说完停顿片刻自动发送，也可点击麦克风结束本轮',
  thinking: '正在识别你的回答…',
  ending: '请勿关闭页面',
  error: '点击麦克风重试'
}[state.value]))

async function aiSpeak(ai) {
  if (!alive || !ai) return
  state.value = 'ai'
  caption.value = ai.text
  let ok = false
  if (ai.audio_url) ok = await playAudio(absUrl(ai.audio_url))
  if (!ok && alive) await simulateSpeaking(ai.text)
  if (alive) listen()
}

async function listen() {
  if (!alive) return
  state.value = 'listen'
  manualStop = false
  level.value = 0
  let rec
  try {
    rec = await recorder.start()
  } catch (e) {
    if (!alive) return
    uni.showToast({ title: e.message || '无法使用麦克风', icon: 'none', duration: 3000 })
    state.value = 'error'
    return
  }
  if (!alive) return
  if (!rec.spoke && !manualStop) return listen() // 长时间没开口，继续等
  state.value = 'thinking'
  let res
  try {
    res = await api.turn(sessionId, rec)
  } catch (e) {
    if (!alive) return
    uni.showToast({ title: (e.message || '发送失败').slice(0, 40), icon: 'none', duration: 3000 })
    return listen()
  }
  if (!alive) return
  if (res.empty) {
    uni.showToast({ title: res.reason === 'no_speech' ? '没听到声音，请靠近麦克风再说一次' : '没听清，请再说一次', icon: 'none' })
    return listen()
  }
  aiSpeak(res.ai)
}

function onMicTap() {
  if (state.value === 'user' || state.value === 'listen') {
    manualStop = true
    recorder.stop()
  } else if (state.value === 'error') {
    listen()
  }
}

function cleanup() {
  alive = false
  clearInterval(timer)
  clearInterval(pinger)
  stopAudio()
  recorder.destroy()
}

async function finish() {
  if (ended) return
  if (!sessionId) return uni.navigateBack()
  ended = true
  cleanup()
  state.value = 'ending'
  uni.showLoading({ title: '正在结束', mask: true })
  try {
    await api.endSession(sessionId, 'finish')
  } catch (e) {}
  uni.hideLoading()
  uni.redirectTo({ url: `/pages/report/report?id=${sessionId}&from=train` })
}

function onBack() {
  if (!sessionId) return uni.navigateBack()
  uni.showModal({
    title: '退出训练？',
    content: '退出后本次训练将直接结算，还没开口的话会记为“主动放弃”。',
    confirmText: '退出',
    success: (r) => r.confirm && uni.navigateBack()
  })
}

async function measurePing() {
  const t = Date.now()
  try {
    await api.ping()
    latency.value = Date.now() - t
  } catch (e) {
    latency.value = null
  }
}

onLoad(async (q) => {
  measurePing()
  pinger = setInterval(measurePing, 3000)
  try {
    drill.value = await api.drill(q.drillId)
    await recorder.init() // 先拿麦克风权限，避免 AI 说完才弹授权
    const st = await api.startSession(q.drillId)
    if (!alive) {
      api.endSession(st.session_id, 'exit').catch(() => {})
      return
    }
    sessionId = st.session_id
    mock.value = st.mock
    startTs = Date.now()
    timer = setInterval(() => (elapsed.value = Math.floor((Date.now() - startTs) / 1000)), 500)
    aiSpeak(st.ai)
  } catch (e) {
    state.value = 'error'
    uni.showModal({
      title: '无法开始训练',
      content: e.message || '请检查麦克风权限和网络',
      showCancel: false,
      success: () => uni.navigateBack()
    })
  }
})

onUnload(() => {
  // 未点“结束训练”就离开 → 记为中途退出（无有效对话时为“主动放弃”）
  if (!ended && sessionId) {
    ended = true
    api.endSession(sessionId, 'exit').catch(() => {})
  }
  cleanup()
})
</script>

<style lang="scss" scoped>
.page {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: $tt-train-bg;
  color: #fff;
  display: flex;
  flex-direction: column;
}
.nav {
  display: flex;
  align-items: center;
  height: 88rpx;
  padding: 0 24rpx;
  box-sizing: content-box;
}
.back { width: 64rpx; font-size: 56rpx; line-height: 88rpx; color: #fff; flex-shrink: 0; }
.nav-center { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; }
.nav-title {
  max-width: 100%;
  font-size: 30rpx;
  font-weight: 600;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.nav-sub { font-size: 24rpx; opacity: 0.8; margin-top: 4rpx; }
.mock-tag {
  align-self: center;
  margin-top: 16rpx;
  font-size: 22rpx;
  padding: 6rpx 20rpx;
  border-radius: 20rpx;
  background: rgba(255, 255, 255, 0.18);
}
.center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0 48rpx;
}
.mic-area {
  position: relative;
  width: 420rpx;
  height: 420rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 60rpx;
}
.ring {
  position: absolute;
  border-radius: 50%;
  border: 2rpx solid rgba(255, 255, 255, 0.28);
}
.ring1 { width: 420rpx; height: 420rpx; }
.ring2 { width: 300rpx; height: 300rpx; background: rgba(255, 255, 255, 0.05); }
.ring3 { width: 230rpx; height: 230rpx; background: rgba(255, 255, 255, 0.10); border: none; transition: transform 0.12s linear; }
.wave { animation: ripple 2.2s ease-out infinite; }
.ring2.wave { animation-delay: 0.6s; }
@keyframes ripple {
  0% { transform: scale(0.85); opacity: 1; }
  100% { transform: scale(1.12); opacity: 0.25; }
}
.mic-btn {
  width: 190rpx;
  height: 190rpx;
  border-radius: 50%;
  background: #F7F9FC;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 16rpx 40rpx rgba(0, 60, 140, 0.25);
  transition: background 0.2s;
  &.live { background: #2C7FD9; }
}
.mic-icon { width: 76rpx; height: 76rpx; }
.state-title { font-size: 44rpx; font-weight: 700; margin-bottom: 18rpx; }
.state-sub { font-size: 26rpx; opacity: 0.75; }
.latency { font-size: 34rpx; opacity: 0.8; margin: 56rpx 0 40rpx; }
.hint { font-size: 26rpx; opacity: 0.75; text-align: center; }
.caption {
  margin-top: 40rpx;
  padding: 24rpx 28rpx;
  border-radius: 20rpx;
  background: rgba(255, 255, 255, 0.14);
  font-size: 28rpx;
  line-height: 1.7;
  max-height: 260rpx;
  overflow: hidden;
}
.bottom { padding: 0 48rpx calc(40rpx + env(safe-area-inset-bottom)); }
.cap-toggle { text-align: center; font-size: 24rpx; opacity: 0.7; margin-bottom: 24rpx; }
.end-btn {
  height: 96rpx;
  line-height: 96rpx;
  text-align: center;
  border-radius: 20rpx;
  border: 2rpx solid rgba(255, 255, 255, 0.45);
  background: rgba(255, 255, 255, 0.08);
  font-size: 32rpx;
  font-weight: 600;
}
</style>
