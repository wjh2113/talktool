<template>
  <view class="page">
    <view class="top">
      <view class="search">
        <text class="search-ico">⌕</text>
        <input v-model="q" class="search-input" placeholder="搜谋略：如 知己知彼、让步、持久战" confirm-type="search"
               @confirm="load" @input="onInput" />
        <text v-if="q" class="clear" @tap="clearQ">✕</text>
      </view>
      <scroll-view class="chips" scroll-x :show-scrollbar="false">
        <view class="chip" :class="{ on: !school }" @tap="pickSchool('')">全部</view>
        <view v-for="s in schools" :key="s.code" class="chip" :class="{ on: school === s.code }" @tap="pickSchool(s.code)">
          {{ s.name }} {{ s.count }}
        </view>
      </scroll-view>
      <scroll-view class="chips small" scroll-x :show-scrollbar="false">
        <view class="chip" :class="{ on: !domain }" @tap="pickDomain('')">全部领域</view>
        <view v-for="d in domains" :key="d" class="chip" :class="{ on: domain === d }" @tap="pickDomain(d)">{{ d }}</view>
      </scroll-view>
    </view>

    <view v-if="curSchool" class="intro muted">{{ curSchool.intro }}</view>
    <view class="list">
      <view v-for="s in items" :key="s.id" class="card item" @tap="open(s)">
        <view class="item-head">
          <text class="name">{{ s.name }}</text>
          <text v-if="s.caution" class="caution">慎用</text>
          <text class="tag">{{ s.sub || s.school_name }}</text>
        </view>
        <text class="plain">{{ s.plain }}</text>
        <view class="domains">
          <text v-for="d in s.domains" :key="d" class="dm">{{ d }}</text>
        </view>
      </view>
      <view v-if="loading" class="state muted">加载中…</view>
      <view v-else-if="!items.length" class="state muted">没有找到相关谋略，换个关键词试试</view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'

const q = ref('')
const school = ref('')
const domain = ref('')
const schools = ref([])
const domains = ref([])
const items = ref([])
const loading = ref(false)
let timer = null

const curSchool = computed(() => schools.value.find((s) => s.code === school.value))

async function load() {
  loading.value = true
  try {
    const r = await api.strategies(school.value, domain.value, q.value.trim())
    items.value = r.items
    if (!schools.value.length) schools.value = r.schools
    domains.value = r.domains
  } finally {
    loading.value = false
  }
}

function onInput() {
  clearTimeout(timer)
  timer = setTimeout(load, 350)
}

function clearQ() {
  q.value = ''
  load()
}

function pickSchool(c) {
  school.value = c
  load()
}

function pickDomain(d) {
  domain.value = d
  load()
}

const open = (s) => uni.navigateTo({ url: `/pages/strategy/strategy?code=${s.code}` })

onLoad((opt) => {
  if (opt && opt.school) school.value = opt.school
  load()
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; }
.top { position: sticky; top: 0; z-index: 5; background: #fff; padding: 20rpx 0 16rpx; }
.search { display: flex; align-items: center; margin: 0 32rpx; padding: 0 24rpx; height: 72rpx; border-radius: 36rpx; background: $tt-bg; }
.search-ico { color: $tt-text-3; font-size: 34rpx; margin-right: 12rpx; }
.search-input { flex: 1; font-size: 28rpx; }
.clear { color: $tt-text-3; font-size: 26rpx; padding: 10rpx; }
.chips { white-space: nowrap; margin-top: 18rpx; padding-left: 32rpx; }
.chip { display: inline-block; margin-right: 16rpx; padding: 10rpx 24rpx; border-radius: 30rpx; background: $tt-bg; color: $tt-text-2; font-size: 26rpx; }
.chip.on { background: $tt-primary; color: #fff; }
.chips.small .chip { font-size: 23rpx; padding: 6rpx 20rpx; }
.chips.small .chip.on { background: $tt-tag-bg; color: $tt-primary; }
.intro { padding: 20rpx 36rpx 0; display: block; }
.list { padding: 20rpx 32rpx 60rpx; }
.item { padding: 30rpx 34rpx; margin-bottom: 20rpx; display: flex; flex-direction: column; }
.item-head { display: flex; align-items: center; gap: 12rpx; }
.name { font-size: 31rpx; font-weight: 700; flex: 1; }
.caution { font-size: 20rpx; color: #C0392B; border: 1rpx solid #E8A39B; padding: 0 10rpx; border-radius: 6rpx; }
.tag { background: $tt-tag-bg; color: $tt-primary; font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 8rpx; flex-shrink: 0; }
.plain { color: $tt-text-2; font-size: 26rpx; line-height: 1.7; margin-top: 12rpx; }
.domains { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }
.dm { font-size: 21rpx; color: $tt-text-3; background: $tt-bg; padding: 2rpx 12rpx; border-radius: 6rpx; }
.state { text-align: center; padding: 80rpx 0; }
</style>
