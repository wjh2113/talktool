export const STATUS_TEXT = {
  completed: '已完成',
  too_short: '时长过短',
  abandoned: '主动放弃',
  in_progress: '进行中'
}

export function mmss(sec) {
  sec = Math.max(0, Math.floor(sec || 0))
  const m = String(Math.floor(sec / 60)).padStart(2, '0')
  const s = String(sec % 60).padStart(2, '0')
  return `${m}:${s}`
}

export function durationText(sec) {
  sec = Math.max(0, Math.floor(sec || 0))
  return `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
}

// 场景封面：没有图片时按分类给一个渐变色（与青绿主色协调，避开旧天蓝）
const PALETTE = {
  职场赋能: ['#1AA897', '#0B6B5F'],
  酒桌文化: ['#E8A05A', '#C46B2E'],
  求职面试: ['#3DB89A', '#1A7A66'],
  社交建联: ['#4A9B8C', '#2A6B5E'],
  亲密关系: ['#E07A8A', '#B84A5C'],
  冲突化解: ['#E07060', '#B8483A'],
  共赢协商: ['#2BB3A0', '#0E7A6C'],
  当众表达: ['#3C8F7E', '#1A5F52'],
  自媒体口播: ['#5CB8A6', '#2A7A6C']
}
export function coverStyle(category) {
  const [a, b] = PALETTE[category] || ['#1AA897', '#0B6B5F']
  return `background: linear-gradient(135deg, ${a} 0%, ${b} 100%);`
}

/** 极简 Markdown → HTML（rich-text 用，H5 和小程序都支持） */
export function mdToHtml(md = '') {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`(.+?)`/g, '<code>$1</code>')
  const out = []
  let list = null
  const flush = () => { if (list) { out.push(`<${list.t} style="padding-left:1.2em;margin:6px 0;">${list.items.join('')}</${list.t}>`); list = null } }
  for (const raw of md.split('\n')) {
    const line = raw.trim()
    let m
    if (!line) { flush(); continue }
    if ((m = line.match(/^#{1,6}\s+(.*)$/))) { flush(); out.push(`<p style="font-weight:600;margin:10px 0 4px;color:#1F2329;">${inline(m[1])}</p>`) }
    else if ((m = line.match(/^[-*]\s+(.*)$/))) { if (!list || list.t !== 'ul') { flush(); list = { t: 'ul', items: [] } } list.items.push(`<li>${inline(m[1])}</li>`) }
    else if ((m = line.match(/^\d+[.、]\s*(.*)$/))) { if (!list || list.t !== 'ol') { flush(); list = { t: 'ol', items: [] } } list.items.push(`<li>${inline(m[1])}</li>`) }
    else if ((m = line.match(/^>\s?(.*)$/))) { flush(); out.push(`<p style="color:#8A9691;border-left:3px solid #D8F3EE;padding-left:8px;margin:6px 0;">${inline(m[1])}</p>`) }
    else { flush(); out.push(`<p style="margin:6px 0;">${inline(line)}</p>`) }
  }
  flush()
  return `<div style="font-size:14px;line-height:1.75;color:#444;">${out.join('')}</div>`
}
