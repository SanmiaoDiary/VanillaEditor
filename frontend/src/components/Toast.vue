<template>
  <div class="ve-toast">
    <div v-for="t in toasts" :key="t.id" class="toast-item" :class="t.type">
      <i :class="t.type === 'success' ? 'bi bi-check-circle' : t.type === 'error' ? 'bi bi-exclamation-circle' : 'bi bi-info-circle'"></i>
      {{ t.msg }}
      <i class="bi bi-x" style="margin-left:auto;cursor:pointer" @click="$emit('dismiss',t.id)"></i>
    </div>
  </div>
</template>

<script setup>
defineProps({ toasts: Array })
defineEmits(['dismiss'])
</script>
