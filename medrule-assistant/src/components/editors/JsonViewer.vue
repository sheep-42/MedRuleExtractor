<!-- src/components/editors/JsonViewer.vue -->
<template>
    <div class="json-viewer">
        <h3>文件预览: {{ filePath }}</h3>
        <pre v-if="content">{{ formattedContent }}</pre>
        <p v-else-if="error">{{ error }}</p>
        <p v-else>加载中...</p>
    </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue'
import { previewFile } from '../../api'

const props = defineProps<{
    filePath: string | undefined
}>()

const content = ref<any>(null)
const error = ref<string>('')

const formattedContent = computed(() => {
    return JSON.stringify(content.value, null, 2)
})

async function loadFile() {
    if (!props.filePath) { // 这个检查很重要
        content.value = null;
        error.value = '';
        return;
    }
    try {
        content.value = await previewFile(props.filePath)
    } catch (e: any) {
        error.value = `加载文件失败: ${e.message}`
    }
}

// 监听 filePath 变化，重新加载文件
watch(() => props.filePath, loadFile)

// 组件挂载时加载一次
onMounted(loadFile)
</script>

<style scoped>
.json-viewer {
    height: 100%;
}

pre {
    background-color: #f9f9f9;
    border: 1px solid #ddd;
    padding: 10px;
    white-space: pre-wrap;
    word-wrap: break-word;
    height: calc(100% - 60px);
    overflow-y: auto;
}
</style>