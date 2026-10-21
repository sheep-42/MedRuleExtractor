<!-- src/App.vue -->
<template>
  <DefaultLayout>
    <template #left>
      <FileBrowser @file-selected="handleFileSelect" />
    </template>

    <template #main>
      <!-- 这里的 :is 会接收一个组件对象或 null -->
      <component 
        :is="activeEditor.component" 
        :file-path="selectedFile?.path"
        :is-editable="activeEditor.isEditable"
        v-if="activeEditor.component" 
      />
      <div v-else class="editor-placeholder">
        <p>请在左侧选择一个文件进行预览或编辑。</p>
      </div>
    </template>

    <template #right>
      <LogViewer />
    </template>
  </DefaultLayout>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import DefaultLayout from './layouts/DefaultLayout.vue'
import FileBrowser from './components/FileBrowser.vue'
import LogViewer from './components/LogViewer.vue'
import JsonViewer from './components/editors/JsonViewer.vue'
import Phase1Editor from './components/editors/Phase1Editor.vue'
import MergedOutputEditor from './components/editors/MergedOutputEditor.vue';
import Phase1_3Editor from './components/editors/Phase1_3Editor.vue';
import Phase2Editor from './components/editors/Phase2Editor.vue';
import Phase3Editor from './components/editors/Phase3Editor.vue';
import TextViewer from './components/editors/TextViewer.vue'
import MarkdownViewer from './components/editors/MarkdownViewer.vue'
import PdfViewer from './components/editors/PdfViewer.vue'
import type { FileNode } from './types'

// 选中的文件
const selectedFile = ref<FileNode | null>(null)

// 定义可编辑的文件列表
const editableFiles = [
  'sections_merged_labels_validated.json',
  'conditions_rules_validated.json',
  'struct_final_normalized.json'
];

// 动态决定使用哪个编辑器组件
const activeEditor = computed(() => {
  if (!selectedFile.value) {
    return { component: null, isEditable: false };
  }
  
  const path = selectedFile.value.path;
  // 1. 标准化路径：使用正则表达式将所有的反斜杠 (\) 替换为正斜杠 (/)
  // 正则表达式 /\\/g 表示全局匹配(g) 反斜杠(\\) (需要用另一个反斜杠来转义)
  const normalizedPath = path.replace(/\\/g, '/');

  // 2. 现在可以安全地按照正斜杠 (/) 进行分割，并取出最后一部分
  const fileName = normalizedPath.split('/').pop()?.toLowerCase() || '';

  let component: any = null;

  // 决定使用哪个组件
  if (path.endsWith('.json')) {
    if (fileName === 'sections_merged_labels_validated.json') {
      component = Phase1_3Editor;
    } else if (fileName === 'conditions_rules_validated.json') {
      component = Phase2Editor;
    } else if (fileName === 'struct_final_normalized.json') {
      component = Phase3Editor;
    } else if (fileName.startsWith('conditions') && !fileName.endsWith('_logs.json')) {
      component = Phase2Editor; // 复用 Phase2Editor 进行预览
    } else if (fileName.startsWith('struct') && !fileName.endsWith('_logs.json')) {
      component = Phase3Editor; // 复用 Phase3Editor 进行预览
    } else if (fileName.startsWith('sections') && !fileName.endsWith('_logs.json')) {
      component = MergedOutputEditor; // 用 MergedOutputEditor 进行预览
    } else {
      component = JsonViewer;
    }
  } else if (path.endsWith('.pdf')) {
    component = PdfViewer;
  } else if (path.endsWith('.md')) {
    component = MarkdownViewer;
  } else if (path.endsWith('.txt')) {
    component = TextViewer;
  }
  
  // 决定是否可编辑
  const isEditable = editableFiles.includes(fileName);

  return { component, isEditable };
})

function handleFileSelect(file: FileNode) {
  selectedFile.value = file
  console.log('Selected file:', file.path)
}
</script>

<style scoped>
.editor-placeholder {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  color: #888;
  font-size: 1.2em;
  border: 2px dashed #ccc;
  border-radius: 8px;
  background-color: #f9f9f9;
}
</style>