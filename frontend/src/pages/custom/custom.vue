<template>
  <view class="page">
    <view class="card form">
      <text class="title">描述你要面对的真实情况</text>
      <text class="sub">说清楚：你是谁、对方是谁、要谈什么、你担心什么。AI 会把它变成一个可以语音对练的场景。</text>
      <textarea
        v-model="desc"
        class="input"
        :maxlength="600"
        placeholder="例如：明天要跟房东谈退押金，他说墙上有划痕要扣一千，我觉得是正常使用痕迹"
        :auto-height="false"
      />
      <text class="count">{{ desc.length }}/600</text>

      <view class="examples">
        <text v-for="e in examples" :key="e" class="example" @tap="desc = e">{{ e }}</text>
      </view>

      <text class="label">对方的态度</text>
      <view class="seg">
        <view v-for="p in pressures" :key="p.key" class="seg-item" :class="{ on: pressure === p.key }" @tap="pressure = p.key">
          <text class="seg-k">{{ p.key }}</text>
          <text class="seg-d">{{ p.desc }}</text>
        </view>
      </view>

      <view class="btn-primary gen" :class="{ disabled: generating }" @tap="generate">
        {{ generating ? 'AI 正在设计场景…' : '生成我的训练场景' }}
      </view>
      <text v-if="generating" class="muted wait">通常需要 10–30 秒</text>
    </view>

    <view v-if="list.length" class="mine-head">
      <text class="sec-title">我的场景</text>
      <text class="muted">共 {{ list.length }} 个</text>
    </view>
    <view v-for="d in list" :key="d.id" class="card item" @tap="open(d)">
      <view class="item-top">
        <text class="item-title ellipsis-2">{{ d.title }}</text>
        <text class="del" @tap.stop="remove(d)">删除</text>
      </view>
      <text class="item-desc ellipsis-2">{{ d.description }}</text>
      <view class="item-tags">
        <text class="tag" :class="pressureClass(d.pressure_level)">{{ d.pressure_level }}</text>
        <text class="tag tag-gray">约 {{ d.duration_min }} 分钟</text>
        <text class="muted stat">{{ d.times ? `练过 ${d.times} 次` : '还没练过' }}{{ d.best != null ? ` · 最高 ${d.best} 分` : '' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api } from '../../utils/api'

const examples = [
  '明天要跟房东谈退押金，他说墙上有划痕要扣一千',
  '想跟领导提调岗到产品部，但他很看重我现在的工作',
  '朋友借了我五千块一年没还，想开口要回来又不伤感情',
  '第一次见女朋友的父母，她爸爸比较严肃'
]
const pressures = [
  { key: '低压', desc: '友善配合' },
  { key: '中压', desc: '会质疑追问' },
  { key: '高压', desc: '强硬刁难' }
]
const desc = ref('')
const pressure = ref('中压')
const generating = ref(false)
const list = ref([])

function pressureClass(p) {
  return p === '高压' ? 'tag-high' : p === '中压' ? 'tag-mid' : ''
}

async function load() {
  try {
    list.value = await api.customDrills()
  } catch (e) {}
}

async function generate() {
  if (generating.value) return
  if (desc.value.trim().length < 6) {
    uni.showToast({ title: '请多描述一点情况', icon: 'none' })
    return
  }
  generating.value = true
  try {
    const d = await api.createCustom(desc.value.trim(), pressure.value)
    desc.value = ''
    uni.navigateTo({ url: `/pages/drill/drill?id=${d.id}` })
  } catch (e) {
  } finally {
    generating.value = false
  }
}

function open(d) {
  uni.navigateTo({ url: `/pages/drill/drill?id=${d.id}` })
}

function remove(d) {
  uni.showModal({
    title: '删除这个场景？',
    content: '已有的训练记录会保留。',
    success: async (r) => {
      if (!r.confirm) return
      await api.deleteCustom(d.id)
      list.value = list.value.filter((x) => x.id !== d.id)
    }
  })
}

onShow(load)
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx 32rpx 60rpx; box-sizing: border-box; }
.form { padding: 36rpx; display: flex; flex-direction: column; margin-bottom: 36rpx; }
.title { font-size: 34rpx; font-weight: 700; margin-bottom: 12rpx; }
.sub { font-size: 26rpx; color: $tt-text-2; line-height: 1.6; margin-bottom: 24rpx; }
.input {
  width: 100%; height: 240rpx; box-sizing: border-box; padding: 22rpx 24rpx;
  background: #F7F9FC; border: 1rpx solid #E3E7ED; border-radius: 16rpx; font-size: 28rpx; line-height: 1.6;
}
.count { align-self: flex-end; font-size: 22rpx; color: $tt-text-3; margin-top: 8rpx; }
.examples { display: flex; flex-wrap: wrap; gap: 14rpx; margin: 16rpx 0 32rpx; }
.example { font-size: 24rpx; color: $tt-primary; background: $tt-tag-bg; padding: 10rpx 18rpx; border-radius: 12rpx; line-height: 1.5; }
.label { font-size: 28rpx; font-weight: 600; margin-bottom: 16rpx; }
.seg { display: flex; gap: 16rpx; margin-bottom: 40rpx; }
.seg-item {
  flex: 1; padding: 18rpx 0; border-radius: 14rpx; border: 1rpx solid #E3E7ED; background: #fff;
  display: flex; flex-direction: column; align-items: center;
  &.on { border-color: $tt-primary; background: $tt-tag-bg; }
}
.seg-k { font-size: 30rpx; font-weight: 700; color: $tt-text; }
.seg-item.on .seg-k { color: $tt-primary; }
.seg-d { font-size: 22rpx; color: $tt-text-3; margin-top: 4rpx; }
.gen.disabled { opacity: 0.6; }
.wait { text-align: center; margin-top: 14rpx; }
.mine-head { display: flex; justify-content: space-between; align-items: center; padding: 0 4rpx 22rpx; }
.sec-title { font-size: 32rpx; font-weight: 700; }
.item { padding: 32rpx; margin-bottom: 22rpx; }
.item-top { display: flex; align-items: flex-start; }
.item-title { flex: 1; font-size: 30rpx; font-weight: 700; line-height: 1.5; }
.del { font-size: 24rpx; color: $tt-text-3; margin-left: 20rpx; padding: 4rpx 0 4rpx 10rpx; }
.item-desc { font-size: 25rpx; color: $tt-text-2; line-height: 1.6; margin: 10rpx 0 18rpx; }
.item-tags { display: flex; align-items: center; gap: 14rpx; flex-wrap: wrap; }
.stat { margin-left: 6rpx; }
</style>
