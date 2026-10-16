<template>
  <view class="page">
    <view v-if="drill" class="card head">
      <text class="cat">跟读模式 · {{ drill.scenario_title }}</text>
      <text class="title">{{ drill.title }}</text>
      <text class="sub">先听示范，再照着读一遍。AI 会对照稿子给发音打分，指出没念准或漏掉的地方。</text>
    </view>

    <view class="card script">
      <view class="script-head">
        <text class="block-title">示范稿</text>
        <text v-if="script" class="star" :class="{ on: noteId }" @tap="toggleSave">{{ noteId ? '★ 已收藏' : '☆ 收藏' }}</text>
      </view>
      <text v-if="loading" class="muted">AI 正在写示范稿…</text>
      <text v-else class="script-txt">{{ script }}</text>
      <ReadAloud v-if="script" :text="script" :note-id="noteId" @scored="onScored" />
    </view>

    <view v-if="history.length" class="card block">
      <text class="block-title">本次练习</text>
      <view class="hist">
        <view v-for="(h, i) in history" :key="i" class="hist-item">
          <text class="hist-n">第 {{ i + 1 }} 遍</text>
          <text class="hist-s">{{ h }} 分</text>
        </view>
      </view>
    </view>

    <view class="tips card block">
      <text class="block-title">跟读小技巧</text>
      <text class="tip">· 先完整听一遍，留意停顿和重音的位置</text>
      <text class="tip">· 语速放在每分钟 180–240 字左右，宁慢勿含糊</text>
      <text class="tip">· 读熟后试着不看稿复述，再去做语音对练</text>
    </view>

    <view class="footer">
      <view class="btn-primary" @tap="goTrain">读熟了，开始对练</view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { unlockAudio } from '../../utils/voice'
import ReadAloud from '../../components/ReadAloud/ReadAloud.vue'

const drill = ref(null)
const script = ref('')
const loading = ref(true)
const noteId = ref(null)
const history = ref([])

async function toggleSave() {
  if (noteId.value) {
    await api.deleteNote(noteId.value)
    noteId.value = null
    uni.showToast({ title: '已取消收藏', icon: 'none' })
  } else {
    const n = await api.addNote({ kind: 'script', text: script.value, drill_id: drill.value.id })
    noteId.value = n.id
    uni.showToast({ title: '已收进练习本', icon: 'none' })
  }
}

function onScored(res) {
  if (typeof res.score === 'number') history.value = history.value.concat(res.score)
}

function goTrain() {
  unlockAudio()
  uni.redirectTo({ url: `/pages/train/train?drillId=${drill.value.id}` })
}

onLoad(async (q) => {
  drill.value = await api.drill(q.drillId)
  try {
    const [res, notes] = await Promise.all([api.drillScript(q.drillId), api.notes('script')])
    script.value = res.script
    const n = notes.find((x) => x.text === res.script)
    if (n) noteId.value = n.id
  } finally {
    loading.value = false
  }
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx 32rpx 200rpx; box-sizing: border-box; }
.head { padding: 36rpx; display: flex; flex-direction: column; margin-bottom: 24rpx; }
.cat { color: $tt-primary; font-size: 24rpx; margin-bottom: 12rpx; }
.title { font-size: 34rpx; font-weight: 700; line-height: 1.5; margin-bottom: 14rpx; }
.sub { font-size: 26rpx; color: $tt-text-2; line-height: 1.6; }
.script { padding: 36rpx; margin-bottom: 24rpx; }
.script-head { display: flex; justify-content: space-between; align-items: center; }
.block { padding: 36rpx; margin-bottom: 24rpx; }
.block-title { display: block; font-size: 30rpx; font-weight: 700; margin-bottom: 20rpx; }
.star { font-size: 25rpx; color: $tt-text-3; margin-bottom: 20rpx; &.on { color: #E6A23C; } }
.script-txt { display: block; font-size: 32rpx; line-height: 1.95; color: $tt-text; letter-spacing: 1rpx; }
.hist { display: flex; flex-wrap: wrap; gap: 16rpx; }
.hist-item { background: #F3F6FA; border-radius: 12rpx; padding: 12rpx 20rpx; display: flex; flex-direction: column; align-items: center; }
.hist-n { font-size: 22rpx; color: $tt-text-3; }
.hist-s { font-size: 30rpx; font-weight: 700; color: $tt-primary; }
.tip { display: block; font-size: 26rpx; color: $tt-text-2; line-height: 1.8; }
.footer {
  position: fixed; left: 0; right: 0; bottom: 0;
  padding: 24rpx 40rpx calc(24rpx + env(safe-area-inset-bottom));
  background: #fff; box-shadow: 0 -4rpx 20rpx rgba(0, 0, 0, 0.04);
}
</style>
