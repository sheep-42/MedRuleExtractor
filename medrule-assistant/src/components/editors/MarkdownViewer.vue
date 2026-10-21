<!-- src/components/editors/MarkdownViewer.vue -->
<template>
  <div class="markdown-viewer">
    <div class="header">
      <h3>Markdown 预览: {{ filePath }}</h3>
      <el-switch
        v-model="isRendered"
        active-text="渲染模式"
        inactive-text="源码模式"
      />
    </div>
    <div class="content-wrapper">
      <!-- 渲染模式 -->
      <div v-if="isRendered" v-html="renderedMarkdown" class="markdown-body"></div>
      <!-- 源码模式 -->
      <pre v-else>{{ markdownContent }}</pre>
      <p v-if="error">{{ error }}</p>
      <p v-if="!markdownContent && !error">加载中...</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue'
import { marked } from 'marked'
import { previewFile } from '../../api'

const props = defineProps<{
  filePath: string | undefined
}>()

const markdownContent = ref<string>('')
const error = ref<string>('')
const isRendered = ref(true) // 默认开启渲染模式

const renderedMarkdown = computed(() => {
  if (markdownContent.value) {
    return marked(markdownContent.value)
  }
  return ''
})

async function loadFile() {
  if (!props.filePath) return
  error.value = ''
  markdownContent.value = ''
  try {
    const response = await previewFile(props.filePath)
    markdownContent.value = response.content
  } catch (e: any) {
    error.value = `加载文件失败: ${e.message}`
  }
}

watch(() => props.filePath, loadFile)
onMounted(loadFile)
</script>

<style scoped>
.markdown-viewer {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.content-wrapper {
  flex-grow: 1;
  overflow: auto;
  border: 1px solid #ddd;
  padding: 15px;
}
pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  margin: 0;
}
/* 添加一些基本的 Markdown 样式 */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  border-bottom: 1px solid #eee;
  padding-bottom: 0.3em;
}
.markdown-body :deep(code) {
  background-color: #f0f0f0;
  padding: 2px 4px;
  border-radius: 4px;
}
.markdown-body :deep(pre) {
  background-color: #f6f8fa;
  padding: 16px;
  overflow: auto;
  border-radius: 6px;
}
</style>