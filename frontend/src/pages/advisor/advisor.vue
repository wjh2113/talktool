<template>
  <view class="page">
    <view class="ask card">
      <text class="ask-title">遇到什么事了？</text>
      <text class="ask-sub">把真实情况说给智囊团，帮你出主意：怎么做、怎么说，还能先演练一遍</text>
      <textarea
        v-model="text"
        class="ask-input"
        :maxlength="2000"
        auto-height
        placeholder="例如：新来的领导总在会上否定我的方案，我想争取下季度的项目负责人"
      />
      <view v-if="myAdvisors.length" class="seats">
        <text class="muted">请谁列席：</text>
        <text v-for="a in myAdvisors" :key="a.code" class="seat" :class="{ on: seats.includes(a.code) }" @tap="toggleSeat(a.code)">{{ a.name }}</text>
      </view>
      <view class="ask-bar">
        <VoiceInput @text="onVoice" />
        <text class="muted mem-hint">{{ memoryPaused ? '记忆已暂停' : '智囊会记得你说过的人和事' }}</text>
        <view class="btn-primary send" :class="{ off: !canSend }" @tap="send()">问智囊</view>
      </view>
    </view>

    <template v-if="due.length">
      <view class="sec-head">
        <text class="sec-title">该跟进了</text>
        <text class="muted">{{ due.length }} 件</text>
      </view>
      <view v-for="d in due" :key="d.consult_id" class="card due">
        <view @tap="openConsult(d.consult_id)">
          <text class="due-title">{{ d.title }}</text>
          <text class="due-reason">{{ d.reason }}</text>
        </view>
        <view class="due-btns">
          <text class="due-btn main" @tap="review(d)">回来复盘</text>
          <text class="due-btn" @tap="snooze(d)">过两天再提醒</text>
          <text class="due-btn" @tap="stopFollow(d)">不用提醒了</text>
        </view>
      </view>
    </template>

    <view v-if="ongoing.length" class="sec-head">
      <text class="sec-title">进行中的事</text>
    </view>
    <view v-for="c in ongoing" :key="c.id" class="card case" @tap="openConsult(c.consult_id)">
      <view class="case-head">
        <text class="case-name">{{ c.name }}</text>
        <text v-if="c.pending" class="case-badge">{{ c.pending }} 步待办</text>
      </view>
      <text v-if="c.next_action" class="case-next">下一步：{{ c.next_action }}</text>
      <text v-else class="muted">{{ c.summary || '回来说说进展，智囊帮你调整下一步' }}</text>
    </view>

    <view class="sec-head">
      <text class="sec-title">智囊团</text>
      <text class="muted">不确定找谁？直接在上面描述就行</text>
    </view>
    <view class="grid">
      <view v-for="c in councils" :key="c.code" class="card council" @tap="pickCouncil(c)">
        <view class="council-icon"><text>{{ c.icon }}</text></view>
        <text class="council-name">{{ c.name }}</text>
        <text class="council-desc">{{ c.description }}</text>
      </view>
    </view>

    <view class="duo">
      <view class="card mini" @tap="go('/pages/strategies/strategies')">
        <text class="mini-title">谋略库</text>
        <text class="mini-sub">毛选、孙子、三十六计、鬼谷子、谈判、投资……</text>
      </view>
      <view class="card mini" @tap="go('/pages/memory/memory')">
        <text class="mini-title">智囊记得的</text>
        <text class="mini-sub">你的档案、人物卡、事件线，可改可删</text>
      </view>
    </view>
    <view class="card mine-adv" @tap="go('/pages/my-advisors/my-advisors')">
      <view class="mine-body">
        <text class="mini-title">我的私人谋士{{ myAdvisors.length ? ' · ' + myAdvisors.length + ' 位' : '' }}</text>
        <text class="mini-sub">把信任的前辈、朋友、家人设成谋士，问计时请他们列席、参加圆桌会议</text>
      </view>
      <text class="chevron">›</text>
    </view>

    <template v-if="consults.length">
      <view class="sec-head">
        <text class="sec-title">最近问计</text>
      </view>
      <view v-for="c in consults" :key="c.id" class="card hist" @tap="openConsult(c.id)">
        <view class="hist-head">
          <text class="hist-title">{{ c.title }}</text>
          <text class="hist-status" :class="c.status">{{ c.status_text }}</text>
        </view>
        <text v-if="c.headline" class="hist-line">{{ c.headline }}</text>
        <text class="muted">{{ c.council_name }} · {{ c.updated_at.slice(5, 16) }}</text>
      </view>
    </template>

    <view v-if="pick" class="mask" @tap="pick = null">
      <view class="sheet" @tap.stop>
        <text class="sheet-title">{{ pick.icon }} {{ pick.name }}</text>
        <text class="sheet-sub">{{ pick.description }}</text>
        <view class="advisors">
          <view v-for="a in pick.advisor_list" :key="a.code" class="adv">
            <text class="adv-avatar">{{ a.avatar }}</text>
            <text class="adv-name">{{ a.name }}</text>
            <text class="adv-style">{{ a.style }}</text>
          </view>
        </view>
        <text class="sheet-label">可以这样问：</text>
        <view v-for="(e, i) in pick.examples" :key="i" class="example" @tap="useExample(e)">{{ e }}</view>
        <textarea v-model="pickText" class="ask-input sheet-input" auto-height :maxlength="2000"
                  :placeholder="`说说你的情况，直接交给${pick.name}`" />
        <view class="ask-bar">
          <VoiceInput @text="(t) => (pickText = (pickText ? pickText + '，' : '') + t)" />
          <view class="btn-primary send" :class="{ off: pickText.trim().length < 2 }" @tap="send(pick.code)">交给{{ pick.name }}</view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onShow, onPullDownRefresh } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import VoiceInput from '../../components/VoiceInput/VoiceInput.vue'

const text = ref('')
const councils = ref([])
const ongoing = ref([])
const consults = ref([])
const memoryPaused = ref(false)
const pick = ref(null)
const due = ref([])
const myAdvisors = ref([])
const seats = ref([])
const pickText = ref('')
const canSend = computed(() => text.value.trim().length >= 2)

async function load() {
  const r = await api.advisorHome()
  councils.value = r.councils
  ongoing.value = r.ongoing.filter((c) => c.consult_id)
  consults.value = r.consults
  memoryPaused.value = r.memory_paused
  due.value = r.due || []
  myAdvisors.value = r.my_advisors || []
  seats.value = seats.value.filter((c) => myAdvisors.value.some((a) => a.code === c))
  setBadge(due.value.length)
}

function setBadge(n) {
  // 底栏「智囊」角标：有几件事该跟进
  if (n) uni.setTabBarBadge({ index: 2, text: String(n), fail: () => {} })
  else uni.removeTabBarBadge({ index: 2, fail: () => {} })
}

function toggleSeat(code) {
  const i = seats.value.indexOf(code)
  if (i >= 0) seats.value.splice(i, 1)
  else if (seats.value.length < 2) seats.value.push(code)
  else uni.showToast({ title: '最多请 2 位', icon: 'none' })
}

function review(d) {
  uni.navigateTo({ url: `/pages/consult/consult?id=${d.consult_id}&review=1` })
}

async function snooze(d) {
  await api.snoozeConsult(d.consult_id, 2)
  uni.showToast({ title: '两天后再提醒你', icon: 'none' })
  load()
}

async function stopFollow(d) {
  await api.stopFollow(d.consult_id)
  load()
}

function onVoice(t) {
  text.value = text.value ? `${text.value}，${t}` : t
}

function send(council) {
  const t = (council ? pickText.value : text.value).trim()
  if (t.length < 2) return
  uni.setStorageSync('tt_pending_consult', { text: t, council: council || '', advisors: [...seats.value] })
  text.value = ''
  pickText.value = ''
  pick.value = null
  uni.navigateTo({ url: '/pages/consult/consult' })
}

function pickCouncil(c) {
  pick.value = c
  pickText.value = ''
}

function useExample(e) {
  pickText.value = e
}

function openConsult(id) {
  if (id) uni.navigateTo({ url: `/pages/consult/consult?id=${id}` })
}

const go = (url) => uni.navigateTo({ url })

onShow(() => load().catch(() => {}))
onPullDownRefresh(async () => {
  try { await load() } finally { uni.stopPullDownRefresh() }
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx 32rpx 60rpx; box-sizing: border-box; }
.ask { padding: 36rpx; display: flex; flex-direction: column; margin-bottom: 28rpx; }
.ask-title { font-size: 38rpx; font-weight: 800; }
.ask-sub { font-size: 25rpx; color: $tt-text-2; margin: 10rpx 0 24rpx; line-height: 1.6; }
.ask-input {
  width: 100%; min-height: 160rpx; box-sizing: border-box; padding: 20rpx 24rpx; border-radius: 16rpx;
  background: $tt-bg; font-size: 28rpx; line-height: 1.6;
}
.ask-bar { display: flex; align-items: center; margin-top: 20rpx; gap: 20rpx; }
.mem-hint { flex: 1; }
.send { width: 200rpx; height: 76rpx; line-height: 76rpx; font-size: 28rpx; flex-shrink: 0; }
.send.off { opacity: 0.45; }
.sec-head { display: flex; align-items: baseline; justify-content: space-between; padding: 20rpx 4rpx 20rpx; }
.sec-title { font-size: 32rpx; font-weight: 700; }
.case { padding: 28rpx 32rpx; margin-bottom: 20rpx; display: flex; flex-direction: column; border-left: 8rpx solid $tt-primary; }
.case-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8rpx; }
.case-name { font-size: 30rpx; font-weight: 700; flex: 1; }
.case-badge { font-size: 22rpx; color: $tt-primary; background: $tt-tag-bg; padding: 4rpx 14rpx; border-radius: 8rpx; }
.case-next { font-size: 26rpx; color: $tt-text-2; }
.grid { display: flex; flex-wrap: wrap; gap: 20rpx; }
.council { width: calc((100% - 40rpx) / 3); box-sizing: border-box; padding: 24rpx 20rpx; display: flex; flex-direction: column; align-items: center; }
.council-icon {
  width: 72rpx; height: 72rpx; border-radius: 50%; background: $tt-soft; color: $tt-primary;
  display: flex; align-items: center; justify-content: center; font-size: 32rpx; font-weight: 700; margin-bottom: 12rpx;
}
.council-name { font-size: 26rpx; font-weight: 700; text-align: center; }
.council-desc {
  font-size: 21rpx; color: $tt-text-3; text-align: center; margin-top: 6rpx; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.duo { display: flex; gap: 20rpx; margin: 28rpx 0 8rpx; }
.mini { flex: 1; padding: 28rpx; display: flex; flex-direction: column; }
.mini-title { font-size: 29rpx; font-weight: 700; margin-bottom: 8rpx; }
.mini-sub { font-size: 23rpx; color: $tt-text-2; line-height: 1.5; }
.hist { padding: 26rpx 32rpx; margin-bottom: 18rpx; display: flex; flex-direction: column; gap: 8rpx; }
.hist-head { display: flex; align-items: center; justify-content: space-between; }
.hist-title { font-size: 29rpx; font-weight: 600; flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.hist-status { font-size: 22rpx; color: $tt-text-3; flex-shrink: 0; margin-left: 12rpx; }
.hist-status.planned { color: $tt-primary; }
.hist-status.safety, .hist-status.failed { color: #E5564B; }
.hist-line { font-size: 26rpx; color: $tt-text-2; line-height: 1.6; }
.mask { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0, 0, 0, 0.45); z-index: 50; display: flex; align-items: flex-end; }
.sheet {
  width: 100%; max-height: 86vh; overflow-y: auto; background: #fff; border-radius: 32rpx 32rpx 0 0;
  padding: 40rpx 36rpx calc(40rpx + env(safe-area-inset-bottom)); box-sizing: border-box; display: flex; flex-direction: column;
}
.sheet-title { font-size: 36rpx; font-weight: 800; }
.sheet-sub { font-size: 26rpx; color: $tt-text-2; margin: 10rpx 0 24rpx; }
.advisors { display: flex; gap: 16rpx; margin-bottom: 24rpx; }
.adv { flex: 1; background: $tt-bg; border-radius: 16rpx; padding: 18rpx 12rpx; display: flex; flex-direction: column; align-items: center; }
.adv-avatar {
  width: 56rpx; height: 56rpx; line-height: 56rpx; text-align: center; border-radius: 50%;
  background: $tt-primary; color: #fff; font-size: 26rpx; font-weight: 700;
}
.adv-name { font-size: 25rpx; font-weight: 600; margin-top: 8rpx; }
.adv-style { font-size: 20rpx; color: $tt-text-3; margin-top: 4rpx; text-align: center; }
.sheet-label { font-size: 24rpx; color: $tt-text-3; margin-bottom: 12rpx; }
.example { font-size: 26rpx; color: $tt-primary; background: $tt-soft; border-radius: 12rpx; padding: 14rpx 20rpx; margin-bottom: 12rpx; }
.sheet-input { margin-top: 12rpx; }
.seats { display: flex; align-items: center; flex-wrap: wrap; gap: 12rpx; margin-top: 18rpx; }
.seat { font-size: 24rpx; padding: 6rpx 18rpx; border-radius: 20rpx; background: $tt-bg; color: $tt-text-2; }
.seat.on { background: #FFF1DC; color: #B7791F; }
.due { padding: 26rpx 30rpx; margin-bottom: 18rpx; border-left: 8rpx solid #E8A13A; display: flex; flex-direction: column; gap: 16rpx; }
.due > view:first-child { display: flex; flex-direction: column; gap: 6rpx; }
.due-title { font-size: 29rpx; font-weight: 700; }
.due-reason { font-size: 25rpx; color: $tt-text-2; line-height: 1.6; }
.due-btns { display: flex; gap: 14rpx; }
.due-btn { font-size: 23rpx; padding: 8rpx 18rpx; border-radius: 20rpx; background: $tt-bg; color: $tt-text-2; }
.due-btn.main { background: $tt-primary; color: #fff; }
.mine-adv { display: flex; align-items: center; padding: 28rpx; margin: 20rpx 0 8rpx; }
.mine-body { flex: 1; display: flex; flex-direction: column; }
.chevron { color: $tt-text-3; font-size: 36rpx; }
</style>
