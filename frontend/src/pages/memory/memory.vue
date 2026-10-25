<template>
  <view class="page">
    <view class="card switch-card">
      <view class="sw-text">
        <text class="sw-title">长期记忆</text>
        <text class="muted">{{ m.paused ? '已暂停：智囊不会记录，也不会参考已有记忆' : '开启中：智囊会记住你说过的人和事，下次不用再从头说' }}</text>
      </view>
      <switch :checked="!m.paused" color="#0D8A7B" @change="togglePause" />
    </view>

    <view class="tabs">
      <text v-for="t in tabs" :key="t.k" class="tab" :class="{ on: tab === t.k }" @tap="tab = t.k">{{ t.n }}</text>
    </view>

    <!-- 我的档案 -->
    <view v-if="tab === 'profile'">
      <view class="card box">
        <view v-for="i in m.profile" :key="i.id" class="item">
          <view class="item-body" @tap="editItem(i)">
            <text class="item-text">{{ i.pinned ? '📌 ' : '' }}{{ i.text }}</text>
            <text class="src">{{ i.source }}</text>
          </view>
          <text class="del" @tap="delItem(i)">删除</text>
        </view>
        <text v-if="!m.profile.length" class="empty muted">还没有记录。和智囊聊过之后，它会记下你的职业、角色和沟通偏好。</text>
        <text class="add" @tap="addProfile">＋ 自己写一条</text>
      </view>
    </view>

    <!-- 人物卡 / 事件线 -->
    <view v-if="tab === 'people' || tab === 'cases'">
      <view v-for="s in list" :key="s.id" class="card box subject">
        <view class="s-head">
          <text class="s-name">{{ s.name }}</text>
          <text v-if="tab === 'cases'" class="s-status" :class="s.status">{{ statusText[s.status] }}</text>
          <text class="s-op" @tap="subjectMenu(s)">管理</text>
        </view>
        <text v-if="s.aliases.length" class="muted">也叫：{{ s.aliases.join('、') }}</text>
        <text v-if="s.summary" class="s-summary">{{ s.summary }}</text>
        <view v-for="i in s.items" :key="i.id" class="item">
          <view class="item-body" @tap="editItem(i)">
            <text class="item-text">{{ i.text }}</text>
            <text class="src">{{ i.source || i.created_at.slice(0, 10) }}</text>
          </view>
          <text class="del" @tap="delItem(i)">删除</text>
        </view>
        <text v-if="!s.items.length" class="muted">还没有细节</text>
      </view>
      <text v-if="!list.length" class="empty muted">{{ tab === 'people' ? '你提到过的人会出现在这里，比如领导、同事、家人。' : '每件找智囊商量过的事会形成一条事件线，记录进展。' }}</text>
    </view>

    <!-- 训练画像 -->
    <view v-if="tab === 'training'">
      <view v-if="m.training && m.training.sessions" class="card box">
        <text class="t-line">最近 {{ m.training.sessions }} 场训练</text>
        <view v-for="(v, k) in m.training.avg" :key="k" class="dim">
          <text class="dim-k">{{ k }}</text>
          <view class="bar"><view class="bar-in" :class="{ weak: k === m.training.weakest }" :style="{ width: v * 10 + '%' }" /></view>
          <text class="dim-v">{{ v }}</text>
        </view>
        <text v-if="m.training.weakest" class="t-line">最需要加强：{{ m.training.weakest }}</text>
        <text v-if="m.training.fillers.length" class="t-line">
          口头禅：{{ m.training.fillers.map((f) => `「${f.word}」每场约 ${f.per_session} 次`).join('，') }}
        </text>
        <text class="muted">训练画像直接从训练报告统计，智囊出主意和写报告时会参考。</text>
      </view>
      <text v-else class="empty muted">完成几次训练后，这里会显示你的长期强项和弱项。</text>
    </view>

    <view class="danger" @tap="clearAll">清空全部记忆</view>
    <text class="foot muted">记忆只有你自己能看到，管理员看不到内容。健康、收入、证件号等敏感信息不会被记录。条目多了智囊会定期整理合并；30 天没有进展的事会自动搁置，有新进展时自动恢复。</text>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onShow, onPullDownRefresh } from '@dcloudio/uni-app'
import { api } from '../../utils/api'

const m = ref({ paused: false, profile: [], people: [], cases: [], training: {} })
const tab = ref('profile')
const tabs = computed(() => [
  { k: 'profile', n: `我的档案 ${m.value.profile.length || ''}` },
  { k: 'people', n: `人物卡 ${m.value.people.length || ''}` },
  { k: 'cases', n: `事件线 ${m.value.cases.length || ''}` },
  { k: 'training', n: '训练画像' }
])
const list = computed(() => (tab.value === 'people' ? m.value.people : m.value.cases))
const statusText = { open: '进行中', done: '已完成', dormant: '搁置' }

async function load() {
  m.value = await api.memory()
}

async function togglePause(e) {
  const paused = !e.detail.value
  await api.memoryPause(paused)
  m.value.paused = paused
}

function prompt(title, value) {
  return new Promise((resolve) => {
    uni.showModal({ title, editable: true, content: value || '', success: (r) => resolve(r.confirm ? (r.content || '').trim() : null) })
  })
}

async function editItem(i) {
  const t = await prompt('修改这条记忆', i.text)
  if (t) {
    await api.memoryUpdateItem(i.id, { text: t })
    load()
  }
}

function delItem(i) {
  uni.showModal({ title: '删除这条记忆？', content: i.text, success: async (r) => {
    if (r.confirm) {
      await api.memoryDeleteItem(i.id)
      load()
    }
  } })
}

async function addProfile() {
  const t = await prompt('写一条关于你自己的信息（如职业、角色、沟通偏好）')
  if (t) {
    await api.memoryAddProfile(t)
    load()
  }
}

function subjectMenu(s) {
  const isCase = tab.value === 'cases'
  const actions = isCase
    ? ['改名称', '标记为已完成', '标记为进行中', '整理（合并重复、去掉过时的）', '删除整条事件线']
    : ['改名字', '编辑别名', '合并到另一张卡', '整理（合并重复、去掉过时的）', '删除整张卡']
  uni.showActionSheet({ itemList: actions, success: async ({ tapIndex }) => {
    const a = actions[tapIndex]
    if (a.startsWith('改名')) {
      const t = await prompt('新的名称', s.name)
      if (t) await api.memoryUpdateSubject(s.id, { name: t })
    } else if (a === '编辑别名') {
      const t = await prompt('别名，用逗号分开', s.aliases.join('，'))
      if (t !== null) await api.memoryUpdateSubject(s.id, { aliases: t.split(/[,，、\s]+/).filter(Boolean) })
    } else if (a === '标记为已完成') {
      await api.memoryUpdateSubject(s.id, { status: 'done' })
    } else if (a === '标记为进行中') {
      await api.memoryUpdateSubject(s.id, { status: 'open' })
    } else if (a.startsWith('整理')) {
      uni.showLoading({ title: '整理中', mask: true })
      try {
        const r = await api.memoryCompact(s.id)
        uni.hideLoading()
        uni.showToast({ title: r.changed ? `已整理：${r.before} 条 → ${r.after} 条` : '条目不多，不用整理', icon: 'none' })
      } catch (e) {
        uni.hideLoading()
      }
    } else if (a === '合并到另一张卡') {
      const others = m.value.people.filter((p) => p.id !== s.id)
      if (!others.length) return uni.showToast({ title: '没有其他人物卡', icon: 'none' })
      uni.showActionSheet({ itemList: others.map((p) => p.name).slice(0, 6), success: async (r) => {
        await api.memoryMergeSubject(s.id, others[r.tapIndex].id)
        load()
      } })
      return
    } else if (a.startsWith('删除')) {
      const ok = await new Promise((res) => uni.showModal({ title: `删除「${s.name}」？`, content: '卡片上的所有记录都会删除', success: (r) => res(r.confirm) }))
      if (ok) await api.memoryDeleteSubject(s.id)
    }
    load()
  } })
}

function clearAll() {
  uni.showModal({ title: '清空全部记忆？', content: '档案、人物卡、事件线都会删除，无法恢复。', confirmColor: '#E5564B', success: async (r) => {
    if (r.confirm) {
      await api.memoryClear()
      load()
    }
  } })
}

onShow(() => load().catch(() => {}))
onPullDownRefresh(async () => {
  try { await load() } finally { uni.stopPullDownRefresh() }
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 28rpx 32rpx 80rpx; box-sizing: border-box; }
.switch-card { display: flex; align-items: center; padding: 30rpx 32rpx; gap: 20rpx; }
.sw-text { flex: 1; display: flex; flex-direction: column; gap: 6rpx; }
.sw-title { font-size: 31rpx; font-weight: 700; }
.tabs { display: flex; gap: 12rpx; margin: 28rpx 0 20rpx; }
.tab { flex: 1; text-align: center; font-size: 25rpx; padding: 14rpx 0; border-radius: 12rpx; background: #fff; color: $tt-text-2; }
.tab.on { background: $tt-primary; color: #fff; }
.box { padding: 24rpx 30rpx; margin-bottom: 20rpx; display: flex; flex-direction: column; }
.item { display: flex; align-items: flex-start; gap: 16rpx; padding: 16rpx 0; border-bottom: 1rpx solid #F0F2F1; }
.item:last-of-type { border-bottom: none; }
.item-body { flex: 1; display: flex; flex-direction: column; gap: 4rpx; }
.item-text { font-size: 28rpx; line-height: 1.6; }
.src { font-size: 21rpx; color: $tt-text-3; }
.del { font-size: 24rpx; color: $tt-text-3; padding: 6rpx 0 6rpx 12rpx; }
.add { margin-top: 18rpx; font-size: 26rpx; color: $tt-primary; }
.empty { display: block; padding: 40rpx 12rpx; text-align: center; line-height: 1.7; }
.s-head { display: flex; align-items: center; gap: 14rpx; margin-bottom: 6rpx; }
.s-name { font-size: 31rpx; font-weight: 700; flex: 1; }
.s-status { font-size: 21rpx; padding: 2rpx 12rpx; border-radius: 6rpx; background: $tt-tag-bg; color: $tt-primary; }
.s-status.done, .s-status.dormant { background: $tt-bg; color: $tt-text-3; }
.s-op { font-size: 24rpx; color: $tt-primary; }
.s-summary { font-size: 25rpx; color: $tt-text-2; margin: 6rpx 0; }
.t-line { font-size: 27rpx; line-height: 1.7; margin: 8rpx 0; }
.dim { display: flex; align-items: center; gap: 16rpx; margin: 10rpx 0; }
.dim-k { width: 120rpx; font-size: 24rpx; color: $tt-text-2; }
.bar { flex: 1; height: 16rpx; border-radius: 8rpx; background: $tt-bg; overflow: hidden; }
.bar-in { height: 100%; background: $tt-primary; border-radius: 8rpx; }
.bar-in.weak { background: #E8A13A; }
.dim-v { width: 50rpx; text-align: right; font-size: 25rpx; font-weight: 600; }
.danger { margin-top: 40rpx; text-align: center; font-size: 27rpx; color: #E5564B; padding: 22rpx; background: #fff; border-radius: 16rpx; }
.foot { display: block; text-align: center; margin-top: 20rpx; line-height: 1.6; }
</style>
