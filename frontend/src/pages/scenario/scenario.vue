<template>
  <view v-if="data" class="page">
    <view class="head">
      <text class="cat">{{ data.category_name }}</text>
      <text class="title">{{ data.title }}</text>
      <text class="sub">{{ data.subtitle }}</text>
    </view>

    <view class="list">
      <view class="list-head">
        <text class="list-title">场景列表</text>
        <text class="muted">共 {{ data.drills.length }} 个场景</text>
      </view>

      <view v-for="d in data.drills" :key="d.id" class="card drill" @tap="open(d)">
        <image v-if="d.cover_image" class="cover" :src="d.cover_image" mode="aspectFill" />
        <view v-else class="cover cover-ph" :style="coverStyle(data.category_name)">
          <text class="cover-txt">{{ data.title.slice(0, 2) }}</text>
        </view>
        <view class="info">
          <text class="d-title ellipsis-2">{{ d.title }}</text>
          <text class="d-desc ellipsis-2">{{ d.description }}</text>
          <view class="tags">
            <text class="tag" :class="pressureClass(d.pressure_level)">{{ d.pressure_level }}</text>
            <text class="tag tag-gray">约 {{ d.duration_min }} 分钟</text>
          </view>
        </view>
      </view>

      <view class="end muted">已加载全部场景</view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { coverStyle } from '../../utils/format'

const data = ref(null)

function pressureClass(p) {
  return p === '高压' ? 'tag-high' : p === '中压' ? 'tag-mid' : ''
}
function open(d) {
  uni.navigateTo({ url: `/pages/drill/drill?id=${d.id}` })
}

onLoad(async (q) => {
  data.value = await api.scenario(q.id)
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; }
.head {
  background: #fff;
  padding: 40rpx 40rpx 48rpx;
  display: flex;
  flex-direction: column;
  border-bottom: 1rpx solid #EEF1F5;
}
.cat { color: $tt-primary; font-size: 26rpx; margin-bottom: 16rpx; }
.title { font-size: 52rpx; font-weight: 800; margin-bottom: 20rpx; }
.sub { font-size: 28rpx; color: $tt-text-2; }
.list { padding: 0 32rpx 60rpx; }
.list-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 44rpx 0 28rpx;
}
.list-title { font-size: 34rpx; font-weight: 700; }
.drill { display: flex; padding: 32rpx; margin-bottom: 24rpx; }
.cover {
  width: 132rpx;
  height: 132rpx;
  border-radius: 16rpx;
  flex-shrink: 0;
  margin-right: 28rpx;
}
.cover-ph { display: flex; align-items: center; justify-content: center; }
.cover-txt { color: rgba(255, 255, 255, 0.95); font-size: 34rpx; font-weight: 700; letter-spacing: 2rpx; }
.info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.d-title { font-size: 31rpx; font-weight: 700; line-height: 1.5; margin-bottom: 10rpx; }
.d-desc { font-size: 26rpx; color: $tt-text-2; line-height: 1.6; margin-bottom: 18rpx; }
.tags { display: flex; gap: 14rpx; }
.end { text-align: center; padding: 30rpx 0; font-size: 26rpx; }
</style>
