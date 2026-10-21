<!-- src/layouts/DefaultLayout.vue -->
<template>
  <el-container class="main-layout">
    <!-- Resizable 组件包裹左侧栏 -->
    <Resizable
      :active="['r']"
      :min-width="minLeftWidth"
      :max-width="maxLeftWidth"
      @resize:move="handleResize"
      @resize:end="handleResize"
      class="resizable-aside"
      :style="{ width: leftWidth + 'px' }"
    >
      <!-- el-aside 的宽度设为 100% 以填充 Resizable 容器 -->
      <el-aside width="100%">
        <slot name="left"></slot>
      </el-aside>
    </Resizable>

    <!-- 右侧部分（中间 + 右栏） -->
    <el-container class="right-container">
      <el-main>
        <slot name="main"></slot>
      </el-main>
      
      <!-- 可收缩的右侧栏 -->
      <el-aside :width="rightAsideWidth" class="right-collapsible-aside">
        <div class="aside-content-wrapper">
          <slot name="right"></slot>
        </div>
        <!-- 收缩/展开触发器 -->
        <div class="collapse-trigger" @click="toggleRightAside">
          <el-icon v-if="isRightAsideCollapsed"><ArrowLeftBold /></el-icon>
          <el-icon v-else><ArrowRightBold /></el-icon>
        </div>
      </el-aside>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import Resizable from 'vue-resizable';
import { ArrowLeftBold, ArrowRightBold } from '@element-plus/icons-vue';

// --- 需求1: 左右拖拽 ---
const leftWidth = ref(window.innerWidth * 0.15); // 初始宽度为 15%
const minLeftWidth = ref(window.innerWidth * 0.10);
const maxLeftWidth = ref(window.innerWidth * 0.25);

function handleResize(event: { width: number }) {
  leftWidth.value = event.width;
}

function updateWidths() {
  const screenWidth = window.innerWidth;
  minLeftWidth.value = screenWidth * 0.10; // 最小 10%
  maxLeftWidth.value = screenWidth * 0.25; // 最大 25%

  if (leftWidth.value < minLeftWidth.value) {
    leftWidth.value = minLeftWidth.value;
  }
  if (leftWidth.value > maxLeftWidth.value) {
    leftWidth.value = maxLeftWidth.value;
  }
}

// --- 需求2: 右侧收缩 ---
const isRightAsideCollapsed = ref(false);
const rightAsideWidth = computed(() => {
  return isRightAsideCollapsed.value ? '0px' : '35%';
});

function toggleRightAside() {
  isRightAsideCollapsed.value = !isRightAsideCollapsed.value;
}

onMounted(() => {
  updateWidths(); // 初始化宽度限制
  window.addEventListener('resize', updateWidths);
});

onUnmounted(() => {
  window.removeEventListener('resize', updateWidths);
});
</script>

<style>
/* --- 布局核心修复 --- */
.main-layout {
  height: 100vh;
  overflow: hidden; /* 防止布局抖动 */
}

.resizable-aside {
  position: relative;
  /* 关键修复：阻止 flex item 被压缩或拉伸，让其宽度严格由 style.width 控制 */
  flex-shrink: 0;
  flex-grow: 0;
}

.right-container {
  /* 关键修复：让右侧容器占据所有剩余空间 */
  flex-grow: 1;
  width: 0; /* flex 布局技巧，与 flex-grow: 1 配合使用 */
}

/* --- 拖拽条样式优化 --- */
.resizable-aside .resizable-r {
  display: block;
  position: absolute;
  z-index: 10;
  right: -5px;
  top: 0;
  width: 10px;
  height: 100%;
  cursor: col-resize;
}
/* 添加一个伪元素作为可见的拖拽线 */
.resizable-aside .resizable-r::after {
  content: '';
  position: absolute;
  top: 0;
  left: 4px;
  width: 2px;
  height: 100%;
  background-color: #dcdfe6; /* 默认可见的细线 */
  transition: background-color 0.3s;
}
.resizable-aside .resizable-r:hover::after {
  background-color: var(--el-color-primary); /* 悬浮时变色 */
}


/* --- 侧边栏通用样式 --- */
.main-layout .el-aside {
  background-color: #f5f7fa;
  padding: 10px;
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
}

.el-main {
  padding: 10px;
}

/* --- 右侧收缩栏样式 (基本不变) --- */
.right-collapsible-aside {
  position: relative;
  transition: width 0.3s ease;
  overflow: hidden;
  border-left: 1px solid #e0e0e0;
}

.aside-content-wrapper {
  width: 100%;
  height: 100%;
}

.collapse-trigger {
  position: absolute;
  left: -1px;
  top: 50%;
  transform: translateY(-50%);
  width: 16px;
  height: 60px;
  background-color: #e9eef3;
  border: 1px solid #dcdfe6;
  border-right: none;
  border-radius: 8px 0 0 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 10;
}
.collapse-trigger:hover {
  background-color: #d9e2ec;
}

.right-collapsible-aside[style*="width: 0px;"] .collapse-trigger {
  left: 0;
}
</style>