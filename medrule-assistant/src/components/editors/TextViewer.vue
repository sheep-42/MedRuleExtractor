<!-- src/components/editors/TextViewer.vue -->
<template>
  <div class="text-viewer">
    <h3>文件预览: {{ filePath }}</h3>
    <div class="content-wrapper">
      <pre v-if="content">{{ content }}</pre>
      <p v-else-if="error">{{ error }}</p>
      <p v-else>加载中...</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { previewFile } from '../../api'

const props = defineProps<{
  filePath: string | undefined
}>()

const content = ref<string>('')
const error = ref<string>('')

async function loadFile() {
  if (!props.filePath) return
  error.value = ''
  content.value = ''
  try {
    // 后端返回的是 { "content": "...", "type": "..." }
    const response = await previewFile(props.filePath)
    content.value = response.content
  } catch (e: any) {
    error.value = `加载文件失败: ${e.message}`
  }
}

watch(() => props.filePath, loadFile)
onMounted(loadFile)
</script>

<style scoped>
.text-viewer {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.content-wrapper {
  flex-grow: 1;
  overflow: auto;
  border: 1px solid #ddd;
  padding: 10px;
  background-color: #f9f9f9;
}
pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  margin: 0;
}
</style>