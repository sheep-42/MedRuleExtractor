<!-- src/components/editors/Phase2Editor.vue -->
<template>
  <div class="editor-container">
    <div class="header">
      <h3>编辑器: {{ filePath }}</h3>
      <el-button v-if="isEditable" type="primary" :icon="DocumentChecked" @click="saveChanges" :loading="isSaving">
        保存更改
      </el-button>
    </div>

    <!-- 卡片列表 -->
    <div class="card-list">
      <el-card v-for="(item, index) in editableData" :key="item.id" class="box-card">
        <template #header>
          <div class="card-header">
            <span>原文内容</span>
            <div>
              <el-button 
                class="button remark-btn" 
                type="info" 
                text 
                :icon="ChatDotSquare" 
                :disabled="!isEditable" 
                @click="editItemRemark(item)"
              >
                {{ item.remark ? '查看/编辑备注' : '添加备注' }}
              </el-button>
              <el-button v-if="isEditable" class="button" type="danger" :icon="Delete" circle @click="removeItem(index)" />
            </div>
          </div>
        </template>
        <div class="card-content">
          <el-input
            v-model="item.originalText"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 8 }"
            class="original-text"
            :disabled="!isEditable"
          />
          
          <div class="form-item">
            <span class="form-label">审核项:</span>
            <el-select
              v-model="item.auditItem"
              placeholder="请选择审核项"
              filterable
              style="width: 100%;"
              :disabled="!isEditable"
              @change="handleAuditItemChange"
            >
              <el-option
                v-for="tag in medicalReviewOrder"
                :key="tag"
                :label="tag"
                :value="tag"
              />
            </el-select>
          </div>

          <div class="form-item">
            <span class="form-label">前提条件:</span>
            <div class="tags-section">
              <el-tag
                v-for="(condition, tagIndex) in item.conditions"
                :key="`${condition}-${tagIndex}`"
                class="mx-1"
                closable
                :disabled="!isEditable"
                @close="handleConditionClose(item, condition)"
              >
                {{ condition }}
              </el-tag>
              <el-select
                v-if="isEditable"
                class="tag-adder-button"
                size="small"
                placeholder="+ 添加条件"
                @change="(newCondition: string) => handleConditionAdd(item, newCondition)"
                :model-value="''"
              >
                <el-option
                  v-for="preset in presetConditions"
                  :key="preset"
                  :label="preset"
                  :value="preset"
                  :disabled="item.conditions.includes(preset)"
                />
              </el-select>
            </div>
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
            <el-input v-model="newItem.originalText" type="textarea" :rows="5" />
          </el-form-item>
          <el-form-item label="审核项">
            <el-select v-model="newItem.auditItem" filterable placeholder="请选择审核项" style="width: 100%;">
              <el-option
                v-for="tag in medicalReviewOrder"
                :key="tag"
                :label="tag"
                :value="tag"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="前提条件">
            <el-select v-model="newItem.conditions" multiple filterable placeholder="请选择前提条件" style="width: 100%;">
              <el-option
                v-for="preset in presetConditions"
                :key="preset"
                :label="preset"
                :value="preset"
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
import { ref, watch, reactive } from 'vue';
import { previewFile, saveFile, logEdit } from '../../api';
import { ElMessage, ElMessageBox } from 'element-plus';
import { DocumentChecked, Delete, ChatDotSquare } from '@element-plus/icons-vue';

// 定义常量替代魔术字符串
const ORIGINAL_TEXT_KEY = '原文内容';
const AUDIT_ITEM_KEY = '审核项';
const CONDITIONS_KEY = '前提条件';

// 定义 UI 内部使用的数据结构
interface EditableItem {
  id: number;
  originalText: string;
  auditItem: string;
  conditions: string[];
  remark?: string;
}

const props = defineProps<{
  filePath: string | undefined;
  isEditable: boolean;
}>();

// 响应式变量
const isLoading = ref(false);
const isSaving = ref(false);
const error = ref('');
const originalData = ref<EditableItem[]>([]);
const editableData = ref<EditableItem[]>([]);
let idCounter = 0;

// 引入医学审核顺序
const medicalReviewOrder = [
  "适应症", "禁忌症", "用法用量-单次剂量", "用法用量-单日剂量", "用法用量-给药频次",
  "用法用量-允许的给药途径", "用法用量-禁止的给药途径", "用法用量-药品总量", "用法用量-疗程",
  "特殊人群-年龄", "特殊人群-性别", "特殊人群-肾功能", "特殊人群-肝功能", "特殊人群-哺乳", "特殊人群-妊娠",
  "相互作用", "不良反应", "过敏", "浓度", "浓度体积", "浓度药品关联", "配伍禁忌"
];

// 预设前提条件列表
const presetConditions = [
  '年龄', '性别', '体重', '体表面积', '孕周', '妊娠哺乳状态', '诊断', 
  '频次', '检验值', '病情', '医嘱类型', '用药目的', '药品', '剂型', 
  '单次剂量', '给药途径', '联合用药'
];

// 添加新条目的表单数据
const newItem = reactive({
  originalText: '',
  auditItem: '',
  conditions: [] as string[],
});

// 提炼排序逻辑为独立函数
function compareItemsByMedicalOrder(a: EditableItem, b: EditableItem): number {
  const itemA = a.auditItem;
  const itemB = b.auditItem;
  const indexA = medicalReviewOrder.indexOf(itemA);
  const indexB = medicalReviewOrder.indexOf(itemB);

  if (indexA === -1 && indexB === -1) return itemA.localeCompare(itemB);
  if (indexA === -1) return 1;
  if (indexB === -1) return -1;
  return indexA - indexB;
}

function editItemRemark(item: EditableItem) {
  ElMessageBox.prompt('请输入针对此条内容的备注信息：', '编辑备注', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    inputType: 'textarea',
    inputValue: item.remark || '',
  })
  .then(({ value }) => {
    item.remark = value || undefined;
    ElMessage.success('备注已更新！');
  })
  .catch(() => {
    ElMessage.info('已取消编辑备注。');
  });
}

// 加载文件数据并排序
async function loadFile() {
  if (!props.filePath) return;
  isLoading.value = true;
  error.value = '';
  idCounter = 0;
  try {
    const rawData: { [ORIGINAL_TEXT_KEY]: string; [AUDIT_ITEM_KEY]: string; [CONDITIONS_KEY]: string[] }[] = await previewFile(props.filePath);

    const structuredData: EditableItem[] = rawData.map(item => ({
      id: idCounter++,
      originalText: item[ORIGINAL_TEXT_KEY],
      auditItem: item[AUDIT_ITEM_KEY],
      conditions: item[CONDITIONS_KEY] || [],
    }));
    
    // 加载后立即排序
    structuredData.sort(compareItemsByMedicalOrder);
    
    originalData.value = JSON.parse(JSON.stringify(structuredData));
    editableData.value = JSON.parse(JSON.stringify(structuredData));

  } catch (e: any) {
    error.value = `加载文件失败: ${e.message}`;
  } finally {
    isLoading.value = false;
  }
}

// 当审核项改变时，重新排序
function handleAuditItemChange() {
  editableData.value.sort(compareItemsByMedicalOrder);
}

function handleConditionClose(item: EditableItem, conditionToRemove: string) {
  item.conditions = item.conditions.filter(cond => cond !== conditionToRemove);
}

function handleConditionAdd(item: EditableItem, newCondition: string) {
  if (newCondition && !item.conditions.includes(newCondition)) {
    item.conditions.push(newCondition);
  }
}

function removeItem(index: number) {
  ElMessageBox.confirm('确定要删除这个条目吗？', '警告', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(() => {
    editableData.value.splice(index, 1);
    ElMessage.success('条目已删除');
  });
}

// 添加新条目并重新排序
function addNewItem() {
  if (!newItem.originalText.trim() || !newItem.auditItem.trim()) {
    ElMessage.warning('原文内容和审核项不能为空！');
    return;
  }
  editableData.value.push({
    id: idCounter++,
    originalText: newItem.originalText,
    auditItem: newItem.auditItem,
    conditions: [...newItem.conditions],
  });

  // 添加后重新排序
  editableData.value.sort(compareItemsByMedicalOrder);

  newItem.originalText = '';
  newItem.auditItem = '';
  newItem.conditions = [];
  ElMessage.success('新条目已添加并排序！');
}

// 保存更改
async function saveChanges() {
  if (!props.filePath || !props.isEditable) return;
  isSaving.value = true;
  try {
    const dataToSave = editableData.value.map(item => ({
      [ORIGINAL_TEXT_KEY]: item.originalText,
      [AUDIT_ITEM_KEY]: item.auditItem,
      [CONDITIONS_KEY]: item.conditions,
    }));

    const diff = {
      before: originalData.value,
      after: JSON.parse(JSON.stringify(editableData.value)),
    };
    
    await Promise.all([
      saveFile(props.filePath, dataToSave),
      logEdit(props.filePath, diff)
    ]);

    ElMessage.success('文件保存成功，修改已记录！');
    await loadFile();
  } catch (e: any) {
    ElMessage.error(`操作失败: ${e.message}`);
  } finally {
    isSaving.value = false;
  }
}

watch(() => props.filePath, loadFile, { immediate: true });
</script>

<style scoped>
.editor-container { height: 100%; display: flex; flex-direction: column; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-shrink: 0; }
.card-list { flex-grow: 1; overflow-y: auto; padding: 5px; background-color: #f9fafb; }
.box-card { margin-bottom: 15px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-header > div {
  display: flex;
  align-items: center;
  gap: 10px;
}
.remark-btn {
  padding-left: 8px;
  padding-right: 8px;
}
.original-text { margin-bottom: 15px; }
.form-item {
  display: flex;
  align-items: flex-start;
  margin-bottom: 10px;
}
.form-label {
  font-size: 14px;
  color: #606266;
  width: 80px;
  flex-shrink: 0;
  padding-top: 8px;
}
.tags-section {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  flex-grow: 1;
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