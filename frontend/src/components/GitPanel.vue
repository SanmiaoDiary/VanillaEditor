<template>
  <div class="git-panel">
    <div class="section-title">
      <i class="bi bi-git"></i> 版本管理
      <span class="count">{{ changedFiles.length }}</span>
    </div>

    <!-- 拉取 -->
    <button class="btn btn-git mb-2" @click="pull" :disabled="loading">
      <i class="bi bi-arrow-down"></i> 拉取
    </button>

    <!-- 提交到暂存区 -->
    <button class="btn btn-secondary-git mb-2" @click="stageAll" :disabled="loading || changedFiles.length === 0">
      <i class="bi bi-plus-circle"></i> 暂存全部
    </button>

    <!-- 提交信息 -->
    <div style="margin:8px 0;font-size:12px;color:var(--text-secondary)">提交信息：</div>
    <textarea
      v-model="commitMsg"
      class="commit-msg"
      placeholder="描述本次更改..."
      :disabled="loading"
    ></textarea>

    <!-- 操作按钮 -->
    <div class="commit-actions">
      <button class="btn btn-git" @click="commit" :disabled="loading || !commitMsg.trim()">
        <i class="bi bi-check-circle"></i> 提交
      </button>
      <button class="btn btn-secondary-git" @click="push" :disabled="loading">
        <i class="bi bi-arrow-up"></i> 推送
      </button>
    </div>

    <!-- 同步到 -->
    <div class="sync-row">
      <select v-model="selectedRemote" class="form-select form-select-sm" style="background:var(--bg-primary);color:var(--text-primary);border-color:var(--border);flex:1">
        <option value="">选择同步目标...</option>
        <option v-for="r in remotes" :key="r.name" :value="r.name">{{ r.name }}</option>
        <option value="__all">所有设备</option>
      </select>
      <button class="btn btn-secondary-git" @click="syncTo" :disabled="loading || !selectedRemote">
        <i class="bi bi-arrows-move"></i> 同步
      </button>
    </div>

    <!-- 历史 -->
    <div class="section-title mt-3">
      <i class="bi bi-clock-history"></i> 最近提交
    </div>
    <div v-for="c in commits" :key="c.sha" class="commit-item" @click="showDiff(c.sha)">
      <span class="dot"></span>
      <span class="msg">{{ c.message }}</span>
      <span class="time">{{ c.date }}</span>
    </div>
    <div v-if="commits.length === 0" style="font-size:12px;color:var(--text-secondary);padding:4px 0">
      暂无提交记录
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { useEditorStore } from '@/stores/editor'
import api from '@/api'

const props = defineProps({ docs: Array })
const emit = defineEmits(['open-doc'])
const editorStore = useEditorStore()

const commitMsg = ref('')
const loading = ref(false)
const selectedRemote = ref('')
const remotes = ref([])
const commits = ref([])
const changedFiles = computed(() => editorStore.changedFiles || [])

async function loadRemotes() {
  if (!editorStore.activeDocId) return
  try {
    const res = await api.get('/sync/remote', { params: { doc_id: editorStore.activeDocId } })
    remotes.value = res.data
  } catch {}
}

async function loadHistory() {
  if (!editorStore.activeDocId) return
  try {
    const res = await api.get(`/history/${editorStore.activeDocId}`)
    commits.value = res.data
  } catch {}
}

async function pull() {
  if (!editorStore.activeDocId) return
  loading.value = true
  try {
    const res = await api.post('/sync/pull', { doc_id: editorStore.activeDocId })
    if (res.data.ok) {
      emit('refresh')
    }
  } catch (e) {
    alert('拉取失败: ' + (e.response?.data?.error || e.message))
  } finally {
    loading.value = false
  }
}

async function stageAll() {
  // In our implementation, commit includes add-all
  // Just inform user
}

async function commit() {
  if (!editorStore.activeDocId || !commitMsg.value.trim()) return
  loading.value = true
  try {
    const res = await api.post(`/commit`, {
      doc_id: editorStore.activeDocId,
      message: commitMsg.value
    })
    if (res.data.ok) {
      commitMsg.value = ''
      emit('refresh')
      loadHistory()
    }
  } catch (e) {
    alert('提交失败: ' + (e.response?.data?.error || e.message))
  } finally {
    loading.value = false
  }
}

async function push() {
  if (!editorStore.activeDocId) return
  loading.value = true
  try {
    const res = await api.post('/sync/push', { doc_id: editorStore.activeDocId })
    if (res.data.ok) {
      emit('refresh')
    }
  } catch (e) {
    alert('推送失败: ' + (e.response?.data?.error || e.message))
  } finally {
    loading.value = false
  }
}

async function syncTo() {
  if (!editorStore.activeDocId) return
  if (selectedRemote.value === '__all') {
    // push to all remotes then pull
    await push()
    await pull()
  } else {
    const remote = remotes.value.find(r => r.name === selectedRemote.value)
    if (!remote) return
    loading.value = true
    try {
      await api.post('/sync/push', { doc_id: editorStore.activeDocId, remote: selectedRemote.value })
      await api.post('/sync/pull', { doc_id: editorStore.activeDocId, remote: selectedRemote.value })
      emit('refresh')
    } catch (e) {
      alert('同步失败: ' + (e.response?.data?.error || e.message))
    } finally {
      loading.value = false
    }
  }
}

function showDiff(sha) {
  // Future: show diff in a modal
  console.log('Show diff for', sha)
}

watch(() => editorStore.activeDocId, () => {
  loadRemotes()
  loadHistory()
})

loadRemotes()
loadHistory()
</script>
