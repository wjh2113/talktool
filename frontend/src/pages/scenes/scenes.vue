<template>
  <view class="wrap">
    <!-- 左侧分类 -->
    <scroll-view class="side" scroll-y>
      <view
        v-for="(c, i) in cats"
        :key="c.id"
        class="side-item"
        :class="{ active: i === activeIdx }"
        @tap="pick(i)"
      >
        <view v-if="i === activeIdx" class="side-bar" />
        <text>{{ c.name }}</text>
      </view>
    </scroll-view>

    <!-- 右侧内容：所有分类连续排列，滚动与左侧联动 -->
    <scroll-view
      class="main"
      scroll-y
      :scroll-into-view="intoView"
      scroll-with-animation
      @scroll="onScroll"
    >
      <view v-for="c in cats" :id="'sec-' + c.id" :key="c.id" class="section">
        <view class="sec-head">
          <text class="sec-title">{{ c.name }}</text>
          <text class="muted">共 {{ c.scenarios.length }} 个分类</text>
        </view>
        <view
          v-for="s in c.scenarios"
          :key="s.id"
          class="card scene-card"
          @tap="openScenario(s)"
        >
          <view class="scene-body">
            <text class="scene-title">{{ s.title }}</text>
            <text class="scene-sub">{{ s.subtitle }}</text>
            <text class="muted">{{ s.drill_count }} 个场景</text>
          </view>
          <text class="chevron">›</text>
        </view>
      </view>
      <view class="bottom-space" />
    </scroll-view>

    <view v-if="loading" class="state muted">加载中…</view>
    <view v-else-if="error" class="state" @tap="load">
      <text class="muted">加载失败，点击重试</text>
    </view>
  </view>
</template>

<script setup>
import { ref, getCurrentInstance, nextTick } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'

const cats = ref([])
const activeIdx = ref(0)
const intoView = ref('')
const loading = ref(true)
const error = ref(false)
let tops = []
let lockUntil = 0
const inst = getCurrentInstance()

async function load() {
  loading.value = true
  error.value = false
  try {
    cats.value = await api.categories()
    await nextTick()
    setTimeout(measure, 300)
  } catch (e) {
    error.value = true
  } finally {
    loading.value = false
  }
}

function measure() {
  uni.createSelectorQuery()
    .in(inst.proxy)
    .selectAll('.section')
    .boundingClientRect((rects) => {
      if (!rects || !rects.length) return
      const base = rects[0].top
      tops = rects.map((r) => r.top - base)
    })
    .exec()
}

function pick(i) {
  activeIdx.value = i
  lockUntil = Date.now() + 600 // 点击滚动期间不反向联动
  intoView.value = ''
  nextTick(() => (intoView.value = 'sec-' + cats.value[i].id))
}

function onScroll(e) {
  if (Date.now() < lockUntil || !tops.length) return
  const y = e.detail.scrollTop + 40
  let idx = 0
  for (let i = 0; i < tops.length; i++) if (y >= tops[i]) idx = i
  activeIdx.value = idx
}

function openScenario(s) {
  uni.navigateTo({ url: `/pages/scenario/scenario?id=${s.id}` })
}

onLoad(load)
</script>

<style lang="scss" scoped>
.wrap {
  display: flex;
  height: calc(100vh - var(--window-top) - var(--window-bottom));
  background: $tt-bg;
}
.side {
  width: 210rpx;
  height: 100%;
  background: #fff;
  flex-shrink: 0;
}
.side-item {
  position: relative;
  height: 162rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32rpx;
  color: #4A4F57;
  &.active {
    background: $tt-tag-bg;
    color: $tt-primary;
    font-weight: 600;
  }
}
.side-bar {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 8rpx;
  height: 72rpx;
  border-radius: 0 8rpx 8rpx 0;
  background: $tt-primary;
}
.main {
  flex: 1;
  height: 100%;
  padding: 0 24rpx;
  box-sizing: border-box;
}
.section { padding-top: 28rpx; }
.sec-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8rpx 0 24rpx;
}
.sec-title { font-size: 32rpx; font-weight: 600; }
.scene-card {
  display: flex;
  align-items: center;
  padding: 36rpx 28rpx 32rpx 32rpx;
  margin-bottom: 24rpx;
}
.scene-body { flex: 1; display: flex; flex-direction: column; }
.scene-title { font-size: 34rpx; font-weight: 700; margin-bottom: 18rpx; }
.scene-sub { font-size: 27rpx; color: $tt-text-2; margin-bottom: 18rpx; line-height: 1.5; }
.bottom-space { height: 60rpx; }
.state {
  position: fixed;
  left: 210rpx;
  right: 0;
  top: 40%;
  text-align: center;
}
</style>
