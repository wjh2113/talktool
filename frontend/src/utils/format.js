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

// 场景封面：没有图片时按分类给一个渐变色
const PALETTE = {
  职场赋能: ['#5AA9F8', '#2F7FDB'],
  酒桌文化: ['#F6A86B', '#E0704A'],
  求职面试: ['#6CC5B0', '#2E9C86'],
  社交建联: ['#8F9CF6', '#5B67D8'],
  亲密关系: ['#F59AB4', '#DD6489'],
  冲突化解: ['#F38A80', '#D2544B'],
  共赢协商: ['#7CC9E8', '#3A97C4'],
  当众表达: ['#6AA8F2', '#3C78D8']
}
export function coverStyle(category) {
  const [a, b] = PALETTE[category] || ['#7FB6F4', '#3B85DB']
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
    else if ((m = line.match(/^>\s?(.*)$/))) { flush(); out.push(`<p style="color:#999;border-left:3px solid #E8F4FE;padding-left:8px;margin:6px 0;">${inline(m[1])}</p>`) }
    else { flush(); out.push(`<p style="margin:6px 0;">${inline(line)}</p>`) }
  }
  flush()
  return `<div style="font-size:14px;line-height:1.75;color:#444;">${out.join('')}</div>`
}
