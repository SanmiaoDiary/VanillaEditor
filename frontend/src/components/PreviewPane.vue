<template>
  <div class="preview-pane" v-html="html"></div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({ content: String })
const html = computed(() => marked.parse(props.content || ''))
</script>
