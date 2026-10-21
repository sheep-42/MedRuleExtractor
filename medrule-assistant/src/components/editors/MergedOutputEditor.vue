<!-- src/components/editors/MergedOutputEditor.vue -->
<template>
  <div class="editor-container">
    <div class="header">
      <h3>编辑器: {{ filePath }}</h3>
      <el-button type="primary" :icon="DocumentChecked" v-if="isEditable" @click="saveChanges" :loading="isSaving">
        保存更改
      </el-button>
    </div>

    <!-- 卡片列表 -->
    <div class="card-list">
      <el-card v-for="(item, index) in editableData" :key="index" class="box-card">
        <template #header>
          <div class="card-header">
            <span>原文内容</span>
            <el-button v-if="isEditable" class="button" type="danger" :icon="Delete" circle @click="removeItem(index)" />
          </div>
        </template>
        <div class="card-content">
          <el-input
            v-model="item['原文内容']"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 10 }"
            class="original-text"
            readonly
          />
          <div class="tags-section">
            <p class="tags-label">标签预测:</p>
            <el-tag
              v-for="tag in item['标签预测']"
              :key="tag"
              class="mx-1"
            >
              {{ tag }}
            </el-tag>
            <!-- 添加新标签的下拉选择器 -->
            <el-select
              v-if="isEditable && !item.isAddingTag"
              class="tag-adder-button"
              size="small"
              placeholder="+ 添加标签"
              @change="(newTag: string) => handleTagAdd(item, newTag)"
            >
              <el-option
                v-for="presetTag in presetTags"
                :key="presetTag"
                :label="presetTag"
                :value="presetTag"
                :disabled="item['标签预测'].includes(presetTag)"
              />
            </el-select>
          </div>
        </div>
      </el-card>
      
      <!-- 添加新条目的卡片 -->
      <el-card class="add-new-card" v-if="isEditable">
        <template #header>
          <span>添加新条目</span>
        </template>
        <el-form :model="newItem" label-position="top">
          <el-form-item label="原文内容">
            <el-input v-model="newItem.originalText" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="标签预测">
            <el-select v-model="newItem.tags" multiple placeholder="请选择标签" style="width: 100%;">
              <el-option
                v-for="tag in presetTags"
                :key="tag"
                :label="tag"
                :value="tag"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="success" @click="addNewItem">添加到列表</el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </div>

    <div v-if="error" class="error-message">{{ error }}</div>
    <div v-if="isLoading && !error" class="loading-message">加载中...</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, reactive } from 'vue';
import { previewFile, saveFile } from '../../api';
import { ElMessage, ElMessageBox } from 'element-plus';
import { DocumentChecked, Delete } from '@element-plus/icons-vue';

// 定义数据结构类型
interface DataItem {
  '段编号'?: string; // 设为可选，因为我们要忽略它
  '原文内容': string;
  '标签预测': string[];
  // 辅助 UI 状态
  isAddingTag?: boolean;
}

const props = defineProps<{
  filePath: string | undefined;
  isEditable: boolean;
}>();

const isLoading = ref(false);
const isSaving = ref(false);
const error = ref('');
const editableData = ref<DataItem[]>([]);

// 预设标签列表
const presetTags = [
  '不良反应', '禁忌症', '过敏', '特殊人群-年龄', '特殊人群-性别', 
  '特殊人群-肾功能', '特殊人群-肝功能', '特殊人群-哺乳', '特殊人群-妊娠', 
  '浓度', '浓度体积', '浓度药品关联', '相互作用', '配伍禁忌', '适应症', 
  '用法用量-单次剂量', '用法用量-单日剂量', '用法用量-给药频次', 
  '用法用量-允许的给药途径', '用法用量-禁止的给药途径', 
  '用法用量-药品总量', '用法用量-疗程'
];

// 添加新条目的表单数据
const newItem = reactive({
  originalText: '',
  tags: [] as string[],
});

// 加载文件数据
async function loadFile() {
  if (!props.filePath) return;
  isLoading.value = true;
  error.value = '';
  try {
    const data = await previewFile(props.filePath);
    // 过滤掉 "段编号" key，并初始化 UI 状态
    editableData.value = data.map((item: any) => ({
      '原文内容': item['原文内容'],
      '标签预测': item['标签预测'] || [],
      isAddingTag: false,
    }));
  } catch (e: any) {
    error.value = `加载文件失败: ${e.message}`;
  } finally {
    isLoading.value = false;
  }
}

// 标签操作
function handleTagClose(item: DataItem, tagToRemove: string) {
  item['标签预测'] = item['标签预测'].filter(tag => tag !== tagToRemove);
}

function handleTagAdd(item: DataItem, newTag: string) {
  if (newTag && !item['标签预测'].includes(newTag)) {
    item['标签预测'].push(newTag);
  }
  // 重置下拉框，以便下次可以再次点击
  // (El-Select v-model 绑定在外部，所以这里不需要手动重置)
}

// 列表项操作
function removeItem(index: number) {
  ElMessageBox.confirm('确定要删除这个条目吗？', '警告', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(() => {
    editableData.value.splice(index, 1);
    ElMessage.success('条目已删除');
  }).catch(() => {
    // 用户取消
  });
}

function addNewItem() {
  if (!newItem.originalText.trim()) {
    ElMessage.warning('原文内容不能为空！');
    return;
  }
  editableData.value.push({
    '原文内容': newItem.originalText,
    '标签预测': [...newItem.tags],
  });
  // 清空表单
  newItem.originalText = '';
  newItem.tags = [];
  ElMessage.success('新条目已添加到列表末尾！');
}

// 保存更改
async function saveChanges() {
  if (!props.filePath) return;
  if (!props.isEditable) {
    ElMessage.warning('此文件为只读模式，不可保存。');
    return;
  }
  isSaving.value = true;
  try {
    // 准备要保存的数据，移除 UI 辅助字段
    const dataToSave = editableData.value.map(item => ({
      '原文内容': item['原文内容'],
      '标签预测': item['标签预测'],
    }));
    await saveFile(props.filePath, dataToSave);
    ElMessage.success('文件保存成功！');
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e.message}`);
  } finally {
    isSaving.value = false;
  }
}

watch(() => props.filePath, loadFile, { immediate: true });
</script>

<style scoped>
.editor-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  flex-shrink: 0;
}
.card-list {
  flex-grow: 1;
  overflow-y: auto;
  padding: 5px;
  background-color: #f9fafb;
}
.box-card {
  margin-bottom: 15px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.original-text {
  margin-bottom: 15px;
}
.tags-section {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.tags-label {
  font-size: 14px;
  color: #606266;
  margin: 0;
}
.tag-adder-button {
  width: 120px;
}
.add-new-card {
  border: 2px dashed #dcdfe6;
}
.error-message, .loading-message {
  text-align: center;
  padding: 20px;
  font-size: 1.2em;
}
</style>