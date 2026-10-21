<!-- src/components/editors/PdfViewer.vue -->
<template>
    <div class="pdf-viewer">
        <div class="header">
            <h3>PDF 预览: {{ filePath }}</h3>
            <div v-if="pdfDoc" class="controls">
                <el-button @click="prevPage" :disabled="pageNum <= 1" :icon="ArrowLeft" circle />
                <span>第 {{ pageNum }} / {{ numPages }} 页</span>
                <el-button @click="nextPage" :disabled="pageNum >= numPages" :icon="ArrowRight" circle />
            </div>
        </div>
        <div class="content-wrapper" ref="containerRef">
            <canvas ref="canvasRef"></canvas>
            <div v-if="isLoading" class="loading-overlay">加载中...</div>
            <div v-if="error" class="error-overlay">{{ error }}</div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, shallowRef } from 'vue';
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue';
import * as pdfjsLib from 'pdfjs-dist';

// --- 这是新的、正确的设置方式 ---
// 动态导入 .mjs worker 文件
// '?' + 'url' 是 Vite 的一个技巧，它会返回该文件的 URL 路径
import PdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
pdfjsLib.GlobalWorkerOptions.workerSrc = PdfjsWorker;

const props = defineProps<{
    filePath: string | undefined;
}>();

const canvasRef = ref<HTMLCanvasElement | null>(null);
const containerRef = ref<HTMLElement | null>(null);
const isLoading = ref(false);
const error = ref('');

const pdfDoc = shallowRef<any>(null); // 使用 shallowRef 而不是 ref

const pageNum = ref(1);
const numPages = ref(0);

async function loadPdf() {
    if (!props.filePath) return;

    isLoading.value = true;
    error.value = '';
    pdfDoc.value = null; // 赋值为 null 仍然会触发响应

    try {
        // PDF 文件需要以二进制形式加载
        // 我们需要修改后端 API 来支持返回二进制数据
        const url = `/api/download?path=${encodeURIComponent(props.filePath)}`;
        const loadingTask = pdfjsLib.getDocument(url);
        const pdf = await loadingTask.promise;

        // --- 3. 将原始的 pdf 对象赋值给 shallowRef 的 .value ---
        pdfDoc.value = pdf; // 这里的赋值操作是响应式的

        numPages.value = pdf.numPages;
        pageNum.value = 1;
        await renderPage(pageNum.value); // 注意这里加 await
    } catch (e: any) {
        console.error('PDF 加载失败:', e);
        error.value = `加载 PDF 失败: ${e.message}`;
    } finally {
        isLoading.value = false;
    }
}

async function renderPage(num: number) {
    // --- 4. 访问 .value 时，得到的是未经代理的原始 pdf 对象 ---
    if (!pdfDoc.value || !canvasRef.value || !containerRef.value) return;

    isLoading.value = true;
    try {
        // 现在 pdfDoc.value 是原始对象，调用 getPage 不会再报错
        const page = await pdfDoc.value.getPage(num);
        const viewport = page.getViewport({ scale: 1.5 });

        const canvas = canvasRef.value;
        const context = canvas.getContext('2d');
        if (!context) return;

        // 根据容器宽度调整缩放比例
        const scale = containerRef.value.clientWidth / viewport.width;
        const scaledViewport = page.getViewport({ scale });
        canvas.height = scaledViewport.height;
        canvas.width = scaledViewport.width;

        const renderContext = {
            canvas: canvas,
            canvasContext: context,
            viewport: scaledViewport,
        };
        await page.render(renderContext).promise;
    } catch (e: any) {
        console.error(`渲染第 ${num} 页失败:`, e);
        error.value = `渲染第 ${num} 页失败: ${e.message}`;
    } finally {
        isLoading.value = false;
    }
}

function prevPage() {
    if (pageNum.value > 1) {
        pageNum.value--;
        renderPage(pageNum.value);
    }
}

function nextPage() {
    if (pageNum.value < numPages.value) {
        pageNum.value++;
        renderPage(pageNum.value);
    }
}

watch(() => props.filePath, loadPdf);
onMounted(loadPdf);
</script>

<style scoped>
.pdf-viewer {
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

.controls span {
    margin: 0 10px;
}

.content-wrapper {
    flex-grow: 1;
    overflow: auto;
    border: 1px solid #ddd;
    position: relative;
    text-align: center;
}

canvas {
    max-width: 100%;
}

.loading-overlay,
.error-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    justify-content: center;
    align-items: center;
    background: rgba(255, 255, 255, 0.8);
}

.error-overlay {
    color: red;
}
</style>