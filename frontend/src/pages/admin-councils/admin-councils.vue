<template>
  <view class="page">
    <view v-if="!edit">
      <text class="intro muted">每个智囊团 = 一组谋士 + 一部分谋略库 + 一份提示词。意图识别会把问题分给启用的智囊团；新建一个团后，它自动出现在识别的选项里。</text>
      <view v-for="c in items" :key="c.code" class="card row" :class="{ off: !c.enabled }" @tap="open(c)">
        <text class="icon">{{ c.icon }}</text>
        <view class="row-body">
          <text class="row-name">{{ c.name }}<text class="muted"> · {{ c.code }}</text></text>
          <text class="muted">{{ c.advisor_list.map((a) => a.name).join('、') }}</text>
        </view>
        <text class="ver">{{ c.enabled ? (c.prompt_version ? '提示词 v' + c.prompt_version : '默认提示词') : '已停用' }}</text>
      </view>
      <view class="btn-primary add" @tap="open(null)">＋ 新建智囊团</view>
    </view>

    <view v-else class="card box">
      <text class="back" @tap="edit = null">‹ 返回</text>
      <template v-if="isNew">
        <text class="label">代码（英文，建好后不能改）</text>
        <input v-model="form.code" class="inp" placeholder="例如 newbie" />
      </template>
      <text class="label">名称</text>
      <input v-model="form.name" class="inp" placeholder="例如 职场新人团" />
      <text class="label">图标字（一个字）</text>
      <input v-model="form.icon" class="inp short" maxlength="2" />
      <text class="label">处理什么问题（意图识别靠这句话分派）</text>
      <textarea v-model="form.description" class="ta" auto-height />
      <text class="label">谋士（最多 4 位）</text>
      <view class="chips">
        <text v-for="a in opts.advisors" :key="a.code" class="chip" :class="{ on: form.advisors.includes(a.code) }" @tap="toggle('advisors', a.code)">{{ a.name }}</text>
      </view>
      <text class="label">谋略子库：体系（不选 = 全库）</text>
      <view class="chips">
        <text v-for="s in opts.schools" :key="s.code" class="chip" :class="{ on: form.schools.includes(s.code) }" @tap="toggle('schools', s.code)">{{ s.name }}</text>
      </view>
      <text class="label">优先的领域</text>
      <view class="chips">
        <text v-for="d in opts.domains" :key="d" class="chip" :class="{ on: form.domains.includes(d) }" @tap="toggle('domains', d)">{{ d }}</text>
      </view>
      <text class="label">本团特别要求（会写进默认提示词）</text>
      <textarea v-model="form.requirement" class="ta" auto-height />
      <text class="label">示例问题（每行一个，显示在智囊首页）</text>
      <textarea v-model="form.examplesText" class="ta" auto-height />
      <view class="switch-row">
        <text>启用</text>
        <switch :checked="form.enabled" color="#0D8A7B" :disabled="form.code === 'general'" @change="(e) => (form.enabled = e.detail.value)" />
      </view>
      <view class="btns">
        <view v-if="!isNew" class="btn-plain" @tap="editPrompt">编辑它的提示词</view>
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
const opts = ref({ advisors: [], schools: [], domains: [] })
const edit = ref(null)
const isNew = ref(false)
const form = ref({})

async function load() {
  const r = await api.adminCouncils()
  items.value = r.items
  opts.value = r.options
}

function open(c) {
  isNew.value = !c
  edit.value = c || {}
  form.value = c
    ? { code: c.code, name: c.name, icon: c.icon, description: c.description, advisors: [...c.advisors], schools: [...c.schools],
        domains: [...c.domains], requirement: c.requirement, examplesText: c.examples.join('\n'), enabled: c.enabled }
    : { code: '', name: '', icon: '', description: '', advisors: ['junshi'], schools: [], domains: [], requirement: '', examplesText: '', enabled: true }
}

function toggle(field, v) {
  const arr = form.value[field]
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1)
  else if (field !== 'advisors' || arr.length < 4) arr.push(v)
}

async function save() {
  const data = { ...form.value, examples: form.value.examplesText.split('\n').map((s) => s.trim()).filter(Boolean) }
  delete data.examplesText
  if (isNew.value) await api.adminCreateCouncil(data)
  else await api.adminSaveCouncil(form.value.code, data)
  uni.showToast({ title: '已保存', icon: 'none' })
  edit.value = null
  load()
}

const editPrompt = () => uni.navigateTo({ url: `/pages/admin-prompts/admin-prompts?key=council.${form.value.code}` })

onShow(() => load().catch(() => {}))
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 24rpx 28rpx 80rpx; box-sizing: border-box; }
.intro { display: block; line-height: 1.7; margin-bottom: 20rpx; }
.row { display: flex; align-items: center; gap: 18rpx; padding: 24rpx 28rpx; margin-bottom: 14rpx; }
.row.off { opacity: 0.5; }
.icon { width: 64rpx; height: 64rpx; line-height: 64rpx; text-align: center; border-radius: 50%; background: $tt-soft; color: $tt-primary; font-weight: 700; flex-shrink: 0; }
.row-body { flex: 1; display: flex; flex-direction: column; gap: 4rpx; }
.row-name { font-size: 28rpx; font-weight: 600; }
.ver { font-size: 22rpx; color: $tt-text-3; }
.add { margin-top: 24rpx; }
.box { padding: 28rpx; display: flex; flex-direction: column; }
.back { color: $tt-primary; font-size: 27rpx; margin-bottom: 8rpx; }
.label { font-size: 24rpx; color: $tt-text-2; margin: 22rpx 0 10rpx; }
.inp { height: 72rpx; background: $tt-bg; border-radius: 12rpx; padding: 0 20rpx; font-size: 27rpx; }
.inp.short { width: 120rpx; }
.ta { width: 100%; min-height: 100rpx; box-sizing: border-box; padding: 16rpx 20rpx; background: $tt-bg; border-radius: 12rpx; font-size: 26rpx; line-height: 1.6; }
.chips { display: flex; flex-wrap: wrap; gap: 12rpx; }
.chip { font-size: 24rpx; padding: 8rpx 20rpx; border-radius: 24rpx; background: $tt-bg; color: $tt-text-2; }
.chip.on { background: $tt-primary; color: #fff; }
.switch-row { display: flex; align-items: center; justify-content: space-between; margin-top: 24rpx; font-size: 27rpx; }
.btns { display: flex; gap: 16rpx; margin-top: 28rpx; }
.btns > view { flex: 1; }
</style>
