<template>
  <view class="page">
    <view v-if="!form">
      <text class="intro muted">私人谋士是你自己设定的顾问：可以是信任的前辈、朋友、家人，也可以是你想象中的高人。问计时请他们列席（最多 2 位），他们会按你写的人设参与出锦囊和圆桌会议。只有你自己能看到。</text>

      <view v-for="a in items" :key="a.code" class="card row" @tap="edit(a)">
        <text class="avatar">{{ a.avatar }}</text>
        <view class="row-body">
          <text class="row-name">{{ a.name }}<text v-if="a.style" class="muted"> · {{ a.style }}</text></text>
          <text class="persona">{{ a.persona }}</text>
          <text v-if="a.school_names.length" class="schools">擅长：{{ a.school_names.join('、') }}</text>
        </view>
        <text class="chevron">›</text>
      </view>

      <view v-if="!items.length" class="card empty">
        <text class="empty-title">还没有私人谋士</text>
        <text class="muted">从下面的模板开始，或者自己写一个</text>
        <view v-for="t in templates" :key="t.name" class="tpl" @tap="edit(null, t)">
          <text class="avatar small">{{ t.avatar }}</text>
          <view class="row-body">
            <text class="row-name">{{ t.name }}</text>
            <text class="persona">{{ t.persona }}</text>
          </view>
        </view>
      </view>

      <view v-if="items.length < max" class="btn-primary add" @tap="edit(null)">＋ 新建私人谋士</view>
      <text v-else class="muted foot">最多 {{ max }} 位</text>
    </view>

    <view v-else class="card box">
      <text class="label">名字</text>
      <input v-model="form.name" class="inp" maxlength="10" placeholder="例如：老周、Linda、妈妈" />
      <text class="label">头像字（一个字）</text>
      <input v-model="form.avatar" class="inp short" maxlength="2" :placeholder="form.name.slice(0, 1)" />
      <text class="label">人设：他是谁、看问题的角度、说话风格</text>
      <textarea v-model="form.persona" class="ta" auto-height maxlength="300"
                placeholder="例如：在国企干了二十年的老处长，看问题先看人和关系；说话直白，爱举自己当年的例子" />
      <text class="count muted">{{ form.persona.length }}/300</text>
      <text class="label">风格</text>
      <view class="chips">
        <text v-for="st in styles" :key="st" class="chip" :class="{ on: form.style === st }" @tap="form.style = form.style === st ? '' : st">{{ st }}</text>
      </view>
      <text class="label">擅长的谋略（最多 4 个，可不选）</text>
      <view class="chips">
        <text v-for="s in schools" :key="s.code" class="chip" :class="{ on: form.schools.includes(s.code) }" @tap="toggleSchool(s.code)">{{ s.name }}</text>
      </view>
      <view class="btns">
        <view class="btn-plain" @tap="form = null">取消</view>
        <view v-if="form.code" class="btn-plain danger" @tap="remove">删除</view>
        <view class="btn-primary" @tap="save">保存</view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api } from '../../utils/api'

const items = ref([])
const templates = ref([])
const styles = ref([])
const schools = ref([])
const max = ref(6)
const form = ref(null)

async function load() {
  const r = await api.myAdvisors()
  items.value = r.items
  templates.value = r.templates
  styles.value = r.styles
  schools.value = r.schools
  max.value = r.max
}

function edit(a, tpl) {
  const src = a || tpl || {}
  form.value = {
    code: a ? a.code : '',
    name: src.name || '',
    avatar: src.avatar || '',
    persona: src.persona || '',
    style: src.style || '',
    schools: [...(src.schools || [])]
  }
}

function toggleSchool(code) {
  const arr = form.value.schools
  const i = arr.indexOf(code)
  if (i >= 0) arr.splice(i, 1)
  else if (arr.length < 4) arr.push(code)
}

async function save() {
  const f = form.value
  if (!f.name.trim()) return uni.showToast({ title: '给谋士起个名字', icon: 'none' })
  if (f.persona.trim().length < 6) return uni.showToast({ title: '人设多写几句', icon: 'none' })
  const data = { name: f.name, avatar: f.avatar, persona: f.persona, style: f.style, schools: f.schools }
  if (f.code) await api.updateMyAdvisor(f.code, data)
  else await api.createMyAdvisor(data)
  uni.showToast({ title: '已保存', icon: 'none' })
  form.value = null
  load()
}

function remove() {
  uni.showModal({
    title: `删除「${form.value.name}」？`,
    content: '历史锦囊里他说过的话会保留。',
    confirmColor: '#E5564B',
    success: async (r) => {
      if (!r.confirm) return
      await api.deleteMyAdvisor(form.value.code)
      form.value = null
      load()
    }
  })
}

onShow(() => load().catch(() => {}))
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 24rpx 28rpx 80rpx; box-sizing: border-box; }
.intro { display: block; line-height: 1.7; margin-bottom: 20rpx; }
.row { display: flex; align-items: flex-start; gap: 18rpx; padding: 26rpx 28rpx; margin-bottom: 16rpx; }
.avatar {
  width: 72rpx; height: 72rpx; line-height: 72rpx; text-align: center; border-radius: 50%; flex-shrink: 0;
  background: #E8A13A; color: #fff; font-weight: 700; font-size: 30rpx;
}
.avatar.small { width: 56rpx; height: 56rpx; line-height: 56rpx; font-size: 24rpx; }
.row-body { flex: 1; display: flex; flex-direction: column; gap: 6rpx; min-width: 0; }
.row-name { font-size: 29rpx; font-weight: 700; }
.persona { font-size: 25rpx; color: $tt-text-2; line-height: 1.6; }
.schools { font-size: 22rpx; color: $tt-primary; }
.chevron { color: $tt-text-3; font-size: 36rpx; align-self: center; }
.empty { padding: 30rpx; display: flex; flex-direction: column; gap: 10rpx; }
.empty-title { font-size: 30rpx; font-weight: 700; }
.tpl { display: flex; gap: 16rpx; padding: 18rpx; background: $tt-bg; border-radius: 16rpx; margin-top: 12rpx; }
.add { margin-top: 24rpx; }
.foot { display: block; text-align: center; margin-top: 24rpx; }
.box { padding: 28rpx; display: flex; flex-direction: column; }
.label { font-size: 24rpx; color: $tt-text-2; margin: 22rpx 0 10rpx; }
.inp { height: 72rpx; background: $tt-bg; border-radius: 12rpx; padding: 0 20rpx; font-size: 27rpx; }
.inp.short { width: 120rpx; }
.ta { width: 100%; min-height: 160rpx; box-sizing: border-box; padding: 16rpx 20rpx; background: $tt-bg; border-radius: 12rpx; font-size: 26rpx; line-height: 1.6; }
.count { text-align: right; font-size: 22rpx; margin-top: 6rpx; }
.chips { display: flex; flex-wrap: wrap; gap: 12rpx; }
.chip { font-size: 24rpx; padding: 8rpx 20rpx; border-radius: 24rpx; background: $tt-bg; color: $tt-text-2; }
.chip.on { background: $tt-primary; color: #fff; }
.btns { display: flex; gap: 16rpx; margin-top: 32rpx; }
.btns > view { flex: 1; }
.danger { color: #E5564B; }
</style>
