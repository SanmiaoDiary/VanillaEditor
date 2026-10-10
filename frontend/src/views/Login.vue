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
        <div v-if="error" class="text-danger mb-3" style="font-size:12px">{{ error }}</div>
        <button type="submit" class="btn btn-primary w-100 mb-2" :disabled="loading">
          {{ loading ? '登录中...' : '登录' }}
        </button>
        <div v-if="!hasAccount" class="text-muted" style="font-size:11px">
          首次使用，将自动创建管理员账号
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const router = useRouter()
const auth = useAuthStore()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const hasAccount = ref(false)

onMounted(async () => {
  if (auth.isLoggedIn) {
    router.push('/editor')
    return
  }
  try {
    const res = await api.get('/auth/me')
    if (res.data.username) {
      auth.login('', res.data.username)
      router.push('/editor')
    }
  } catch {
    // no account yet
  }
})

async function handleSubmit() {
  error.value = ''
  loading.value = true
  try {
    const res = await api.post('/auth/login', { username: username.value, password: password.value })
    auth.login(res.data.token, res.data.username)
    router.push('/editor')
  } catch (e) {
    error.value = e.response?.data?.error || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
