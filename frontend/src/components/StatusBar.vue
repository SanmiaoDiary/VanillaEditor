<template>
  <div class="status-bar">
    <span><i class="bi bi-git"></i> {{ branch }}</span>
    <span v-if="sha">{{ sha.slice(0, 7) }}</span>
    <span v-if="unsaved" style="color:#e2c08d">● 有未保存更改</span>
    <span class="right">VanillaEditor v0.1.0</span>
    <span class="right">{{ new Date().toLocaleTimeString() }}</span>
  </div>
</template>

<script setup>
defineProps({ branch: String, sha: String, unsaved: Boolean })
</script>
