import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('ve_token') || '')
  const username = ref(localStorage.getItem('ve_username') || '')

  const isLoggedIn = computed(() => !!token.value)

  function login(tok, user) {
    token.value = tok
    username.value = user
    localStorage.setItem('ve_token', tok)
    localStorage.setItem('ve_username', user)
  }

  function logout() {
    token.value = ''
    username.value = ''
    localStorage.removeItem('ve_token')
    localStorage.removeItem('ve_username')
  }

  return { token, username, isLoggedIn, login, logout }
})
