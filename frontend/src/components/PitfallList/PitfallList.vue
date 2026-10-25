<template>
  <view class="pl">
    <view v-for="(p, i) in shown" :key="i" class="pl-item">
      <view class="pl-row">
        <text class="pl-x">✕</text>
        <text class="pl-bad">{{ p.bad }}</text>
      </view>
      <view v-if="p.fix" class="pl-row pl-fix-row">
        <text class="pl-ok">改</text>
        <text class="pl-fix">{{ p.fix }}</text>
      </view>
    </view>
    <view v-if="items.length > limit" class="pl-more" @tap="open = !open">
      {{ open ? '收起' : `展开全部 ${items.length} 条` }}
    </view>
    <text v-if="source" class="pl-src">出自：{{ source }}</text>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'

// 每条误区形如“错误做法 → 正确做法”，没有箭头的只显示错误做法
const props = defineProps({
  items: { type: Array, default: () => [] },
  limit: { type: Number, default: 5 },
  source: { type: String, default: '' }
})
const open = ref(false)
const parsed = computed(() =>
  props.items.map((s) => {
    const i = String(s).indexOf('→')
    return i < 0 ? { bad: s, fix: '' } : { bad: s.slice(0, i).trim(), fix: s.slice(i + 1).trim() }
  })
)
const shown = computed(() => (open.value ? parsed.value : parsed.value.slice(0, props.limit)))
</script>

<style lang="scss" scoped>
.pl-item { padding: 14rpx 0; border-bottom: 1rpx solid #F0F2F1; }
.pl-item:last-of-type { border-bottom: none; }
.pl-row { display: flex; align-items: flex-start; }
.pl-x { color: #E5564B; font-size: 24rpx; width: 40rpx; line-height: 1.8; flex-shrink: 0; }
.pl-bad { flex: 1; font-size: 28rpx; line-height: 1.7; color: $tt-text; }
.pl-fix-row { margin-top: 6rpx; }
.pl-ok {
  flex-shrink: 0; width: 30rpx; height: 30rpx; line-height: 30rpx; margin: 8rpx 10rpx 0 0;
  border-radius: 6rpx; background: $tt-tag-bg; color: $tt-primary; font-size: 20rpx; text-align: center;
}
.pl-fix { flex: 1; font-size: 26rpx; line-height: 1.7; color: $tt-primary-deep; }
.pl-more { text-align: center; color: $tt-primary; font-size: 26rpx; padding: 18rpx 0 4rpx; }
.pl-src { display: block; color: $tt-text-3; font-size: 22rpx; margin-top: 12rpx; }
</style>
