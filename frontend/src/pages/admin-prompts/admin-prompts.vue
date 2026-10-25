<template>
  <view class="page">
    <!-- 列表 -->
    <view v-if="!cur">
      <text class="intro muted">工作流每一步用一份提示词。改完先「保存草稿」并「试运行」，满意再「发布」；随时可以回滚或恢复默认。建议在电脑浏览器里修改。</text>
      <view v-for="g in groups" :key="g.name">
        <text class="group">{{ g.name }}</text>
        <view v-for="p in g.items" :key="p.key" class="card row" @tap="open(p.key)">
          <view class="row-body">
            <text class="row-name">{{ p.name }}</text>
            <text class="muted">{{ p.key }} · {{ p.capability }}</text>
          </view>
          <text class="ver" :class="{ custom: p.active_version }">{{ p.active_version ? 'v' + p.active_version : '默认版' }}</text>
          <text v-if="p.has_draft" class="draft">有草稿</text>
        </view>
      </view>
    </view>

    <!-- 编辑 -->
    <view v-else>
      <view class="bar">
        <text class="back" @tap="cur = null; loadList()">‹ 返回列表</text>
        <text class="cur-name">{{ cur.name }}</text>
      </view>
      <view class="card box">
        <text class="muted">当前生效：{{ cur.active ? 'v' + cur.active.version + '（' + cur.active.created_at.slice(0, 16) + '）' : '代码默认版' }}
          {{ cur.draft ? ' · 草稿 v' + cur.draft.version : '' }}</text>
        <text class="label">可用变量（点击复制）</text>
        <view class="vars">
          <text v-for="v in cur.variables" :key="v" class="var" :class="{ req: cur.required.includes(v) }" @tap="copyVar(v)">{{ varLabel(v) }}</text>
        </view>
        <text class="muted small">深色的是必填变量；输出格式：{{ cur.output === 'json' ? 'JSON（请保留输出 JSON 的要求）' : '纯文本' }}</text>

        <text class="label">系统设定</text>
        <textarea v-model="form.system" class="ta" :maxlength="-1" auto-height />
        <text class="label">消息模板</text>
        <textarea v-model="form.user" class="ta tall" :maxlength="-1" auto-height />

        <view class="params">
          <view class="param">
            <text class="label">能力</text>
            <view class="seg">
              <text v-for="cap in ['fast-chat', 'quality-chat']" :key="cap" class="seg-i" :class="{ on: form.capability === cap }" @tap="form.capability = cap">{{ cap }}</text>
            </view>
          </view>
          <view class="param">
            <text class="label">最大输出</text>
            <input v-model="form.max_tokens" class="num" type="number" />
          </view>
          <view class="param">
            <text class="label">温度</text>
            <input v-model="form.temperature" class="num" type="digit" />
          </view>
        </view>
        <text class="label">修改说明</text>
        <input v-model="form.note" class="note" placeholder="这次改了什么（可选）" />

        <view class="btns">
          <view class="btn-plain" @tap="saveDraft">保存草稿</view>
          <view class="btn-primary" :class="{ off: !cur.draft }" @tap="publish">发布草稿</view>
        </view>
      </view>

      <text class="block-title">试运行</text>
      <view class="card box">
        <textarea v-model="testMsg" class="ta" auto-height :placeholder="cur.key === 'memory_compact' ? '输入几条记忆，用换行或分号隔开，例如：王总看重数据；王总周一最忙；王总喜欢看数据' : '输入一个测试问题，例如：新领导总在会上否定我的方案'" />
        <view class="btns">
          <view class="btn-primary" :class="{ off: testing }" @tap="runTest">{{ testing ? '运行中…' : '用编辑框里的内容试运行' }}</view>
        </view>
        <view v-if="testOut" class="out">
          <text class="out-k">意图识别：{{ testOut.intent.council }} · 置信度 {{ testOut.intent.confidence }} · 路由 {{ testOut.route }}</text>
          <text class="code">{{ pretty(testOut.output) }}</text>
        </view>
      </view>

      <text class="block-title">版本历史</text>
      <view class="card box">
        <view v-for="h in cur.history" :key="h.version" class="hist">
          <text class="hist-v">v{{ h.version }}</text>
          <text class="hist-s" :class="h.status">{{ h.status === 'active' ? '生效中' : '历史' }}</text>
          <text class="hist-note">{{ h.note || '—' }} · {{ h.created_at.slice(5, 16) }}</text>
          <text v-if="cur.ratings && cur.ratings[h.version]" class="hist-rate">{{ rateText(cur.ratings[h.version]) }}</text>
          <text v-if="h.status !== 'active'" class="link" @tap="rollback(h.version)">回滚到此版</text>
        </view>
        <text v-if="!cur.history.length" class="muted">还没有发布过，一直在用默认版</text>
        <text v-if="cur.ratings && cur.ratings['0']" class="muted">默认版：{{ rateText(cur.ratings['0']) }}</text>
        <view class="btns">
          <view class="btn-plain" @tap="loadDefault">把默认版填进编辑框</view>
          <view class="btn-plain danger" @tap="reset">恢复默认</view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'

const list = ref([])
const cur = ref(null)
const form = ref({})
const testMsg = ref('')
const testOut = ref(null)
const testing = ref(false)

const groups = computed(() => {
  const g = [
    { name: '识别与路由', items: list.value.filter((p) => ['intent', 'clarify', 'safety'].includes(p.key)) },
    { name: '各智囊团出谋', items: list.value.filter((p) => p.key.startsWith('council.')) },
    { name: '追问、圆桌与记忆', items: list.value.filter((p) => ['followup', 'roundtable', 'memory_extract', 'memory_compact'].includes(p.key)) }
  ]
  return g.filter((x) => x.items.length)
})

// 这个版本出的锦囊被评“有用”的比例
const rateText = (r) => (r.rated ? `👍 ${Math.round(r.up_rate * 100)}%（${r.rated} 评 / ${r.plans} 份）` : `${r.plans} 份，暂无评价`)

async function loadList() {
  list.value = await api.adminPrompts()
}

function fill(src) {
  form.value = {
    system: src.system, user: src.user, capability: src.capability,
    max_tokens: String(src.max_tokens), temperature: String(src.temperature ?? ''), note: src.note || ''
  }
}

async function open(key) {
  cur.value = await api.adminPrompt(key)
  fill(cur.value.draft || cur.value.active || cur.value.default)
  testOut.value = null
}

function body() {
  return { ...form.value, max_tokens: Number(form.value.max_tokens) || null, temperature: form.value.temperature === '' ? null : Number(form.value.temperature) }
}

async function saveDraft() {
  cur.value = await api.adminSavePrompt(cur.value.key, body())
  uni.showToast({ title: '草稿已保存', icon: 'none' })
}

function publish() {
  if (!cur.value.draft) return uni.showToast({ title: '先保存草稿', icon: 'none' })
  uni.showModal({ title: '发布草稿？', content: '发布后所有用户的问计都会用这一版', success: async (r) => {
    if (r.confirm) {
      cur.value = await api.adminPublishPrompt(cur.value.key)
      uni.showToast({ title: '已发布', icon: 'none' })
    }
  } })
}

async function runTest() {
  if (testing.value) return
  if (testMsg.value.trim().length < 4) return uni.showToast({ title: '先输入一个测试问题', icon: 'none' })
  testing.value = true
  testOut.value = null
  try {
    testOut.value = await api.adminTestPrompt(cur.value.key, testMsg.value.trim(), body())
  } finally {
    testing.value = false
  }
}

function rollback(v) {
  uni.showModal({ title: `回滚到 v${v}？`, content: '会生成一个内容相同的新版本并立即生效', success: async (r) => {
    if (r.confirm) {
      cur.value = await api.adminRollbackPrompt(cur.value.key, v)
      fill(cur.value.active)
    }
  } })
}

function reset() {
  uni.showModal({ title: '恢复默认？', content: '当前生效的版本会归档，草稿会删除，之后用代码里的默认版', success: async (r) => {
    if (r.confirm) {
      cur.value = await api.adminResetPrompt(cur.value.key)
      fill(cur.value.default)
    }
  } })
}

const loadDefault = () => fill(cur.value.default)
const varLabel = (v) => '{' + '{' + v + '}' + '}'
const copyVar = (v) => uni.setClipboardData({ data: varLabel(v) })
const pretty = (o) => (typeof o === 'string' ? o : JSON.stringify(o, null, 2))

onLoad(async (q) => {
  await loadList()
  if (q && q.key) open(decodeURIComponent(q.key))
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 24rpx 28rpx 80rpx; box-sizing: border-box; }
.intro { display: block; line-height: 1.7; margin-bottom: 12rpx; }
.group { display: block; font-size: 27rpx; font-weight: 700; margin: 28rpx 4rpx 14rpx; }
.row { display: flex; align-items: center; gap: 14rpx; padding: 24rpx 28rpx; margin-bottom: 14rpx; }
.row-body { flex: 1; display: flex; flex-direction: column; }
.row-name { font-size: 28rpx; font-weight: 600; }
.ver { font-size: 22rpx; color: $tt-text-3; }
.ver.custom { color: $tt-primary; font-weight: 600; }
.draft { font-size: 20rpx; color: #B7791F; background: #FFF6E5; padding: 2rpx 10rpx; border-radius: 6rpx; }
.bar { display: flex; align-items: center; gap: 20rpx; margin-bottom: 16rpx; }
.back { color: $tt-primary; font-size: 27rpx; }
.cur-name { font-size: 30rpx; font-weight: 700; }
.box { padding: 26rpx 28rpx; margin-bottom: 20rpx; display: flex; flex-direction: column; }
.label { font-size: 24rpx; color: $tt-text-2; margin: 22rpx 0 10rpx; }
.vars { display: flex; flex-wrap: wrap; gap: 10rpx; }
.var { font-size: 22rpx; padding: 4rpx 12rpx; border-radius: 8rpx; background: $tt-bg; color: $tt-text-2; font-family: monospace; }
.var.req { background: $tt-tag-bg; color: $tt-primary-deep; font-weight: 600; }
.small { font-size: 21rpx; margin-top: 8rpx; }
.ta { width: 100%; min-height: 160rpx; box-sizing: border-box; padding: 16rpx 18rpx; background: $tt-bg; border-radius: 12rpx; font-size: 24rpx; line-height: 1.6; font-family: monospace; }
.ta.tall { min-height: 400rpx; }
.params { display: flex; gap: 16rpx; flex-wrap: wrap; }
.param { display: flex; flex-direction: column; }
.seg { display: flex; border-radius: 10rpx; overflow: hidden; border: 1rpx solid $tt-soft-border; }
.seg-i { font-size: 22rpx; padding: 10rpx 16rpx; color: $tt-text-2; }
.seg-i.on { background: $tt-primary; color: #fff; }
.num { width: 140rpx; height: 60rpx; background: $tt-bg; border-radius: 10rpx; padding: 0 14rpx; font-size: 25rpx; }
.note { height: 64rpx; background: $tt-bg; border-radius: 10rpx; padding: 0 16rpx; font-size: 25rpx; }
.btns { display: flex; gap: 16rpx; margin-top: 24rpx; }
.btns > view { flex: 1; }
.off { opacity: 0.45; }
.danger { color: #E5564B; }
.block-title { display: block; font-size: 29rpx; font-weight: 700; margin: 24rpx 4rpx 14rpx; }
.out { margin-top: 20rpx; display: flex; flex-direction: column; gap: 10rpx; }
.out-k { font-size: 24rpx; color: $tt-primary; }
.code { font-size: 22rpx; font-family: monospace; white-space: pre-wrap; background: #F7F9F8; padding: 16rpx; border-radius: 10rpx; line-height: 1.5; }
.hist { display: flex; align-items: center; gap: 14rpx; padding: 12rpx 0; border-bottom: 1rpx solid #F0F2F1; }
.hist-v { font-size: 25rpx; font-weight: 700; width: 60rpx; }
.hist-s { font-size: 21rpx; color: $tt-text-3; }
.hist-s.active { color: $tt-primary; }
.hist-rate { font-size: 21rpx; color: $tt-primary; flex-shrink: 0; }
.hist-note { flex: 1; font-size: 23rpx; color: $tt-text-2; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.link { color: $tt-primary; font-size: 23rpx; }
</style>
