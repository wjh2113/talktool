/**
 * 示范朗读（对齐小树学堂）：
 * - 进页预取首句，点「听示范」时少干等合成
 * - 长文分句：首句 ≤60 字尽快出声，边播边取下一句
 * - 本页内存缓存同一句不重复请求
 */
import { api } from './api'
import { absUrl } from './request'
import { playAudio, stopAudio, unlockAudio } from './voice'

const audioCache = new Map() // text -> Promise<url|null>
const AUDIO_CACHE_MAX = 40
let seq = 0

/** 切成短句；第一段尽快出声，之后略长。 */
export function splitSentences(text, max = 120, firstMax = 60) {
  const t = String(text || '').replace(/\s+/g, ' ').trim()
  if (!t) return []
  const pieces = t.match(/[^。！？!?；;\n.]+(?:\.(?!\s|$)[^。！？!?；;\n.]*)*[。！？!?；;.”"』」）)]*|[。！？!?；;.]+/g) || [t]
  const out = []
  let cur = ''
  const limit = () => (out.length === 0 ? firstMax : max)
  for (const raw of pieces) {
    if (!raw.trim()) continue
    let p = cur ? raw : raw.trimStart()
    while (p.length > limit()) {
      if (cur) {
        out.push(cur.trim())
        cur = ''
        p = p.trimStart()
        continue
      }
      const lim = limit()
      const cut = Math.max(p.lastIndexOf('，', lim), p.lastIndexOf(',', lim), p.lastIndexOf('、', lim))
      const at = cut >= 10 ? cut + 1 : lim
      out.push(p.slice(0, at).trim())
      p = p.slice(at).trimStart()
    }
    if (!p) continue
    if (cur && (cur + p).length > limit()) {
      out.push(cur.trim())
      cur = p.trimStart()
    } else {
      cur += p
    }
  }
  if (cur.trim()) out.push(cur.trim())
  return out.filter(Boolean)
}

function getAudioUrl(text) {
  const key = text
  let p = audioCache.get(key)
  if (p) {
    audioCache.delete(key)
    audioCache.set(key, p)
    return p
  }
  p = api
    .tts(text)
    .then((r) => (r && r.audio_url ? absUrl(r.audio_url) : null))
    .catch((e) => {
      if (audioCache.get(key) === p) audioCache.delete(key)
      throw e
    })
  audioCache.set(key, p)
  while (audioCache.size > AUDIO_CACHE_MAX) audioCache.delete(audioCache.keys().next().value)
  return p
}

/** 文字一出来就预取首句，点播放时不用干等整段合成 */
export function prefetch(text) {
  const first = splitSentences(text)[0]
  if (first) getAudioUrl(first).catch(() => {})
}

export function stopDemo() {
  seq += 1
  stopAudio()
}

/**
 * 分句朗读。须在点击同步阶段先 unlockAudio()。
 * @param {object} [opts]
 * @param {() => void} [opts.onStart] 首句音频就绪、即将播放时回调（用于把「合成中」切成「停止」）
 * @returns {Promise<boolean>} 是否播过至少一句
 */
export async function speakDemo(text, opts = {}) {
  unlockAudio()
  const my = (seq += 1)
  const chunks = splitSentences(text)
  if (!chunks.length) return false
  let played = false
  for (let i = 0; i < chunks.length; i++) {
    if (my !== seq) return played
    const urlP = getAudioUrl(chunks[i])
    if (i + 1 < chunks.length) getAudioUrl(chunks[i + 1]).catch(() => {})
    let url = null
    try {
      url = await urlP
    } catch (e) {
      if (i === 0) throw e
      continue
    }
    if (my !== seq) return played
    if (!url) {
      if (i === 0) return false
      continue
    }
    if (!played) {
      played = true
      opts.onStart && opts.onStart()
    }
    await playAudio(url)
    if (my !== seq) return played
  }
  return played
}
