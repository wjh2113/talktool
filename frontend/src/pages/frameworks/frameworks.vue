<template>
  <view class="page">
    <view class="top">
      <view class="search">
        <text class="search-ico">⌕</text>
        <input
          v-model="q"
          class="search-input"
          placeholder="搜框架：如 汇报、拒绝、开场"
          confirm-type="search"
          @confirm="load"
          @input="onInput"
        />
        <text v-if="q" class="clear" @tap="clearQ">✕</text>
      </view>
      <scroll-view class="chips" scroll-x :show-scrollbar="false">
        <view class="chip" :class="{ on: !cat }" @tap="pickCat('')">全部 {{ allCount }}</view>
        <view
          v-for="c in cats"
          :key="c.name"
          class="chip"
          :class="{ on: cat === c.name }"
          @tap="pickCat(c.name)"
        >{{ c.name }} {{ c.count }}</view>
      </scroll-view>
    </view>

    <view class="list">
      <view v-for="f in items" :key="f.id" class="card item" @tap="open(f)">
        <view class="item-head">
          <text class="name">{{ f.name }}</text>
          <text class="tag">{{ f.category }}</text>
        </view>
        <text class="summary">{{ f.summary }}</text>
        <view class="steps">
          <text v-for="(s, j) in f.steps" :key="j" class="step">{{ j + 1 }} {{ s.name }}</text>
        </view>
        <text v-if="f.drill_count" class="muted used">关联 {{ f.drill_count }} 个训练场景</text>
      </view>
      <view v-if="loading" class="state muted">加载中…</view>
      <view v-else-if="!items.length" class="state muted">没有找到相关框架，换个关键词试试</view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'

const q = ref('')
const cat = ref('')
const cats = ref([])
const items = ref([])
const allCount = ref(0)
const loading = ref(false)
let timer = null

async function load() {
  loading.value = true
  try {
    const res = await api.frameworks(cat.value, q.value.trim())
    items.value = res.items
    cats.value = res.categories
    if (!cat.value && !q.value.trim()) allCount.value = res.total
    else if (!allCount.value) allCount.value = res.categories.reduce((n, c) => n + c.count, 0)
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

function pickCat(name) {
  cat.value = name
  load()
}

function open(f) {
  uni.navigateTo({ url: `/pages/framework/framework?key=${f.code}` })
}

onLoad((opt) => {
  if (opt && opt.category) cat.value = decodeURIComponent(opt.category)
  load()
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; }
.top { position: sticky; top: 0; z-index: 5; background: #fff; padding: 20rpx 0 16rpx; }
.search {
  display: flex; align-items: center; margin: 0 32rpx; padding: 0 24rpx;
  height: 72rpx; border-radius: 36rpx; background: $tt-bg;
}
.search-ico { color: $tt-text-3; font-size: 34rpx; margin-right: 12rpx; }
.search-input { flex: 1; font-size: 28rpx; }
.clear { color: $tt-text-3; font-size: 26rpx; padding: 10rpx; }
.chips { white-space: nowrap; margin-top: 20rpx; padding-left: 32rpx; }
.chip {
  display: inline-block; margin-right: 16rpx; padding: 10rpx 24rpx; border-radius: 30rpx;
  background: $tt-bg; color: $tt-text-2; font-size: 26rpx;
}
.chip.on { background: $tt-primary; color: #fff; }
.list { padding: 24rpx 32rpx 60rpx; }
.item { padding: 32rpx 36rpx; margin-bottom: 20rpx; display: flex; flex-direction: column; }
.item-head { display: flex; align-items: center; justify-content: space-between; }
.name { font-size: 32rpx; font-weight: 700; flex: 1; }
.tag { background: $tt-tag-bg; color: $tt-primary; font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 8rpx; flex-shrink: 0; }
.summary { color: $tt-text-2; font-size: 27rpx; line-height: 1.7; margin-top: 12rpx; }
.steps { display: flex; flex-wrap: wrap; gap: 12rpx; margin-top: 18rpx; }
.step { background: #F7F9FC; color: #333; font-size: 23rpx; padding: 6rpx 16rpx; border-radius: 8rpx; }
.used { margin-top: 16rpx; }
.state { text-align: center; padding: 80rpx 0; }
</style>
