<template>
  <div class="menu-bar">
    <span class="logo">🌿 VE</span>
    <span class="menu-item" @click="$emit('menu-click','files')">文件</span>
    <span class="menu-item" @click="$emit('menu-click','git')">Git</span>
    <span class="menu-item" @click="$emit('menu-click','settings')">设置</span>
    <div class="tabs">
      <div v-if="editorStore.activeFilePath" class="tab">
        <span>📄 {{ editorStore.activeFilePath.split('/').pop() }}</span>
        <span v-if="editorStore.unsaved" class="unsaved">●</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useEditorStore } from '@/stores/editor'
defineEmits(['menu-click'])
const editorStore = useEditorStore()
</script>
