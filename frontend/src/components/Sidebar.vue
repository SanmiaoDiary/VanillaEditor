<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <span>资源管理器</span>
      <i class="bi bi-plus-lg" style="cursor:pointer" title="新建文件" @click="$emit('new-file')"></i>
    </div>
    <div class="sidebar-content">
      <template v-for="doc in files" :key="doc.id">
        <div class="tree-item" @click="toggleFolder(doc.id)">
          <span class="arrow">{{ expanded[doc.id] ? '▼' : '▶' }}</span>
          <span class="icon">📁</span>
          <span class="name">{{ doc.name }}</span>
          <span style="font-size:10px;color:var(--text-secondary)">{{ doc.file_count }}</span>
        </div>
        <template v-if="expanded[doc.id]">
          <div
            v-for="file in doc.children"
            :key="file.path"
            class="tree-item"
            :class="{ active: isActive(doc.id, file.path) }"
            @click="$emit('file-click', doc.id, file.path)"
          >
            <span class="arrow" style="width:12px"></span>
            <span class="icon">{{ file.path.endsWith('.md') ? '📝' : '📄' }}</span>
            <span class="name">{{ file.path.split('/').pop() }}</span>
            <span v-if="file.unsaved" class="dot"></span>
          </div>
        </template>
      </template>
      <div v-if="files.length === 0" style="padding:12px;font-size:12px;color:var(--text-secondary)">
        暂无文档，点击右上角 + 新建
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useEditorStore } from '@/stores/editor'

const props = defineProps({ files: Array })
const emit = defineEmits(['file-click', 'folder-click', 'new-file'])
const editorStore = useEditorStore()
const expanded = ref({})

function isActive(docId, path) {
  return editorStore.activeDocId === docId && editorStore.activeFilePath === path
}

function toggleFolder(docId) {
  expanded.value = { ...expanded.value, [docId]: !expanded.value[docId] }
  emit('folder-click', docId)
}
</script>
