import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useEditorStore = defineStore('editor', () => {
  const activeDocId = ref('')
  const activeFilePath = ref('')
  const content = ref('')
  const fileSha = ref('')
  const history = ref([])
  const changedFiles = ref([])
  const gitBranch = ref('main')
  const unsaved = ref(false)

  const activeFile = computed(() => {
    if (!activeDocId.value || !activeFilePath.value) return null
    return { docId: activeDocId.value, path: activeFilePath.value }
  })

  function setActiveFile(docId, filePath, fileContent = '', sha = '') {
    activeDocId.value = docId
    activeFilePath.value = filePath
    content.value = fileContent
    fileSha.value = sha
    unsaved.value = false
  }

  function markUnsaved() {
    unsaved.value = true
  }

  function clearUnsaved() {
    unsaved.value = false
  }

  return {
    activeDocId, activeFilePath, content, fileSha,
    history, changedFiles, gitBranch, unsaved,
    activeFile, setActiveFile, markUnsaved, clearUnsaved
  }
})
