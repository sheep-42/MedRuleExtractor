<!-- src/components/editors/Phase1Editor.vue -->
<template>
  <div class="phase1-editor">
    <h3>Phase 1 编辑器 (占位符)</h3>
    <p v-if="filePath">正在编辑: {{ filePath }}</p>
    <p v-else>没有选择文件。</p>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  filePath: string | undefined;
}>();

// 未来的编辑逻辑会在这里
</script>

<style scoped>
.phase1-editor {
  padding: 10px;
  border: 1px solid #eee;
  height: 100%;
}
</style>