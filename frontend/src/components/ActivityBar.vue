<template>
  <div class="activity-bar">
    <div class="icon-btn" :class="{ active: active === 'files' }" @click="$emit('panel-change','files')" title="文件">
      <i class="bi bi-folder"></i>
    </div>
    <div class="icon-btn" :class="{ active: active === 'git' }" @click="$emit('panel-change','git')" title="Git">
      <i class="bi bi-git"></i>
      <span v-if="changedCount > 0" class="badge">{{ changedCount }}</span>
    </div>
    <div class="icon-btn" title="搜索">
      <i class="bi bi-search"></i>
    </div>
    <div class="icon-btn" @click="$emit('panel-change','settings')" title="设置">
      <i class="bi bi-gear"></i>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useEditorStore } from '@/stores/editor'

const props = defineProps({ active: String })
const emit = defineEmits(['panel-change'])
const editorStore = useEditorStore()

const changedCount = computed(() => editorStore.changedFiles?.length || 0)
</script>
