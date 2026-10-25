<template>
  <view v-if="f" class="page">
    <view class="head">
      <text class="cat">{{ f.category }}</text>
      <text class="title">{{ f.name }}</text>
      <text class="summary">{{ f.summary }}</text>
    </view>

    <text class="block-title">框架步骤</text>
    <view class="card box">
      <view v-for="(s, i) in f.steps" :key="i" class="step">
        <view class="step-no">{{ i + 1 }}</view>
        <view class="step-body">
          <text class="step-name">{{ s.name }}</text>
          <text class="step-desc">{{ s.desc }}</text>
        </view>
      </view>
    </view>

    <template v-if="f.when_to_use">
      <text class="block-title">适用场合</text>
      <view class="card box"><text class="txt">{{ f.when_to_use }}</text></view>
    </template>

    <text class="block-title">示例</text>
    <view class="card box example">
      <text class="txt">{{ f.example }}</text>
      <ReadAloud :text="exampleText" />
      <text class="act" @tap="save">{{ saved ? '✓ 已收藏到练习本' : '＋ 收藏到练习本' }}</text>
    </view>

    <template v-if="f.pitfalls && f.pitfalls.length">
      <text class="block-title">常见误区（{{ f.pitfalls.length }}）</text>
      <view class="card box">
        <PitfallList :items="f.pitfalls" :source="f.pitfall_source" />
      </view>
    </template>

    <template v-if="f.tips && f.tips.length">
      <text class="block-title">使用技巧</text>
      <view class="card box">
        <view v-for="(t, i) in f.tips" :key="i" class="line">
          <text class="ok">✓</text><text class="txt">{{ t }}</text>
        </view>
      </view>
    </template>

    <template v-if="f.detail">
      <text class="block-title">深入了解</text>
      <view class="card box"><text class="txt">{{ f.detail }}</text></view>
    </template>

    <template v-if="f.strategies && f.strategies.length">
      <text class="block-title">配合这些谋略</text>
      <view class="card box strat-box">
        <text v-for="st in f.strategies" :key="st.code" class="strat-chip" @tap="openStrategy(st.code)">{{ st.school_name }} · {{ st.name }}</text>
      </view>
    </template>

    <template v-if="f.drills && f.drills.length">
      <text class="block-title">去这些场景里练（{{ f.drills.length }}）</text>
      <view v-for="d in f.drills" :key="d.id" class="card drill" @tap="openDrill(d)">
        <view class="drill-head">
          <text class="drill-title">{{ d.title }}</text>
          <text class="chevron">›</text>
        </view>
        <text class="muted">{{ d.category_name }} · {{ d.scenario_title }} · {{ d.pressure_level }}</text>
        <text v-if="d.example" class="drill-ex">“{{ d.example }}”</text>
      </view>
    </template>
    <view class="bottom" />
  </view>
  <view v-else-if="error" class="state muted" @tap="load">加载失败，点击重试</view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import ReadAloud from '../../components/ReadAloud/ReadAloud.vue'
import PitfallList from '../../components/PitfallList/PitfallList.vue'

const f = ref(null)
const error = ref(false)
const saved = ref(false)
let key = ''
// 示范朗读/跟读的文本上限 500 字
const exampleText = computed(() => (f.value ? f.value.example.slice(0, 480).trim() : ''))

async function load() {
  error.value = false
  try {
    f.value = await api.framework(key)
    uni.setNavigationBarTitle({ title: f.value.name })
  } catch (e) {
    error.value = true
  }
}

async function save() {
  if (saved.value) return
  await api.addNote({ kind: 'script', text: f.value.example, source_text: `表达框架：${f.value.name}` })
  saved.value = true
  uni.showToast({ title: '已收藏到练习本', icon: 'none' })
}

const openStrategy = (code) => uni.navigateTo({ url: `/pages/strategy/strategy?code=${code}` })

function openDrill(d) {
  uni.navigateTo({ url: `/pages/drill/drill?id=${d.id}` })
}

onLoad((q) => {
  key = q.key
  load()
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; }
.head {
  background: linear-gradient(135deg, #1AA897 0%, #0B6B5F 100%);
  padding: 44rpx 40rpx 52rpx; display: flex; flex-direction: column;
}
.cat { color: rgba(255, 255, 255, 0.8); font-size: 24rpx; }
.title { color: #fff; font-size: 44rpx; font-weight: 800; margin-top: 10rpx; }
.summary { color: rgba(255, 255, 255, 0.92); font-size: 28rpx; line-height: 1.7; margin-top: 16rpx; }
.block-title { display: block; font-size: 32rpx; font-weight: 700; margin: 40rpx 32rpx 20rpx; }
.box { margin: 0 32rpx; padding: 32rpx 36rpx; }
.txt { font-size: 28rpx; line-height: 1.85; color: #333; white-space: pre-wrap; flex: 1; }
.step { display: flex; align-items: flex-start; padding: 14rpx 0; }
.step-no {
  width: 44rpx; height: 44rpx; line-height: 44rpx; text-align: center; border-radius: 50%;
  background: $tt-primary; color: #fff; font-size: 24rpx; margin-right: 20rpx; flex-shrink: 0;
}
.step-body { flex: 1; display: flex; flex-direction: column; }
.step-name { font-size: 30rpx; font-weight: 700; }
.step-desc { font-size: 27rpx; color: $tt-text-2; line-height: 1.7; margin-top: 6rpx; }
.example { background: $tt-soft; display: flex; flex-direction: column; }
.act { color: $tt-primary; font-size: 26rpx; margin-top: 20rpx; }
.line { display: flex; align-items: flex-start; padding: 6rpx 0; }
.ok { color: #19BE6B; margin-right: 14rpx; font-size: 26rpx; line-height: 1.85; }
.drill { margin: 0 32rpx 20rpx; padding: 28rpx 36rpx; display: flex; flex-direction: column; }
.drill-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8rpx; }
.drill-title { font-size: 30rpx; font-weight: 600; flex: 1; }
.chevron { color: $tt-text-3; font-size: 36rpx; }
.drill-ex { font-size: 26rpx; color: $tt-text-2; line-height: 1.7; margin-top: 12rpx; }
.bottom { height: 60rpx; }
.state { text-align: center; padding: 160rpx 0; }
.strat-box { display: flex; flex-direction: row; flex-wrap: wrap; gap: 14rpx; }
.strat-chip { font-size: 24rpx; color: $tt-primary; background: $tt-tag-bg; padding: 8rpx 18rpx; border-radius: 20rpx; }
</style>
