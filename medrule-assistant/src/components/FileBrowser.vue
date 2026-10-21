<!-- src/components/FileBrowser.vue -->
<template>
  <div class="file-browser">
    <div class="header">
      <h3>文件浏览器</h3>
      <span>版本：2025-12-3</span>
      <el-tooltip content="手动刷新" placement="top">
        <el-button :icon="Refresh" circle size="small" @click="refreshTree" :loading="isRefreshing"></el-button>
      </el-tooltip>
    </div>
    <el-tree
      ref="treeRef"
      :props="treeProps"
      :load="loadNode"
      lazy
      node-key="path"
      @node-click="handleNodeClick"
      @node-expand="handleNodeExpand"
      @node-collapse="handleNodeCollapse"
    >
      <template #default="{ node, data }">
        <span class="custom-tree-node">
          <el-icon v-if="data.is_dir"><Folder /></el-icon>
          <el-icon v-else><Document /></el-icon>
          <span :class="getNodeClass(data)">{{ node.label }}</span>
        </span>
      </template>
    </el-tree>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue';
import { Refresh, Folder, Document } from '@element-plus/icons-vue';
import { browseDirectory } from '../api';
import type { FileNode } from '../types';
import type { ElTree } from 'element-plus';

// --- 定义可编辑文件列表 ---
const editableFiles = [
  'sections_merged_labels_validated.json',
  'conditions_rules_validated.json',
  'struct_final_normalized.json'
];

// --- 创建一个函数来返回动态的 class ---
function getNodeClass(data: FileNode): string {
  // 我们只关心文件，不关心目录
  if (data.is_dir) {
    return '';
  }
  
  // 从路径中提取文件名 (使用我们之前修复过的跨平台方法)
  const normalizedPath = data.path.replace(/\\/g, '/');
  const fileName = normalizedPath.split('/').pop()?.toLowerCase() || '';

  // 如果文件名在可编辑列表中，则返回 'editable-file' class
  if (editableFiles.includes(fileName)) {
    return 'editable-file';
  }

  return ''; // 否则不添加任何特殊 class
}

const emit = defineEmits(['file-selected']);

const treeRef = ref<InstanceType<typeof ElTree> | null>(null);
const isRefreshing = ref(false);
let pollingTimer: number | null = null;

const expandedKeys = ref<Set<string>>(new Set());

const treeProps = {
  label: 'name',
  children: 'children',
  isLeaf: (data: FileNode) => !data.is_dir,
};

// --- 核心修改：让 loadNode 负责级联展开 ---
const loadNode = async (node: any, resolve: (data: FileNode[]) => void) => {
  const path = node.level === 0 ? '.' : node.data.path;
  try {
    // 1. 正常加载子节点数据
    const files = await browseDirectory(path);
    resolve(files);

    // 2. 等待 DOM 更新，确保新节点已添加到树中
    await nextTick();

    // 3. 检查新加载的子节点中，是否有需要继续展开的
    for (const file of files) {
      if (expandedKeys.value.has(file.path)) {
        const childNode = treeRef.value?.getNode(file.path);
        // 如果节点存在且未展开，则程序化地展开它
        if (childNode && !childNode.expanded) {
          childNode.expand(); // 这会递归地再次触发 loadNode
        }
      }
    }
  } catch (error) {
    console.error(`Failed to load node ${path}:`, error);
    resolve([]);
  }
};

// --- 简化后的刷新逻辑 ---
function refreshTree() {
  if (!treeRef.value) return;
  isRefreshing.value = true;
  
  // expandedKeys 已经保存了所有需要展开的节点的状态
  // 我们只需要清空树，让它从根节点开始，利用我们“智能”的 loadNode 函数自动重建状态
  const root = treeRef.value.root;
  root.childNodes = []; // 清空所有节点
  root.loaded = false;   // 将根节点标记为未加载
  root.expand();       // 展开根节点，这将触发对根节点的 loadNode 调用
  
  isRefreshing.value = false;
}

// --- 定时器和事件处理 ---
onMounted(() => {
  pollingTimer = window.setInterval(refreshTree, 300000);
});

onUnmounted(() => {
  if (pollingTimer) {
    clearInterval(pollingTimer);
  }
});

function handleNodeClick(data: FileNode) {
  if (!data.is_dir) {
    emit('file-selected', data);
  }
}

function handleNodeExpand(data: FileNode) {
  if (data.is_dir) {
    expandedKeys.value.add(data.path);
  }
}

function handleNodeCollapse(data: FileNode) {
  if (data.is_dir) {
    expandedKeys.value.delete(data.path);
  }
}
</script>

<style scoped>
/* 样式部分保持不变 */
.file-browser { height: 100%; display: flex; flex-direction: column; }
.header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 10px; flex-shrink: 0; }
.header h3 { margin: 0; }
.el-tree { flex-grow: 1; overflow-y: auto; background-color: transparent; }
.custom-tree-node { display: flex; align-items: center; gap: 5px; }

/* --- 添加特殊文件的样式 --- */
/* 注意：这里需要使用 :deep() 选择器，因为 el-tree 的内部 DOM 结构是封装的 */
:deep(.editable-file) {
  color: #67C23A; /* Element Plus 的成功绿色 */
  font-weight: bold;
}

/* (可选) 添加一个 hover 效果，让交互更明显 */
:deep(.editable-file:hover) {
  color: #85ce61;
  text-decoration: underline;
}
</style>