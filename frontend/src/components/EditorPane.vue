<template>
  <div class="editor-pane" ref="editorRef">
    <textarea
      v-model="content"
      class="code-editor"
      spellcheck="false"
      @input="onInput"
    ></textarea>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useEditorStore } from '@/stores/editor'

const props = defineProps({ docId: String, filePath: String, content: String })
const emit = defineEmits(['change', 'save'])
const editorStore = useEditorStore()
const editorRef = ref(null)

const content = ref(props.content || '')

watch(() => props.content, val => {
  if (val !== content.value && document.activeElement !== editorRef.value) {
    content.value = val
  }
})

function onInput() {
  editorStore.content = content.value
  emit('change', content.value)
}
</script>

<style scoped>
.code-editor {
  flex: 1;
  width: 100%;
  background: var(--bg-primary);
  color: #d4d4d4;
  border: none;
  resize: none;
  outline: none;
  padding: 12px 16px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 14px;
  line-height: 1.6;
  tab-size: 2;
}
</style>
