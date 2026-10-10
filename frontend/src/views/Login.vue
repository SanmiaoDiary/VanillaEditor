<template>
  <div class="login-container">
    <div class="login-box">
      <h2>🌿 VanillaEditor</h2>
      <p class="text-muted mb-4" style="font-size:12px">分布式离线 Markdown 编辑器</p>
      <form @submit.prevent="handleSubmit">
        <div class="mb-3">
          <input v-model="username" type="text" class="form-control" placeholder="用户名" required autofocus />
        </div>
        <div class="mb-3">
          <input v-model="password" type="password" class="form-control" placeholder="密码" required />
        </div>
        <div v-if="isRegister" class="mb-3">
          <input v-model="confirmPassword" type="password" class="form-control" placeholder="确认密码" required />
          <div v-if="confirmError" class="text-danger mt-1" style="font-size:11px">{{ confirmError }}</div>
        </div>
        <div v-if="error" class="text-danger mb-3" style="font-size:12px">{{ error }}</div>
        <button type="submit" class="btn btn-primary w-100 mb-2" :disabled="loading">
          {{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}
        </button>
        <button v-if="!isRegister" type="button" class="btn btn-link w-100" style="font-size:12px;color:#858585" @click="toggleMode">
          还没有账号？点击注册
        </button>
        <button v-else type="button" class="btn btn-link w-100" style="font-size:12px;color:#858585" @click="toggleMode">
          已有账号？返回登录
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const error = ref('')
const loading = ref(false)
const isRegister = ref(false)

const confirmError = computed(() => {
  if (!isRegister.value || !confirmPassword.value || confirmPassword.value === password.value) return ''
  return '两次输入的密码不一致'
})

async function handleSubmit() {
  error.value = ''
  if (confirmError.value) {
    error.value = confirmError.value
    return
  }
  loading.value = true
  try {
    if (isRegister.value) {
      const res = await api.post('/auth/init', { username: username.value, password: password.value })
      if (res.status === 201) {
        // 注册成功后自动登录
        const loginRes = await api.post('/auth/login', { username: username.value, password: password.value })
        auth.login(loginRes.data.token, loginRes.data.username)
        router.push('/editor')
      }
    } else {
      const res = await api.post('/auth/login', { username: username.value, password: password.value })
      auth.login(res.data.token, res.data.username)
      router.push('/editor')
    }
  } catch (e) {
    error.value = e.response?.data?.error || '操作失败，请重试'
  } finally {
    loading.value = false
  }
}

function toggleMode() {
  isRegister.value = !isRegister.value
  error.value = ''
  username.value = ''
  password.value = ''
  confirmPassword.value = ''
}
</script>
