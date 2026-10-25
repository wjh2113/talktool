<template>
  <view class="vi" :title="label" :aria-label="label" :class="{ rec: state === 'recording', busy: state === 'busy' }" @tap="toggle">
    <view v-if="state === 'recording'" class="vi-level" :style="{ transform: `scale(${1 + Math.min(0.6, level * 8)})` }" />
    <image class="vi-icon" :src="state === 'recording' ? '/static/icons/mic-white.png' : '/static/icons/mic.png'" />
    <text v-if="showLabel" class="vi-label">{{ label }}</text>
  </view>
</template>

<script setup>
import { ref, computed, onUnmounted, watch } from 'vue'
import { onHide } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { createRecorder, unlockAudio } from '../../utils/voice'

// 语音输入：点一下开始说，停顿约 2 秒自动结束（也可以再点一下结束），识别成文字后交给父组件放进输入框
const props = defineProps({ showLabel: { type: Boolean, default: true }, disabled: { type: Boolean, default: false } })
let generation = 0
let hidden = false
const emit = defineEmits(['text', 'state'])
const state = ref('idle') // idle | recording | busy
const level = ref(0)
let recorder = null

const label = computed(() => {
  let recording = '说完停顿自动结束'
  // #ifdef APP-PLUS
  recording = '再点一次结束录音'
  // #endif
  return { idle: '按一下说话', recording, busy: '识别中…' }[state.value]
})

function setState(s) {
  state.value = s
  emit('state', s)
}

async function toggle() {
  if (props.disabled || state.value === 'busy') return
  if (state.value === 'recording') {
    recorder && recorder.stop()
    return
  }
  hidden = false
  const token = ++generation
  unlockAudio()
  recorder = recorder || createRecorder({ vad: { silenceMs: 2000, maxMs: 90000 }, onLevel: (v) => (level.value = v) })
  setState('recording')
  let rec
  try {
    rec = await recorder.start()
  } catch (e) {
    if (token !== generation) return
    setState('idle')
    uni.showToast({ title: e.message || '无法使用麦克风', icon: 'none', duration: 3000 })
    return
  }
  if (hidden || token !== generation) return
  if (!rec || !rec.spoke) {
    setState('idle')
    uni.showToast({ title: '没听到声音，请靠近麦克风再试', icon: 'none' })
    return
  }
  setState('busy')
  try {
    const res = await api.transcribe(rec)
    if (!hidden && token === generation && res.text) emit('text', res.text)
  } catch (e) {
    if (hidden || token !== generation) return
    uni.showToast({ title: (e.message || '识别失败').slice(0, 40), icon: 'none' })
  } finally {
    if (token === generation) setState('idle')
  }
}

function cleanup() {
  hidden = true
  generation++
  if (recorder) recorder.destroy()
  recorder = null
  setState('idle')
}
watch(() => props.disabled, (v) => { if (v) cleanup() })
uni.$on('tt:page-hide', cleanup)
onHide(cleanup)
onUnmounted(() => { uni.$off('tt:page-hide', cleanup); cleanup() })
// #ifdef H5
function visibility() { if (document.hidden) cleanup() }
document.addEventListener('visibilitychange', visibility)
onUnmounted(() => document.removeEventListener('visibilitychange', visibility))
// #endif
</script>

<style lang="scss" scoped>
.vi {
  position: relative; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  width: 76rpx; height: 76rpx; border-radius: 50%; background: $tt-soft;
}
.vi.rec { background: $tt-primary; }
.vi.busy { opacity: 0.6; }
.vi-level { position: absolute; top: 0; left: 0; right: 0; bottom: 0; border-radius: 50%; background: rgba(13, 138, 123, 0.25); transition: transform 0.12s linear; }
.vi-icon { position: relative; width: 40rpx; height: 40rpx; }
.vi-label { position: absolute; bottom: -36rpx; white-space: nowrap; font-size: 20rpx; color: $tt-text-3; }
</style>

<style scoped>
.vi { margin-bottom: 16px; }
</style>
