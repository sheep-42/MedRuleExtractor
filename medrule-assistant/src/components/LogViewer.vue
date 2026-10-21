<!-- src/components/LogViewer.vue -->
<template>
  <div class="executor-container">
    <!-- 流程执行器表单 -->
    <div class="executor-form">
      <div class="form-header">
        <h3>流程执行器</h3>
        <el-button @click="executeScript" type="success" :icon="VideoPlay" :loading="isExecuting">
          执行
        </el-button>
      </div>

      <el-form :model="formState" label-position="top" class="form-body">
        <el-form-item label="选择脚本">
          <el-select v-model="selectedScriptPath" placeholder="请选择要执行的脚本" style="width: 100%;">
            <el-option v-for="script in availableScripts" :key="script.path" :label="script.name" :value="script.path">
              <span style="float: left">{{ script.name }}</span>
              <span style="float: right; color: var(--el-text-color-secondary); font-size: 13px;">
                {{ script.path }}
              </span>
            </el-option>
          </el-select>
        </el-form-item>

        <!-- 1. 新增：快捷设置按钮 -->
        <div v-if="currentScript?.path === 'run_pipeline.py'" class="shortcut-buttons">
          <el-tooltip content="运行 Phase 1.0 到 1.3，生成可编辑的 '...labels_validated.json'" placement="top">
            <el-button @click="setPipelineStage('phase1.0', 'phase1.3')">运行第一阶段</el-button>
          </el-tooltip>
          <el-tooltip content="运行 Phase 2.0 到 2.1，生成可编辑的 '...rules_validated.json'" placement="top">
            <el-button @click="setPipelineStage('phase2.0', 'phase2.1')">运行第二阶段</el-button>
          </el-tooltip>
          <el-tooltip content="运行 Phase 3.0 到 4.0，生成可编辑的 '...final_normalized.json'" placement="top">
            <el-button @click="setPipelineStage('phase3.0', 'phase4.0')">运行第三/四阶段</el-button>
          </el-tooltip>
        </div>

        <!-- 动态生成的参数输入框 -->
        <div v-if="currentScript">
          <p class="script-description">{{ currentScript.description }}</p>
          <el-form-item v-for="arg in currentScript.args" :key="arg.name" :label="arg.label" :required="arg.required">
            <el-input v-if="arg.type === 'string' || arg.type === 'number'" v-model="formState[arg.name]"
              :placeholder="arg.defaultValue ? `例如: ${arg.defaultValue}` : ''" />
            <!-- TODO: 可以为 boolean 类型的参数添加 el-switch -->
          </el-form-item>
        </div>
      </el-form>
    </div>

    <!-- 日志区域 -->
    <div class="log-viewer-container">
      <div class="header">
        <h4>实时日志</h4>
        <div class="actions">
          <el-button @click="handleConnect" :disabled="isConnected" type="primary" size="small">连接</el-button>
          <el-button @click="handleClearLogs" type="danger" size="small">清空日志</el-button>
        </div>
      </div>
      <div class="log-area" ref="logAreaRef">
        <div v-for="log in loggerStore.logs" :key="log.id" :class="['log-entry', getLogClass(log.type)]">
          <span class="timestamp">[{{ log.timestamp }}]</span>
          <span class="type">[{{ log.type }}]</span>
          <span class="message">{{ log.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch, computed, reactive } from 'vue';
import { ElMessage } from 'element-plus';
import { VideoPlay } from '@element-plus/icons-vue';
import { useLoggerStore } from '../store/logger';
import wsService from '../services/websocket';
import { availableScripts } from './script.config';
import type { ScriptConfig } from './script.config';

const loggerStore = useLoggerStore();
const logAreaRef = ref<HTMLElement | null>(null);

// --- 表单状态 ---
const selectedScriptPath = ref<string>(availableScripts[0]?.path || '');
const formState = reactive<Record<string, any>>({});
const isExecuting = ref(false);

// 当前选中的脚本配置
const currentScript = computed<ScriptConfig | undefined>(() => {
  return availableScripts.find(s => s.path === selectedScriptPath.value);
});

// --- 提取自动生成目录名的逻辑为一个可复用的函数 ---
function generateOutputDirName(inputPath: string): string {
  // 从路径中提取文件名，并移除 .md 后缀
  const drugName = inputPath.split('/').pop()?.split('\\').pop()?.replace(/\.md$/i, '') || 'output';
  return `${drugName}`;
}

// 快捷设置函数
function setPipelineStage(start: string, end: string) {
  formState['--start-from'] = start;
  formState['--end-at'] = end;
  
  // 自动填充结果目录名
  if (!formState['--output-dir-name']) {
    formState['--output-dir-name'] = generateOutputDirName(formState['--input_file'] || '请输入药物名');
  }

  ElMessage.info({
    message: `已设置运行阶段：从 ${start} 到 ${end}。请确认输入文件和结果目录名后点击执行。`,
    duration: 4000,
  });
}

// 监听脚本选择变化，重置表单
watch(selectedScriptPath, (newPath, oldPath) => {
  if (newPath !== oldPath) {
    // 清空旧的表单值
    Object.keys(formState).forEach(key => delete formState[key]);
    // 设置新脚本的默认值
    const script = availableScripts.find(s => s.path === newPath);
    if (script) {
      script.args.forEach(arg => {
        if (arg.defaultValue) {
          formState[arg.name] = arg.defaultValue;
        }
      });
    }
  }
}, { immediate: true });

// --- 监听输入文件路径的变化 ---
watch(
  () => formState['--input_file'],
  (newInputPath, oldInputPath) => {
    // 确保 newPath 存在且与 oldPath 不同，避免不必要的更新
    if (newInputPath && newInputPath !== oldInputPath) {
      // 自动填充结果目录名
      formState['--output-dir-name'] = generateOutputDirName(newInputPath);
    }
  }
);

// --- 执行脚本 ---
function executeScript() {
  if (!currentScript.value) {
    ElMessage.error('请先选择一个脚本！');
    return;
  }

  const args: string[] = [];
  // 校验并构建参数列表
  for (const argDef of currentScript.value.args) {
    const value = formState[argDef.name];
    if (argDef.required && (value === undefined || value === '')) {
      ElMessage.error(`参数 "${argDef.label}" 是必需的！`);
      return;
    }
    if (value !== undefined && value !== '') {
      args.push(argDef.name);
      args.push(String(value));
    }
  }

  const request = {
    script_path: currentScript.value.path,
    args: args,
  };

  loggerStore.addLog({ type: 'SYSTEM', message: `准备执行脚本: ${request.script_path}` });
  wsService.sendMessage(request);
  isExecuting.value = true;
}

// 监听日志，判断任务是否结束
watch(() => loggerStore.logs, (newLogs) => {
  if (!isExecuting.value) return; // 如果不是在执行中，就不用判断了

  const lastLog = newLogs[newLogs.length - 1];
  if (lastLog) {
    const type = lastLog.type.toUpperCase();
    // 任何表示任务结束的状态都应该重置按钮
    if (type === 'SUCCESS' || type === 'FAILURE' || type.includes('ERROR')) {
      isExecuting.value = false;
    }
  }
}, { deep: true });

// --- 日志区域逻辑 (与之前相同) ---
watch(
  () => loggerStore.logs.length,
  async () => {
    await nextTick();
    if (logAreaRef.value) {
      logAreaRef.value.scrollTop = logAreaRef.value.scrollHeight;
    }
  }
);

function getLogClass(type: string): string {
  // ... (与之前相同)
  switch (type.toUpperCase()) {
    case 'ERROR':
    case 'FATAL_ERROR':
    case 'FAILURE':
      return 'log-error';
    case 'SUCCESS':
      return 'log-success';
    case 'SYSTEM':
      return 'log-system';
    default:
      return 'log-info';
  }
}

function handleConnect() {
  wsService.connect();
}

function handleClearLogs() {
  loggerStore.clearLogs();
}

const isConnected = computed(() => {
  const lastLog = loggerStore.logs[loggerStore.logs.length - 1];
  return lastLog?.message.includes('连接成功');
});

onMounted(() => {
  handleConnect();
});
</script>

<style scoped>
.executor-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.executor-form {
  flex-shrink: 0;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 15px;
  margin-bottom: 10px;
}

.form-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.form-header h3 {
  margin: 0;
}

.form-body .el-form-item {
  margin-bottom: 12px;
}

.shortcut-buttons {
  margin-bottom: 15px;
  padding-bottom: 15px;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  gap: 10px;
}

.script-description {
  font-size: 13px;
  color: #909399;
  margin-top: -5px;
  margin-bottom: 10px;
}

.log-viewer-container {
  display: flex;
  flex-direction: column;
  flex-grow: 1;
  /* 占据剩余空间 */
  background-color: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Courier New', Courier, monospace;
  font-size: 14px;
  border-radius: 4px;
  padding: 10px;
  min-height: 200px;
  /* 保证日志区域有最小高度 */
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  flex-shrink: 0;
}

.header h4 {
  margin: 0;
  color: #fff;
}

.log-area {
  flex-grow: 1;
  overflow-y: auto;
  border: 1px solid #333;
  padding: 8px;
  border-radius: 4px;
}

/* 日志条目样式 (与之前相同) */
.log-entry {
  margin-bottom: 4px;
  white-space: pre-wrap;
  word-break: break-all;
}

.timestamp {
  color: #888;
  margin-right: 8px;
}

.type {
  font-weight: bold;
  margin-right: 8px;
}

.log-info .type {
  color: #9cdcfe;
}

.log-error .type {
  color: #f44747;
}

.log-success .type {
  color: #4ec9b0;
}

.log-system .type {
  color: #ce9178;
}

.message {
  color: #d4d4d4;
}
</style>