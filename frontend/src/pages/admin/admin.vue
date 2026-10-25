<template>
  <view class="page">
    <view class="tabs">
      <view class="tab" :class="{ on: tab === 'invites' }" @tap="tab = 'invites'">邀请码</view>
      <view class="tab" :class="{ on: tab === 'users' }" @tap="switchUsers">用户（{{ users.length || '…' }}）</view>
      <view class="tab" :class="{ on: tab === 'catalog' }" @tap="tab = 'catalog'">场景导入</view>
    </view>
    <view class="advisor-links">
      <text class="advisor-link" @tap="goPage('/pages/admin-prompts/admin-prompts')">智囊提示词管理 ›</text>
      <text class="advisor-link" @tap="goPage('/pages/admin-councils/admin-councils')">智囊团配置 ›</text>
      <text class="advisor-link" @tap="goPage('/pages/admin-advisor-stats/admin-advisor-stats')">问计效果统计 ›</text>
    </view>

    <!-- 邀请码 -->
    <block v-if="tab === 'invites'">
      <view class="card form">
        <text class="block-title">生成邀请码</text>
        <view class="row">
          <view class="cell">
            <text class="label">数量</text>
            <input v-model="gen.count" class="input" type="number" maxlength="2" />
          </view>
          <view class="cell">
            <text class="label">每个可用次数</text>
            <input v-model="gen.max_uses" class="input" type="number" maxlength="4" />
          </view>
          <view class="cell">
            <text class="label">有效天数</text>
            <input v-model="gen.expires_days" class="input" type="number" maxlength="3" placeholder="0=永久" />
          </view>
        </view>
        <text class="label">备注（选填，如“销售部”）</text>
        <input v-model="gen.note" class="input" maxlength="50" />
        <view class="btn-primary gen" @tap="createInvites">生成</view>

        <view v-if="fresh.length" class="fresh">
          <view class="fresh-head">
            <text class="fresh-title">刚生成的 {{ fresh.length }} 个邀请码</text>
            <text class="link" @tap="copyAll">全部复制</text>
          </view>
          <text v-for="c in fresh" :key="c.code" class="fresh-code" @tap="copy(c.code)">{{ c.code }}</text>
        </view>
      </view>

      <view v-for="i in invites" :key="i.code" class="card item">
        <view class="item-top">
          <text class="code" @tap="copy(i.code)">{{ i.code }}</text>
          <text class="state" :class="i.state">{{ STATE_TEXT[i.state] }}</text>
        </view>
        <text class="meta">已用 {{ i.used_count }}/{{ i.max_uses }} · {{ i.expires_at ? '至 ' + i.expires_at.slice(0, 16) : '永不过期' }}{{ i.note ? ' · ' + i.note : '' }}</text>
        <text v-if="i.used_by" class="meta">使用者：{{ i.used_by }}</text>
        <view class="actions">
          <text class="act" @tap="copy(i.code)">复制码</text>
          <text v-if="canLink" class="act" @tap="copyLink(i.code)">复制注册链接</text>
          <text v-if="i.state === 'active'" class="act danger" @tap="disable(i)">停用</text>
        </view>
      </view>
      <view v-if="!invites.length" class="empty muted">还没有邀请码</view>
    </block>

    <!-- 场景导入 -->
    <block v-else-if="tab === 'catalog'">
      <view class="card form">
        <text class="block-title">导入场景库 / 表达框架 / 谋略库</text>
        <text class="hint">支持单个 .md，或 .zip（内含多个 md）。场景按标题、框架和谋略 / 谋士 / 智囊团按 code 更新或新增，不会删除库里多出来的内容。导入的谋略类内容以后程序升级不会覆盖。</text>
        <text class="label">导入模式</text>
        <view class="mode-row">
          <view class="mode" :class="{ on: importMode === 'upsert' }" @tap="importMode = 'upsert'">更新或新增</view>
          <view class="mode" :class="{ on: importMode === 'add_only' }" @tap="importMode = 'add_only'">仅新增</view>
        </view>
        <view class="btn-primary gen" :class="{ dim: importing }" @tap="pickImport">{{ importing ? '导入中…' : '选择文件并导入' }}</view>
        <text class="hint linkish" @tap="copyPromptHint">复制「发给大模型的整理提示词」说明路径</text>
      </view>
      <view v-if="importResult" class="card item">
        <text class="uname">导入结果</text>
        <text class="meta">{{ importResult.summary }}</text>
        <text class="meta">模式 {{ importResult.mode }} · 文件 {{ (importResult.files || []).map((f) => f.name + '(' + f.kind + ')').join('、') || '—' }}</text>
        <text class="meta">框架 +{{ importResult.frameworks && importResult.frameworks.added }} / 改 {{ importResult.frameworks && importResult.frameworks.updated }}</text>
        <text class="meta">训练 +{{ importResult.catalog && importResult.catalog.drills_added }} / 改 {{ importResult.catalog && importResult.catalog.drills_updated }} / 跳过 {{ importResult.catalog && importResult.catalog.drills_skipped }}</text>
        <text v-for="(w, i) in importResult.warnings || []" :key="i" class="meta warn">⚠ {{ w }}</text>
      </view>
    </block>

    <!-- 用户 -->
    <block v-else>
      <view v-for="u in users" :key="u.id" class="card item">
        <view class="item-top">
          <text class="uname">{{ u.nickname }}<text class="muted"> @{{ u.username }}</text></text>
          <text v-if="u.role === 'admin'" class="state admin">管理员</text>
          <text v-else class="state" :class="u.status === 'active' ? 'active' : 'disabled'">{{ u.status === 'active' ? '正常' : '已停用' }}</text>
        </view>
        <text class="meta">训练 {{ u.sessions }} 次 · 最近训练 {{ u.last_session_at ? u.last_session_at.slice(0, 16) : '—' }}</text>
        <text class="meta">注册 {{ u.created_at.slice(0, 16) }}{{ u.invite_code ? ' · 邀请码 ' + u.invite_code : '' }} · 最近登录 {{ u.last_login_at ? u.last_login_at.slice(0, 16) : '—' }}</text>
        <view v-if="u.id !== me.id" class="actions">
          <text class="act" @tap="resetPwd(u)">重置密码</text>
          <text v-if="u.status === 'active'" class="act danger" @tap="setStatus(u, 'disabled')">停用</text>
          <text v-else class="act" @tap="setStatus(u, 'active')">启用</text>
        </view>
      </view>
    </block>
  </view>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { onLoad, onPullDownRefresh } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { getCurrentUser } from '../../utils/request'

const STATE_TEXT = { active: '可用', used_up: '已用完', expired: '已过期', disabled: '已停用' }
const tab = ref('invites')
const goPage = (url) => uni.navigateTo({ url })
const invites = ref([])
const users = ref([])
const fresh = ref([])
const me = ref(getCurrentUser() || {})
const gen = reactive({ count: '5', max_uses: '1', expires_days: '30', note: '' })
const importMode = ref('upsert')
const importing = ref(false)
const importResult = ref(null)
let canLink = false
// #ifdef H5
canLink = true
// #endif

async function loadInvites() {
  invites.value = await api.adminInvites()
}
async function loadUsers() {
  users.value = await api.adminUsers()
}
function switchUsers() {
  tab.value = 'users'
  loadUsers()
}

function copyPromptHint() {
  copy('场景：docs/场景库导入-发给大模型的提示词.md；谋略库：docs/谋略库导入-发给大模型的提示词.md（仓库内）', '路径已复制')
}

function pickImport() {
  if (importing.value) return
  // #ifdef H5
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.md,.markdown,.txt,.zip,text/markdown,application/zip'
  input.onchange = async () => {
    const f = input.files && input.files[0]
    if (!f) return
    await doImport(f)
  }
  input.click()
  // #endif
  // #ifndef H5
  uni.chooseMessageFile({
    count: 1,
    type: 'file',
    extension: ['md', 'markdown', 'txt', 'zip'],
    success: async (res) => {
      const path = res.tempFiles && res.tempFiles[0] && res.tempFiles[0].path
      if (!path) return
      await doImport(path)
    }
  })
  // #endif
}

async function doImport(fileOrPath) {
  importing.value = true
  importResult.value = null
  try {
    const res = await api.adminCatalogImport(fileOrPath, importMode.value)
    importResult.value = res
    uni.showToast({ title: res.summary || '导入完成', icon: 'none', duration: 3000 })
  } catch (e) {
    /* toast 已由 request 处理 */
  } finally {
    importing.value = false
  }
}

async function createInvites() {
  const res = await api.adminCreateInvites({
    count: Number(gen.count) || 1,
    max_uses: Number(gen.max_uses) || 1,
    expires_days: Number(gen.expires_days) || 0,
    note: gen.note
  })
  fresh.value = res
  loadInvites()
}

function copy(text, tip = '已复制') {
  uni.setClipboardData({ data: text, success: () => uni.showToast({ title: tip, icon: 'none' }) })
}
function copyAll() {
  copy(fresh.value.map((c) => c.code).join('\n'), `已复制 ${fresh.value.length} 个邀请码`)
}
function copyLink(code) {
  // #ifdef H5
  copy(`${location.origin}${location.pathname}#/pages/login/login?code=${code}`, '注册链接已复制')
  // #endif
}

function disable(i) {
  uni.showModal({
    title: `停用邀请码 ${i.code}？`,
    content: '已经用它注册的账号不受影响。',
    success: async (r) => {
      if (!r.confirm) return
      await api.adminDisableInvite(i.code)
      loadInvites()
    }
  })
}

function setStatus(u, status) {
  uni.showModal({
    title: status === 'disabled' ? `停用 ${u.username}？` : `启用 ${u.username}？`,
    content: status === 'disabled' ? '停用后会立刻退出登录，无法再登录。' : '',
    success: async (r) => {
      if (!r.confirm) return
      await api.adminSetUserStatus(u.id, status)
      loadUsers()
    }
  })
}

function resetPwd(u) {
  uni.showModal({
    title: `重置 ${u.username} 的密码？`,
    content: '会生成一个临时密码，并让该用户所有设备退出登录。',
    success: async (r) => {
      if (!r.confirm) return
      const res = await api.adminResetPassword(u.id)
      uni.showModal({
        title: '临时密码（只显示这一次）',
        content: res.temp_password,
        confirmText: '复制',
        success: (x) => x.confirm && copy(res.temp_password)
      })
    }
  })
}

onLoad(() => {
  if (me.value.role !== 'admin') {
    uni.showToast({ title: '需要管理员权限', icon: 'none' })
    setTimeout(() => uni.navigateBack(), 800)
    return
  }
  loadInvites()
  loadUsers()
})
onPullDownRefresh(async () => {
  try {
    if (tab.value === 'invites') await loadInvites()
    else if (tab.value === 'users') await loadUsers()
  } finally {
    uni.stopPullDownRefresh()
  }
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 24rpx 32rpx 60rpx; box-sizing: border-box; }
.tabs { display: flex; gap: 18rpx; margin-bottom: 24rpx; flex-wrap: wrap; }
.tab {
  padding: 0 32rpx; height: 72rpx; line-height: 72rpx; border-radius: 14rpx; background: #fff; border: 1rpx solid #E3E7ED; font-size: 28rpx;
  &.on { background: $tt-primary; border-color: $tt-primary; color: #fff; font-weight: 600; }
}
.form { padding: 32rpx; margin-bottom: 28rpx; }
.block-title { display: block; font-size: 30rpx; font-weight: 700; margin-bottom: 20rpx; }
.hint { display: block; font-size: 24rpx; color: $tt-text-3; line-height: 1.6; margin-bottom: 20rpx; }
.linkish { color: $tt-primary; margin-top: 16rpx; }
.mode-row { display: flex; gap: 16rpx; margin-bottom: 8rpx; }
.mode {
  flex: 1; text-align: center; height: 72rpx; line-height: 72rpx; border-radius: 12rpx;
  background: #F7F9FC; border: 1rpx solid #E3E7ED; font-size: 26rpx; color: $tt-text-2;
  &.on { background: $tt-soft; border-color: $tt-soft-border; color: $tt-primary; font-weight: 600; }
}
.row { display: flex; gap: 16rpx; margin-bottom: 16rpx; }
.cell { flex: 1; }
.label { display: block; font-size: 23rpx; color: $tt-text-2; margin-bottom: 8rpx; }
.input { height: 76rpx; padding: 0 20rpx; border-radius: 12rpx; background: #F7F9FC; border: 1rpx solid #E3E7ED; font-size: 28rpx; }
.gen { margin-top: 28rpx; &.dim { opacity: 0.55; } }
.fresh { margin-top: 28rpx; padding: 24rpx; border-radius: 16rpx; background: $tt-soft; border: 1rpx solid $tt-soft-border; }
.fresh-head { display: flex; justify-content: space-between; margin-bottom: 14rpx; }
.fresh-title { font-size: 26rpx; font-weight: 600; }
.fresh-code { display: inline-block; font-family: Menlo, monospace; font-size: 32rpx; letter-spacing: 4rpx; margin: 6rpx 24rpx 6rpx 0; color: $tt-primary; }
.link { font-size: 26rpx; color: $tt-primary; }
.item { padding: 28rpx 32rpx; margin-bottom: 20rpx; }
.item-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10rpx; }
.code { font-family: Menlo, monospace; font-size: 34rpx; font-weight: 700; letter-spacing: 4rpx; }
.uname { font-size: 30rpx; font-weight: 700; }
.state {
  font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 8rpx; background: #F0F2F5; color: $tt-text-3;
  &.active { background: #E7F7EE; color: #22A060; }
  &.admin { background: $tt-tag-bg; color: $tt-primary; }
  &.disabled { background: #FDECEC; color: #E5484D; }
}
.meta { display: block; font-size: 24rpx; color: $tt-text-2; line-height: 1.7; }
.actions { display: flex; gap: 32rpx; margin-top: 14rpx; }
.act { font-size: 26rpx; color: $tt-primary; &.danger { color: #E5484D; } }
.empty { text-align: center; padding: 60rpx 0; }
.advisor-links { display: flex; gap: 32rpx; padding: 8rpx 8rpx 20rpx; }
.advisor-link { font-size: 26rpx; color: $tt-primary; }
.warn { color: #B7791F; }
</style>
