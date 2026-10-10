<template>
  <div class="layout">
    <MenuBar @menu-click="handleMenu" />
    <div class="main-area">
      <ActivityBar :active-panel="activePanel" @panel-change="setPanel" />
      <Sidebar v-if="activePanel === 'files'" :files="files" @file-click="openFile" @folder-click="toggleFolder" />
      <GitPanel v-else-if="activePanel === 'git'" :docs="docs" @open-doc="openFile" />
      <div class="editor-area">
        <EditorPane
          :doc-id="editorStore.activeDocId"
          :file-path="editorStore.activeFilePath"
          :content="editorStore.content"
          @change="onEditorChange"
          @save="saveFile"
        />
        <PreviewPane :content="editorStore.content" />
      </div>
    </div>
    <StatusBar :branch="editorStore.gitBranch" :sha="editorStore.fileSha" :unsaved="editorStore.unsaved" />
    <Toast :toasts="toasts" @dismiss="dismissToast" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useEditorStore } from '@/stores/editor'
import MenuBar from '@/components/MenuBar.vue'
import ActivityBar from '@/components/ActivityBar.vue'
import Sidebar from '@/components/Sidebar.vue'
import GitPanel from '@/components/GitPanel.vue'
import EditorPane from '@/components/EditorPane.vue'
import PreviewPane from '@/components/PreviewPane.vue'
import StatusBar from '@/components/StatusBar.vue'
import Toast from '@/components/Toast.vue'
import api from '@/api'

const auth = useAuthStore()
const editorStore = useEditorStore()
const activePanel = ref('files')
const files = ref([])
const docs = ref([])
const toasts = ref([])

function addToast(msg, type = 'info') {
  const id = Date.now()
  toasts.value.push({ id, msg, type })
  setTimeout(() => dismissToast(id), 3000)
}

function dismissToast(id) {
  toasts.value = toasts.value.filter(t => t.id !== id)
}

async function handleMenu(action) {
  if (action === 'git') {
    activePanel.value = activePanel.value === 'git' ? 'files' : 'git'
  } else if (action === 'files') {
    activePanel.value = activePanel.value === 'files' ? '' : 'files'
  } else if (action === 'settings') {
    // settings in future
  } else if (action === 'logout') {
    auth.logout()
    window.location.reload()
  }
}

async function setPanel(panel) {
  activePanel.value = panel
}

async function loadFiles() {
  try {
    const res = await api.get('/docs')
    docs.value = res.data
    if (res.data.length > 0) {
      const first = res.data[0]
      editorStore.activeDocId = first.id
      if (first.children?.length > 0) {
        await openFile(first.id, first.children[0].path)
      }
    }
  } catch (e) {
    console.error('Failed to load docs', e)
  }
}

async function openFile(docId, filePath) {
  editorStore.activeDocId = docId
  try {
    const res = await api.get(`/files/${docId}/${encodeURIComponent(filePath)}`)
    editorStore.setActiveFile(docId, filePath, res.data.content, res.data.sha)
    editorStore.gitBranch = 'main'
  } catch (e) {
    addToast('无法打开文件', 'error')
  }
}

function onEditorChange(newContent) {
  editorStore.content = newContent
  editorStore.markUnsaved()
}

let saveTimer = null
async function saveFile() {
  if (!editorStore.activeDocId || !editorStore.activeFilePath) return
  try {
    await api.put(`/files/${editorStore.activeDocId}/${encodeURIComponent(editorStore.activeFilePath)}`, {
      content: editorStore.content
    })
    editorStore.clearUnsaved()
    addToast('已保存', 'success')
  } catch (e) {
    addToast('保存失败', 'error')
  }
}

onMounted(loadFiles)
</script>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}
.main-area {
  display: flex;
  flex: 1;
  overflow: hidden;
}
.editor-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
