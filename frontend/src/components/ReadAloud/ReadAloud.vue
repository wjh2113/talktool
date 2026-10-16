<template>
  <view class="ra">
    <view class="ra-actions">
      <view class="ra-btn" :class="{ on: playing }" @tap="onListen">
        <text>{{ playing ? '■ 停止' : '▶ 听示范' }}</text>
      </view>
      <view class="ra-btn primary" :class="{ rec: state === 'recording' }" @tap="onRecord">
        <text>{{ recordLabel }}</text>
      </view>
      <text v-if="bestScore != null && !result" class="ra-best">最高 {{ bestScore }} 分</text>
    </view>

    <view v-if="state === 'recording'" class="ra-tip">
      <view class="ra-level"><view class="ra-level-in" :style="{ width: levelPct + '%' }" /></view>
      <text>读完停顿 2 秒自动提交，或再点一次按钮结束</text>
    </view>

    <view v-if="result" class="ra-result">
      <view class="ra-score-row">
        <text class="ra-score" :class="scoreClass">{{ result.score == null ? '--' : result.score }}</text>
        <text class="ra-unit">分</text>
        <text class="ra-note">{{ result.note }}</text>
      </view>
      <view v-for="(it, i) in result.issues" :key="i" class="ra-issue">
        <text class="ra-quote">“{{ it.quote }}”</text>
        <text class="ra-issue-note">{{ it.note }}</text>
      </view>
      <text v-if="result.transcript" class="ra-heard">识别到：{{ result.transcript }}</text>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { api } from '../../utils/api'
import { absUrl } from '../../utils/request'
import { createRecorder, playAudio, stopAudio, unlockAudio } from '../../utils/voice'

const props = defineProps({
  text: { type: String, required: true },
  noteId: { type: [Number, String], default: null },
  best: { type: Number, default: null }
})
const emit = defineEmits(['scored'])

const state = ref('idle') // idle | recording | scoring
const playing = ref(false)
const result = ref(null)
const level = ref(0)
const bestScore = ref(props.best)
let recorder = null

const levelPct = computed(() => Math.min(100, Math.round(level.value * 600)))
const recordLabel = computed(() =>
  state.value === 'recording' ? '■ 读完了' : state.value === 'scoring' ? '评分中…' : result.value ? '🎙 再读一遍' : '🎙 跟读'
)
const scoreClass = computed(() => {
  const s = result.value && result.value.score
  return s == null ? '' : s >= 85 ? 'good' : s >= 70 ? 'ok' : 'low'
})

async function onListen() {
  unlockAudio()
  if (playing.value) {
    stopAudio()
    playing.value = false
    return
  }
  if (state.value !== 'idle') return
  playing.value = true
  try {
    const r = await api.tts(props.text)
    if (!r.audio_url) {
      uni.showToast({ title: 'Mock 模式没有示范语音', icon: 'none' })
    } else if (playing.value) {
      await playAudio(absUrl(r.audio_url))
    }
  } catch (e) {
  } finally {
    playing.value = false
  }
}

async function onRecord() {
  if (state.value === 'recording') {
    recorder && recorder.stop()
    return
  }
  if (state.value === 'scoring') return
  unlockAudio()
  stopAudio()
  playing.value = false
  recorder = createRecorder({ vad: { silenceMs: 2200, maxMs: 120000 }, onLevel: (v) => (level.value = v) })
  state.value = 'recording'
  try {
    const rec = await recorder.start()
    state.value = 'scoring'
    const res = await api.pronounce(rec, props.text, props.noteId)
    result.value = res
    if (typeof res.score === 'number') bestScore.value = Math.max(bestScore.value || 0, res.score)
    emit('scored', res)
  } catch (e) {
    uni.showToast({ title: (e && e.message ? e.message : '跟读失败').slice(0, 40), icon: 'none', duration: 2500 })
  } finally {
    recorder && recorder.destroy()
    recorder = null
    state.value = 'idle'
    level.value = 0
  }
}

onUnmounted(() => {
  recorder && recorder.destroy()
  if (playing.value) stopAudio()
})
</script>

<style lang="scss" scoped>
.ra { margin-top: 18rpx; }
.ra-actions { display: flex; align-items: center; gap: 16rpx; flex-wrap: wrap; }
.ra-btn {
  height: 60rpx;
  line-height: 60rpx;
  padding: 0 26rpx;
  border-radius: 30rpx;
  font-size: 25rpx;
  background: #F0F3F7;
  color: #4A4F57;
  &.on { background: #E0E8F2; }
  &.primary { background: $tt-tag-bg; color: $tt-primary; font-weight: 600; }
  &.rec { background: #FDECEC; color: #E5484D; }
}
.ra-best { font-size: 24rpx; color: $tt-text-3; }
.ra-tip { margin-top: 16rpx; font-size: 24rpx; color: $tt-text-3; }
.ra-level { height: 8rpx; border-radius: 4rpx; background: #EEF2F7; margin-bottom: 10rpx; overflow: hidden; }
.ra-level-in { height: 100%; background: #E5484D; transition: width 0.1s linear; }
.ra-result { margin-top: 18rpx; padding: 22rpx 24rpx; border-radius: 16rpx; background: #F7F9FC; }
.ra-score-row { display: flex; align-items: baseline; flex-wrap: wrap; }
.ra-score { font-size: 48rpx; font-weight: 800; color: $tt-text;
  &.good { color: #22A060; } &.ok { color: $tt-primary; } &.low { color: #E68A1A; } }
.ra-unit { font-size: 24rpx; color: $tt-text-3; margin: 0 16rpx 0 6rpx; }
.ra-note { flex: 1; font-size: 26rpx; color: $tt-text-2; }
.ra-issue { margin-top: 12rpx; font-size: 25rpx; line-height: 1.6; }
.ra-quote { color: #E68A1A; margin-right: 10rpx; }
.ra-issue-note { color: $tt-text-2; }
.ra-heard { display: block; margin-top: 12rpx; font-size: 23rpx; color: $tt-text-3; line-height: 1.6; }
</style>
