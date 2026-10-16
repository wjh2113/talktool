<template>
  <view class="page">
    <view class="card box">
      <text class="title">练习本</text>
      <text class="sub">收藏的话术、AI 示范与错题回顾会放在这里。</text>
      <text class="muted">MVP 版本暂未开放，敬请期待</text>
    </view>
  </view>
</template>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx; box-sizing: border-box; }
.box { padding: 80rpx 40rpx; display: flex; flex-direction: column; align-items: center; text-align: center; }
.title { font-size: 36rpx; font-weight: 700; margin-bottom: 20rpx; }
.sub { font-size: 28rpx; color: $tt-text-2; margin-bottom: 20rpx; line-height: 1.6; }
</style>
