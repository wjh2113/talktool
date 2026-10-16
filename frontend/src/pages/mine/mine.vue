<template>
  <view class="page">
    <view class="card user">
      <view class="avatar">{{ (user.nickname || user.username || '练').slice(0, 1) }}</view>
      <view class="user-info">
        <text class="name">{{ user.nickname || user.username }}</text>
        <text class="muted">@{{ user.username }}<text v-if="user.role === 'admin'" class="admin-tag">管理员</text></text>
      </view>
      <text class="edit" @tap="editNickname">改昵称</text>
    </view>

    <view class="card menu">
      <view v-if="user.role === 'admin'" class="row" @tap="go('/pages/admin/admin')">
        <text>管理后台（邀请码 / 用户）</text>
        <text class="chevron">›</text>
      </view>
      <view class="row" @tap="go('/pages/records/records')">
        <text>训练记录</text>
        <text class="chevron">›</text>
      </view>
      <view class="row" @tap="go('/pages/custom/custom')">
        <text>我的自定义场景</text>
        <text class="chevron">›</text>
      </view>
      <view class="row" @tap="showPwd = !showPwd">
        <text>修改密码</text>
        <text class="chevron">{{ showPwd ? '⌄' : '›' }}</text>
      </view>
      <view v-if="showPwd" class="pwd">
        <input v-model="pwd.old" class="input" password placeholder="原密码" />
        <input v-model="pwd.new1" class="input" password placeholder="新密码（至少 6 位）" />
        <input v-model="pwd.new2" class="input" password placeholder="再输入一次新密码" />
        <view class="btn-primary small" @tap="changePwd">确认修改</view>
      </view>
      <view class="row">
        <text>服务状态</text>
        <text class="muted">{{ healthText }}</text>
      </view>
    </view>

    <view class="btn-plain logout" @tap="logout">退出登录</view>
    <text class="foot muted">训练结果仅反映单次练习表现，仅供参考</text>
  </view>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api } from '../../utils/api'
import { clearLogin, getCurrentUser, saveLogin } from '../../utils/request'

const user = ref(getCurrentUser() || {})
const healthText = ref('检测中…')
const showPwd = ref(false)
const pwd = reactive({ old: '', new1: '', new2: '' })

const go = (url) => uni.navigateTo({ url })

function editNickname() {
  uni.showModal({
    title: '修改昵称',
    editable: true,
    placeholderText: user.value.nickname || '',
    success: async (r) => {
      const v = (r.content || '').trim()
      if (!r.confirm || !v) return
      const u = await api.updateProfile(v)
      user.value = u
      saveLogin({ user: u })
    }
  })
}

async function changePwd() {
  if (!pwd.old || !pwd.new1) return uni.showToast({ title: '请填写完整', icon: 'none' })
  if (pwd.new1.length < 6) return uni.showToast({ title: '新密码至少 6 位', icon: 'none' })
  if (pwd.new1 !== pwd.new2) return uni.showToast({ title: '两次输入的新密码不一致', icon: 'none' })
  await api.changePassword(pwd.old, pwd.new1)
  pwd.old = pwd.new1 = pwd.new2 = ''
  showPwd.value = false
  uni.showToast({ title: '密码已修改', icon: 'none' })
}

function logout() {
  uni.showModal({
    title: '退出登录？',
    success: async (r) => {
      if (!r.confirm) return
      await api.logout().catch(() => {})
      clearLogin()
      uni.reLaunch({ url: '/pages/login/login' })
    }
  })
}

onShow(async () => {
  api.me().then((u) => {
    if (u) {
      user.value = u
      saveLogin({ user: u })
    }
  }).catch(() => {})
  try {
    const h = await api.health()
    healthText.value = h.mock ? '在线 · Mock 模式' : '在线 · 已连接网关'
  } catch (e) {
    healthText.value = '后端未连接'
  }
})
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: $tt-bg; padding: 32rpx; box-sizing: border-box; }
.user { display: flex; align-items: center; padding: 40rpx 36rpx; margin-bottom: 28rpx; }
.avatar {
  width: 112rpx; height: 112rpx; border-radius: 50%; background: $tt-tag-bg; color: $tt-primary;
  font-size: 44rpx; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-right: 28rpx;
}
.user-info { flex: 1; display: flex; flex-direction: column; }
.name { font-size: 34rpx; font-weight: 700; margin-bottom: 8rpx; }
.admin-tag { margin-left: 12rpx; font-size: 22rpx; color: $tt-primary; background: $tt-tag-bg; padding: 2rpx 10rpx; border-radius: 8rpx; }
.edit { font-size: 25rpx; color: $tt-primary; }
.menu { padding: 0 36rpx; }
.row {
  display: flex; justify-content: space-between; align-items: center;
  height: 108rpx; font-size: 30rpx; border-bottom: 1rpx solid #EEF1F5;
  &:last-child { border-bottom: none; }
}
.pwd { padding: 20rpx 0 28rpx; border-bottom: 1rpx solid #EEF1F5; }
.input { height: 80rpx; padding: 0 22rpx; border-radius: 12rpx; background: #F7F9FC; border: 1rpx solid #E3E7ED; font-size: 28rpx; margin-bottom: 16rpx; }
.small { height: 80rpx; line-height: 80rpx; font-size: 28rpx; }
.logout { margin-top: 40rpx; color: #E5484D; }
.foot { display: block; text-align: center; margin-top: 40rpx; }
</style>
