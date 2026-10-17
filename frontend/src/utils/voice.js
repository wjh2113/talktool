/**
 * 语音能力封装（录音 + 语音活动检测 VAD + 播放），H5 与微信小程序双端实现。
 *
 * 录音输出统一为 16kHz / 16bit / 单声道 PCM，由后端包装成 WAV 送网关识别：
 *   - H5：getUserMedia + WebAudio 采集，浏览器内降采样
 *   - 小程序：RecorderManager format=PCM，onFrameRecorded 实时计算音量做 VAD
 * 播放：
 *   - H5：WebAudio 解码播放（在“开始训练”点击时解锁，规避 iOS 自动播放限制）
 *   - 小程序：InnerAudioContext
 */

export const VAD_CONFIG = {
  calibMs: 400,        // 开头用来估计环境噪声
  minThreshold: 0.012, // 音量阈值下限（RMS，0~1）
  maxThreshold: 0.06,  // 阈值上限，避免开口太早导致阈值被抬高
  ratio: 3,            // 阈值 = 噪声 × ratio
  minSpeechMs: 250,    // 连续有声多久算“开始说话”
  silenceMs: 1400,     // 说话后静音多久算“说完了”
  maxMs: 90000         // 单轮最长录音
}

class Vad {
  constructor(cb) {
    this.cb = cb
    this.reset()
  }
  reset() {
    this.t = 0; this.noise = 0; this.noiseN = 0; this.voiceMs = 0; this.silence = 0
    this.started = false; this.done = false
  }
  feed(rms, ms) {
    if (this.done) return
    const C = this.cb.vad ? { ...VAD_CONFIG, ...this.cb.vad } : VAD_CONFIG
    this.t += ms
    this.cb.onLevel && this.cb.onLevel(rms)
    if (this.t <= C.calibMs) { this.noise += rms; this.noiseN++; return }
    const noise = this.noiseN ? this.noise / this.noiseN : 0
    const thr = Math.min(C.maxThreshold, Math.max(C.minThreshold, noise * C.ratio))
    if (rms > thr) {
      this.voiceMs += ms
      this.silence = 0
      if (!this.started && this.voiceMs >= C.minSpeechMs) { this.started = true; this.cb.onSpeechStart && this.cb.onSpeechStart() }
    } else if (this.started) {
      this.silence += ms
      if (this.silence >= C.silenceMs) this.finish()
    } else {
      this.voiceMs = Math.max(0, this.voiceMs - ms)
    }
    if (this.t >= C.maxMs) this.finish()
  }
  finish() {
    if (this.done) return
    this.done = true
    this.cb.onSpeechEnd && this.cb.onSpeechEnd()
  }
}

// ======================= H5 =======================
// #ifdef H5
let sharedCtx = null
function getCtx() {
  if (!sharedCtx) {
    const AC = window.AudioContext || window.webkitAudioContext
    sharedCtx = new AC()
  }
  return sharedCtx
}
/** 必须在用户点击事件里调用一次（“开始训练”按钮），解锁音频播放 */
export function unlockAudio() {
  try {
    const ctx = getCtx()
    if (ctx.state === 'suspended') ctx.resume()
    const buf = ctx.createBuffer(1, 1, 22050)
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(ctx.destination)
    src.start(0)
  } catch (e) { console.warn('unlockAudio', e) }
}

function downsampleToInt16(chunks, inRate, outRate = 16000) {
  let len = 0
  chunks.forEach((c) => (len += c.length))
  const input = new Float32Array(len)
  let off = 0
  chunks.forEach((c) => { input.set(c, off); off += c.length })
  const ratio = inRate / outRate
  const outLen = Math.floor(len / ratio)
  const out = new Int16Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const start = Math.floor(i * ratio)
    const end = Math.min(len, Math.floor((i + 1) * ratio))
    let sum = 0
    for (let j = start; j < end; j++) sum += input[j]
    const v = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)))
    out[i] = v < 0 ? v * 0x8000 : v * 0x7fff
  }
  return out
}

export function createRecorder(cb = {}) {
  let stream = null, source = null, proc = null
  let capturing = false, chunks = [], startAt = 0, resolver = null, vad = null

  async function init() {
    if (stream) return
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('当前浏览器不支持录音（需 HTTPS 或 localhost）')
    }
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    })
    const ctx = getCtx()
    if (ctx.state === 'suspended') await ctx.resume()
    source = ctx.createMediaStreamSource(stream)
    proc = ctx.createScriptProcessor(4096, 1, 1)
    proc.onaudioprocess = (e) => {
      if (!capturing) return
      const d = e.inputBuffer.getChannelData(0)
      chunks.push(new Float32Array(d))
      let sum = 0
      for (let i = 0; i < d.length; i++) sum += d[i] * d[i]
      vad.feed(Math.sqrt(sum / d.length), (d.length / ctx.sampleRate) * 1000)
    }
    source.connect(proc)
    proc.connect(ctx.destination)
  }

  function finish() {
    if (!capturing) return
    capturing = false
    const ctx = getCtx()
    const pcm = downsampleToInt16(chunks, ctx.sampleRate)
    chunks = []
    const r = resolver
    resolver = null
    r && r({ data: pcm.buffer, format: 'pcm', sampleRate: 16000, durationMs: Date.now() - startAt, spoke: vad.started })
  }

  return {
    init,
    /** 开始一轮监听；VAD 判定说完（或手动 stop）后 resolve 录音结果 */
    async start() {
      await init()
      chunks = []
      startAt = Date.now()
      vad = new Vad({ ...cb, onSpeechEnd: () => finish() })
      capturing = true
      return new Promise((resolve) => (resolver = resolve))
    },
    stop() { finish() },
    cancel() { capturing = false; chunks = []; resolver = null },
    destroy() {
      capturing = false
      resolver = null
      try { proc && proc.disconnect(); source && source.disconnect() } catch (e) {}
      stream && stream.getTracks().forEach((t) => t.stop())
      stream = source = proc = null
    }
  }
}

let currentSource = null
let playGen = 0
export function playAudio(url) {
  return new Promise(async (resolve) => {
    stopAudio()
    const my = playGen
    try {
      const ctx = getCtx()
      if (ctx.state === 'suspended') await ctx.resume()
      const buf = await fetch(url).then((r) => r.arrayBuffer())
      if (my !== playGen) return resolve(false)
      const audio = await ctx.decodeAudioData(buf.slice(0))
      if (my !== playGen) return resolve(false)
      const src = ctx.createBufferSource()
      src.buffer = audio
      src.connect(ctx.destination)
      src.onended = () => { if (currentSource === src) currentSource = null; resolve(true) }
      currentSource = src
      src.start(0)
    } catch (e) {
      console.warn('playAudio failed', e)
      resolve(false)
    }
  })
}
export function stopAudio() {
  playGen += 1
  try { currentSource && currentSource.stop() } catch (e) {}
  currentSource = null
}
// #endif

// ======================= 小程序 / App =======================
// #ifndef H5
export function unlockAudio() {}

let rm = null
let rmHandlers = null
function getRm() {
  if (rm) return rm
  rm = uni.getRecorderManager()
  rm.onFrameRecorded(({ frameBuffer }) => {
    if (!rmHandlers || !frameBuffer) return
    const i16 = new Int16Array(frameBuffer)
    if (!i16.length) return
    let sum = 0
    for (let i = 0; i < i16.length; i++) { const v = i16[i] / 32768; sum += v * v }
    rmHandlers.frame(Math.sqrt(sum / i16.length), (i16.length / 16000) * 1000)
  })
  rm.onStop((res) => { rmHandlers && rmHandlers.stop(res) })
  rm.onError((err) => { rmHandlers && rmHandlers.error(err) })
  return rm
}

function ensureRecordAuth() {
  return new Promise((resolve, reject) => {
    // #ifdef MP-WEIXIN
    uni.authorize({
      scope: 'scope.record',
      success: resolve,
      fail: () => {
        uni.showModal({
          title: '需要麦克风权限',
          content: '语音训练需要使用麦克风，请在设置中开启',
          confirmText: '去设置',
          success: (r) => { if (r.confirm) uni.openSetting() }
        })
        reject(new Error('未授权麦克风'))
      }
    })
    // #endif
    // #ifndef MP-WEIXIN
    resolve()
    // #endif
  })
}

export function createRecorder(cb = {}) {
  let vad = null, resolver = null, active = false, cancelled = false, authed = false
  const manager = getRm()

  return {
    async init() {
      if (!authed) { await ensureRecordAuth(); authed = true }
    },
    async start() {
      await this.init()
      cancelled = false
      vad = new Vad({ ...cb, onSpeechEnd: () => active && manager.stop() })
      return new Promise((resolve, reject) => {
        resolver = resolve
        rmHandlers = {
          frame: (rms, ms) => vad && vad.feed(rms, ms),
          stop: (res) => {
            active = false
            const r = resolver
            resolver = null
            if (cancelled || !r) return
            r({ filePath: res.tempFilePath, format: 'pcm', sampleRate: 16000, durationMs: res.duration, spoke: vad.started })
          },
          error: (err) => { active = false; resolver = null; reject(new Error(err.errMsg || '录音失败')) }
        }
        active = true
        manager.start({
          duration: 600000,
          sampleRate: 16000,
          numberOfChannels: 1,
          encodeBitRate: 48000,
          format: 'PCM',
          frameSize: 2
        })
      })
    },
    stop() { if (active) manager.stop() },
    cancel() { cancelled = true; if (active) manager.stop() },
    destroy() { cancelled = true; if (active) manager.stop(); rmHandlers = null }
  }
}

let player = null
export function playAudio(url) {
  return new Promise((resolve) => {
    stopAudio()
    player = uni.createInnerAudioContext()
    // #ifdef MP-WEIXIN
    if (uni.setInnerAudioOption) uni.setInnerAudioOption({ obeyMuteSwitch: false })
    // #endif
    const p = player
    let finished = false
    const done = (ok) => {
      if (finished) return
      finished = true
      try { p.destroy() } catch (e) {}
      if (player === p) player = null
      resolve(ok)
    }
    p.onEnded(() => done(true))
    p.onError((e) => { console.warn('play error', e); done(false) })
    p.onStop(() => done(true))
    p.src = url
    p.play()
  })
}
export function stopAudio() {
  if (player) { try { player.stop() } catch (e) {} }
}
// #endif

/** 没有音频（Mock 模式或合成失败）时，按文字长度模拟“AI 讲话”的时长 */
export function simulateSpeaking(text) {
  const ms = Math.min(12000, Math.max(1500, (text || '').length * 230))
  return new Promise((r) => setTimeout(r, ms))
}
