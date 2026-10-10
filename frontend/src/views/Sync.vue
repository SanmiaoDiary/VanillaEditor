<template>
  <div style="padding:20px">
    <h4 style="color:var(--text-primary)">同步设置</h4>
    <div style="margin-top:16px;font-size:13px;color:var(--text-secondary)">
      将其他设备的 VE 地址添加为 Git 远端，即可进行端到端同步。
    </div>
    <div style="margin-top:12px">
      <input v-model="remoteUrl" placeholder="http://192.168.1.x:5000" class="form-control form-control-sm mb-2" style="background:var(--bg-secondary);color:var(--text-primary);border-color:var(--border);width:300px" />
      <button class="btn btn-git" @click="addRemote" :disabled="!remoteUrl">+ 添加远端</button>
    </div>
    <div style="margin-top:16px">
      <div v-for="r in remotes" :key="r.name" style="display:flex;align-items:center;gap:8px;padding:6px 0;font-size:13px">
        <i class="bi bi-hdd-network"></i>
        <span>{{ r.name }} — {{ r.url }}</span>
        <button class="btn btn-secondary-git btn-sm" @click="removeRemote(r.name)" style="margin-left:auto">删除</button>
      </div>
      <div v-if="remotes.length === 0" style="font-size:12px;color:var(--text-secondary)">暂无远端设备</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useEditorStore } from '@/stores/editor'
import api from '@/api'

const editorStore = useEditorStore()
const remoteUrl = ref('')
const remotes = ref([])

async function addRemote() {
  if (!remoteUrl.value || !editorStore.activeDocId) return
  try {
    await api.post('/sync/remote', { doc_id: editorStore.activeDocId, name: 'remote', url: remoteUrl.value })
    remotes.value.push({ name: 'remote', url: remoteUrl.value })
    remoteUrl.value = ''
  } catch (e) {
    alert('添加失败')
  }
}

async function removeRemote(name) {
  if (!editorStore.activeDocId) return
  await api.delete(`/sync/remote/${name}`, { data: { doc_id: editorStore.activeDocId } })
  remotes.value = remotes.value.filter(r => r.name !== name)
}
</script>
