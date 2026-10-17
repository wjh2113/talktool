<template>
  <view class="page" :style="{ paddingTop: statusBar + 60 + 'px' }">
    <view class="brand">
      <text class="brand-title">沟通训练</text>
      <text class="brand-sub">AI 扮演对手，在真实场景里练习说话</text>
    </view>

    <view class="card box">
      <view class="tabs">
        <view class="tab" :class="{ on: mode === 'login' }" @tap="mode = 'login'">登录</view>
        <view class="tab" :class="{ on: mode === 'register' }" @tap="mode = 'register'">邀请码注册</view>
      </view>

      <view v-if="mode === 'register'" class="field">
        <text class="label">邀请码</text>
        <input v-model="form.code" class="input code" placeholder="8 位邀请码" maxlength="12" />
      </view>
      <view class="field">
        <text class="label">用户名</text>
        <input v-model="form.username" class="input" placeholder="2-20 位字母、数字或汉字" maxlength="20" />
      </view>
      <view class="field">
        <text class="label">密码</text>
        <input v-model="form.password" class="input" password placeholder="至少 6 位" maxlength="64" />
      </view>
      <block v-if="mode === 'register'">
        <view class="field">
          <text class="label">确认密码</text>
          <input v-model="form.password2" class="input" password placeholder="再输入一次" maxlength="64" />
        </view>
        <view class="field">
          <text class="label">昵称（选填）</text>
          <input v-model="form.nickname" class="input" placeholder="怎么称呼你" maxlength="20" />
        </view>
      </block>

      <view class="btn-primary submit" :class="{ busy }" @tap="submit">
        {{ busy ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录' }}
      </view>
      <text class="hint muted">
        {{ mode === 'login' ? '还没有账号？向管理员要一个邀请码再注册。' : '邀请码由管理员发放，每个码有使用次数和有效期。' }}
      </text>
    </view>
  </view>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { getDeviceId, saveLogin } from '../../utils/request'

const statusBar = ref(uni.getSystemInfoSync().statusBarHeight || 20)
const mode = ref('login')
const busy = ref(false)
const form = reactive({ code: '', username: '', password: '', password2: '', nickname: '' })

function toast(title) {
  uni.showToast({ title, icon: 'none', duration: 2500 })
}

async function submit() {
  if (busy.value) return
  const username = form.username.trim()
  if (!username || !form.password) return toast('请输入用户名和密码')
  if (mode.value === 'register') {
    if (!form.code.trim()) return toast('请输入邀请码')
    if (form.password.length < 6) return toast('密码至少 6 位')
    if (form.password !== form.password2) return toast('两次输入的密码不一致')
  }
  busy.value = true
  try {
    const res =
      mode.value === 'login'
        ? await api.login(username, form.password)
        : await api.register({
            invite_code: form.code.trim(),
            username,
            password: form.password,
            nickname: form.nickname.trim(),
            device_id: getDeviceId() || null
          })
    saveLogin(res)
    if (res.claimed_sessions) toast(`已把这台设备上的 ${res.claimed_sessions} 条训练记录归到你的账号`)
    setTimeout(() => uni.reLaunch({ url: '/pages/index/index' }), res.claimed_sessions ? 1200 : 0)
  } catch (e) {
    // 错误提示已由 request 统一弹出
  } finally {
    busy.value = false
  }
}

onLoad((q) => {
  // 管理员分享的邀请链接：/#/pages/login/login?code=XXXXXXXX
  if (q && q.code) {
    form.code = String(q.code).toUpperCase()
    mode.value = 'register'
  }
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: linear-gradient(180deg, $tt-tag-bg 0%, $tt-bg 45%); padding: 0 40rpx 60rpx; box-sizing: border-box; }
.brand { display: flex; flex-direction: column; align-items: center; margin-bottom: 56rpx; }
.brand-title { font-size: 56rpx; font-weight: 800; color: $tt-text; letter-spacing: 4rpx; }
.brand-sub { font-size: 26rpx; color: $tt-text-2; margin-top: 14rpx; }
.box { padding: 20rpx 40rpx 44rpx; }
.tabs { display: flex; border-bottom: 1rpx solid #EEF1F5; margin-bottom: 28rpx; }
.tab {
  flex: 1; text-align: center; height: 96rpx; line-height: 96rpx; font-size: 30rpx; color: $tt-text-2; position: relative;
  &.on { color: $tt-primary; font-weight: 700; }
  &.on::after { content: ''; position: absolute; left: 50%; bottom: 0; width: 64rpx; height: 6rpx; margin-left: -32rpx; border-radius: 3rpx; background: $tt-primary; }
}
.field { margin-bottom: 24rpx; }
.label { display: block; font-size: 25rpx; color: $tt-text-2; margin-bottom: 10rpx; }
.input {
  height: 88rpx; padding: 0 24rpx; border-radius: 14rpx; background: #F7F9FC; border: 1rpx solid #E3E7ED; font-size: 30rpx;
}
.code { letter-spacing: 6rpx; text-transform: uppercase; }
.submit { margin-top: 40rpx; &.busy { opacity: 0.6; } }
.hint { display: block; text-align: center; margin-top: 24rpx; line-height: 1.6; }
</style>
