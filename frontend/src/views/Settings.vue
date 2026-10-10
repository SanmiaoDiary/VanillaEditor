<template>
  <div style="padding:20px">
    <h4 style="color:var(--text-primary)">设置</h4>
    <div style="margin-top:16px">
      <label style="font-size:12px;color:var(--text-secondary)">字体大小</label>
      <select v-model="fontSize" class="form-select form-select-sm mt-1" style="background:var(--bg-secondary);color:var(--text-primary);border-color:var(--border);width:120px">
        <option value="12">12px</option>
        <option value="14">14px</option>
        <option value="16">16px</option>
        <option value="18">18px</option>
      </select>
    </div>
    <div style="margin-top:16px">
      <label style="font-size:12px;color:var(--text-secondary)">主题</label>
      <div class="btn-group mt-1" role="group">
        <button class="btn btn-secondary-git" :class="{ active: theme==='dark' }" @click="theme='dark'">暗色</button>
        <button class="btn btn-secondary-git" :class="{ active: theme==='light' }" @click="theme='light'">亮色</button>
      </div>
    </div>
    <div style="margin-top:24px;padding:12px;background:var(--bg-tertiary);border-radius:6px;font-size:12px;color:var(--text-secondary)">
      VanillaEditor v0.1.0<br>
      数据完全存储在本地，不上传任何第三方服务器
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
const fontSize = ref('14')
const theme = ref('dark')
</script>
