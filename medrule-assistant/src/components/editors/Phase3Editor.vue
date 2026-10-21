<!-- src/components/editors/Phase3Editor.vue -->
<template>
  <div class="editor-container">
    <div class="header">
      <h3 class="header-title" :title="filePath">
        结构化数据编辑器: {{ filePath }}
      </h3>
      <div class="header-actions">
        <el-button 
          v-if="isEditable"
          type="success" 
          :icon="Download" 
          @click="exportToFile"
        >
          导出
        </el-button>
        <el-button 
          v-if="isEditable"
          type="primary" 
          :icon="DocumentChecked" 
          @click="saveChanges" 
          :loading="isSaving"
        >
          保存更改
        </el-button>
      </div>
    </div>

    <!-- 卡片列表 -->
    <div class="card-list">
      <el-card v-for="(item, itemIndex) in editableData" :key="item.id" class="box-card">
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
              <el-button 
                v-if="isEditable"
                class="button" 
                type="danger" 
                :icon="Delete" 
                circle 
                @click="removeItem(itemIndex)" 
              />
            </div>
          </div>
        </template>
        <!-- 多个原文内容 -->
        <div v-for="(text, textIndex) in item.originalTexts" :key="textIndex" class="original-text-item">
          <el-input :model-value="text" type="textarea" :autosize="{ minRows: 1 }" disabled />
        </div>

        <!-- 规则卡片 -->
        <div class="struct-list">
          <h4>规则:</h4>
          <el-card class="inner-card">
            <template #header>
              <div class="card-header inner-card-header">
                <span>规则设置</span>
              </div>
            </template>
            <div class="struct-item">
              <div class="form-row">
                <span class="form-label">等级:</span>
                <el-select v-model="item.ruleValue" :disabled="!isEditable" style="min-width: 220px;">
                  <el-option v-for="opt in ruleLevelOptions" :key="opt.value" :label="`${opt.label}（${opt.value}）`" :value="opt.value" />
                </el-select>
              </div>
            </div>
          </el-card>
        </div>

        <!-- 结构列表 -->
        <div class="struct-list">
          <h4>结构化信息:</h4>
          <el-card v-for="(struct, structIndex) in item.struct" :key="structIndex" class="inner-card">
            <template #header>
              <div class="card-header inner-card-header">
                <span>类别: {{ struct['类别'] }}</span>
                <el-button 
                  v-if="isEditable"
                  class="button" 
                  type="danger" 
                  plain 
                  :icon="Delete" 
                  circle
                  @click="removeStructItem(item, structIndex)" 
                />
              </div>
            </template>
            <div class="struct-item">
              <div class="form-row">
                <span class="form-label">类别:</span>
                <el-select v-model="struct['类别']" @change="() => handleCategoryChange(struct, item)" :disabled="!isEditable">
                  <el-option v-for="opt in categoryOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
              </div>
              <div class="form-row">
                <span class="form-label">表名:</span>
                <el-select v-model="struct['表名']" filterable :disabled="!isEditable" @change="() => handleTableNameChange(item)">
                  <el-option v-for="opt in tableMap[struct['类别']]" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
              </div>
              <div class="fields-section">
                <p class="fields-label">字段:</p>
                <div v-for="fieldKey in Object.keys(struct['字段'] || {})" :key="fieldKey" class="form-row field-row">
                  <span class="form-label field-key">{{ fieldKey }}:</span>
                  <el-input v-model="struct['字段'][fieldKey]" :disabled="!isEditable" />
                </div>
              </div>
            </div>
          </el-card>

          <!-- 新增结构项... -->
           <div v-if="isEditable" class="add-struct-form">
            <el-collapse-transition>
              <div v-if="item.isAddingStruct">
                <el-card shadow="never">
                  <h5>新增结构项</h5>
                  <div class="form-row">
                    <span class="form-label">类别:</span>
                    <el-select v-model="item.newStruct.category" @change="() => handleNewCategoryChange(item)">
                      <el-option v-for="opt in categoryOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                    </el-select>
                  </div>
                  <div class="form-row">
                    <span class="form-label">表名:</span>
                    <el-select v-model="item.newStruct.tableName" filterable>
                       <el-option v-for="opt in tableMap[item.newStruct.category]" :key="opt.value" :label="opt.label" :value="opt.value" />
                    </el-select>
                  </div>
                  <div class="fields-section">
                     <p class="fields-label">字段:</p>
                     <div v-for="(field, index) in item.newStruct.fields" :key="index" class="form-row field-row">
                        <el-input v-model="field.key" placeholder="字段名 (Key)" class="field-key-input"/>
                        <span style="margin: 0 5px;">:</span>
                        <el-input v-model="field.value" placeholder="字段值 (Value)"/>
                        <el-button :icon="Delete" text circle @click="() => item.newStruct.fields.splice(index, 1)" />
                     </div>
                     <el-button :icon="Plus" @click="() => item.newStruct.fields.push({key: '', value: ''})">添加字段</el-button>
                  </div>
                  <div class="form-actions">
                    <el-button @click="() => item.isAddingStruct = false">取消</el-button>
                    <el-button type="primary" @click="() => confirmAddStruct(item)">确认添加</el-button>
                  </div>
                </el-card>
              </div>
            </el-collapse-transition>
            <el-button v-if="!item.isAddingStruct" type="primary" plain @click="() => item.isAddingStruct = true">新增结构</el-button>
          </div>
        </div>
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
import { DocumentChecked, Delete, Plus, Download, ChatDotSquare } from '@element-plus/icons-vue';
import { categoryOptions, tableMap } from '../phase3.config';

// 引入医学审核顺序
const medicalReviewOrder = [
  "适应症", "禁忌症", "用法用量-单次剂量", "用法用量-单日剂量", "用法用量-给药频次",
  "用法用量-允许的给药途径", "用法用量-禁止的给药途径", "用法用量-药品总量", "用法用量-疗程",
  "特殊人群-年龄", "特殊人群-性别", "特殊人群-肾功能", "特殊人群-肝功能", "特殊人群-哺乳", "特殊人群-妊娠",
  "相互作用", "不良反应", "过敏", "浓度", "浓度体积", "浓度药品关联", "配伍禁忌"
];

// 定义数据结构
interface StructField { [key: string]: any; }
interface StructItem { '类别': string; '表名': string; '字段': StructField; }
interface EditableItem {
  id: number;
  originalTexts: string[];
  struct: StructItem[];
  ruleValue: number; // 1-监测, 2-提示, 3-警告, 4-拦截
  isAddingStruct: boolean;
  newStruct: {
    category: '审核项' | '前提条件';
    tableName: string;
    fields: { key: string; value: string }[];
  };
  remark?: string;
}

const props = defineProps<{ 
  filePath: string | undefined;
  isEditable: boolean;
}>();

const isLoading = ref(false);
const isSaving = ref(false);
const error = ref('');
const originalData = ref<EditableItem[]>([]);
const editableData = ref<EditableItem[]>([]);
let idCounter = 0;

// 规则映射（等级⇄名称）
const ruleLevelOptions = [
  { label: '拦截', value: 4 },
  { label: '警告', value: 3 },
  { label: '提示', value: 2 },
  { label: '监测', value: 1 },
];
function valueToLabel(v: number): string {
  const m = ruleLevelOptions.find(o => o.value === v);
  return m ? m.label : '警告';
}
function labelToValue(label: string): number | null {
  const m = ruleLevelOptions.find(o => o.label === label);
  return m ? m.value : null;
}
function parseRuleValueFromRaw(item: Record<string, any>): number {
  const rules = item['规则'];
  if (Array.isArray(rules) && rules.length > 0 && typeof rules[0] === 'object') {
    const r = rules[0];
    const v = typeof r['值'] === 'number' ? r['值'] : null;
    const l = typeof r['等级'] === 'string' ? r['等级'] : null;
    if (v && ruleLevelOptions.some(o => o.value === v)) return v;
    if (l) {
      const mapped = labelToValue(l);
      if (mapped) return mapped;
    }
  }
  // 默认：警告(3)
  return 3;
}

// 提炼排序逻辑
// 这个函数现在只比较审核项的表名
function compareItemsByMedicalOrder(a: EditableItem, b: EditableItem): number {
  // 找到第一个类别为“审核项”的结构
  const auditItemA = a.struct.find(s => s['类别'] === '审核项');
  const auditItemB = b.struct.find(s => s['类别'] === '审核项');

  // 如果某个条目没有审核项，则将其排在后面
  if (!auditItemA) return 1;
  if (!auditItemB) return -1;

  const tableNameA = auditItemA['表名'];
  const tableNameB = auditItemB['表名'];
  
  const indexA = medicalReviewOrder.indexOf(tableNameA);
  const indexB = medicalReviewOrder.indexOf(tableNameB);
  
  if (indexA === -1 && indexB === -1) return tableNameA.localeCompare(tableNameB);
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

// 重写 loadFile 函数以支持合并和排序
async function loadFile() {
  if (!props.filePath) return;
  isLoading.value = true;
  error.value = '';
  idCounter = 0;
  try {
    const rawData: Record<string, any>[] = await previewFile(props.filePath);
    
    // --- 步骤 1: 合并逻辑 ---
    const dataMap = new Map<string, { originalTexts: string[], struct: StructItem[], ruleValue: number }>();

    for (const item of rawData) {
      const originalTexts: string[] = [];
      const struct = item['结构'] || [];
      const ruleValue = parseRuleValueFromRaw(item);

      // 提取所有原文内容
      Object.keys(item).forEach(key => {
        if (key.startsWith('原文内容')) {
          originalTexts.push(item[key]);
        }
      });
      
      // 使用 `结构` 字段的字符串化版本作为 Map 的 key 来进行分组
      const structKey = JSON.stringify(struct);

      if (dataMap.has(structKey)) {
        // 如果已存在相同的结构，则合并原文内容，并合并规则（取最高）
        const entry = dataMap.get(structKey)!;
        entry.originalTexts.push(...originalTexts);
        entry.ruleValue = Math.max(entry.ruleValue, ruleValue);
      } else {
        // 否则，创建一个新条目
        dataMap.set(structKey, { originalTexts, struct, ruleValue });
      }
    }
    
    // --- 步骤 2: 将 Map 转换为 UI 使用的格式 ---
    let structuredData: EditableItem[] = Array.from(dataMap.values()).map(group => ({
      id: idCounter++,
      originalTexts: group.originalTexts,
      struct: group.struct,
      ruleValue: group.ruleValue,
      isAddingStruct: false,
      newStruct: { category: '审核项', tableName: '', fields: [] },
    }));

    // --- 步骤 3: 排序 ---
    structuredData.sort(compareItemsByMedicalOrder);
    
    originalData.value = JSON.parse(JSON.stringify(structuredData));
    editableData.value = JSON.parse(JSON.stringify(structuredData));

  } catch (e: any) {
    error.value = `加载文件失败: ${e.message}`;
  } finally {
    isLoading.value = false;
  }
}

// 当用户修改了可能影响排序的字段时，重新排序
function handleTableNameChange(item: EditableItem) {
  // 简单起见，只要任何表名改变就重排
  editableData.value.sort(compareItemsByMedicalOrder);
}
function handleCategoryChange(struct: StructItem, item: EditableItem) {
  struct['表名'] = ''; // 清空表名
  // 因为类别改变可能影响到哪个是“第一个审核项”，所以也要重排
  editableData.value.sort(compareItemsByMedicalOrder);
}
function handleNewCategoryChange(item: EditableItem) {
  item.newStruct.tableName = '';
}

function confirmAddStruct(item: EditableItem) {
  const { category, tableName, fields } = item.newStruct;
  if (!tableName) {
    ElMessage.warning('请选择表名！');
    return;
  }
  const newFields: StructField = {};
  for (const field of fields) {
    if (field.key.trim()) {
      newFields[field.key.trim()] = field.value;
    }
  }

  item.struct.push({
    '类别': category,
    '表名': tableName,
    '字段': newFields,
  });

  // 如果添加的是审核项，需要重新排序
  if (category === '审核项') {
    editableData.value.sort(compareItemsByMedicalOrder);
  }

  item.newStruct = { category: '审核项', tableName: '', fields: [] };
  item.isAddingStruct = false;
  ElMessage.success('结构项已添加');
}

function removeItem(itemIndex: number) {
  ElMessageBox.confirm('确定要删除这个原文内容及其所有结构化信息吗？', '警告', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(() => {
    editableData.value.splice(itemIndex, 1);
    ElMessage.success('条目已删除');
  });
}

function removeStructItem(item: EditableItem, structIndex: number) {
  if (item.struct.length <= 1) {
    ElMessage.warning('每个条目至少需要保留一个“结构”项。');
    return;
  }

  const removedStruct = item.struct[structIndex];

  ElMessageBox.confirm('确定要删除这个结构项吗？', '确认', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'info',
  }).then(() => {
    item.struct.splice(structIndex, 1);
    // 如果删除的是审核项，可能影响排序
    if (removedStruct['类别'] === '审核项') {
      editableData.value.sort(compareItemsByMedicalOrder);
    }
    ElMessage.success('结构项已删除');
  });
}

async function saveChanges() {
  if (!props.filePath || !props.isEditable) return;
  isSaving.value = true;
  try {
    // 保存时需要“展开”合并的数据
    const dataToSave: Record<string, any>[] = [];
    editableData.value.forEach(item => {
      const result: Record<string, any> = {};
      if (item.originalTexts.length > 1) {
        item.originalTexts.forEach((text, index) => {
          result[`原文内容_${index + 1}`] = text;
        });
      } else if (item.originalTexts.length === 1) {
        result['原文内容'] = item.originalTexts[0];
      }
      result['结构'] = item.struct;
      result['规则'] = [{ '等级': valueToLabel(item.ruleValue), '值': item.ruleValue }];
      dataToSave.push(result);
    });

    const diff = {
      before: originalData.value,
      after: editableData.value.map(item => {
        const { isAddingStruct, newStruct, ...rest } = item;
        return rest;
      })
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

function exportToFile() {
  if (!props.filePath) {
    ElMessage.error('没有文件可导出。');
    return;
  }
  // 导出逻辑与保存逻辑类似，但格式化为JSON
  // 这里的导出逻辑与原版基本一致，但使用展开后的数据
  const dataToExport: Record<string, any>[] = [];
  editableData.value.forEach(item => {
      const result: Record<string, any> = {};
      if (item.originalTexts.length > 1) {
          item.originalTexts.forEach((text, index) => {
              result[`原文内容_${index + 1}`] = text;
          });
      } else if (item.originalTexts.length === 1) {
          result['原文内容'] = item.originalTexts[0];
      }
      result['结构'] = item.struct;
      result['规则'] = [{ '等级': valueToLabel(item.ruleValue), '值': item.ruleValue }];
      dataToExport.push(result);
  });


  const jsonString = JSON.stringify(dataToExport, null, 2);
  const blob = new Blob([jsonString], { type: 'application/json;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  const fileName = props.filePath.split('\\').pop()?.split('/').pop() || 'exported_data.json';
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  ElMessage.success('文件已开始下载！');
}

watch(() => props.filePath, loadFile, { immediate: true });

</script>

<style scoped>
/* 样式无需改动 */
.editor-container { height: 100%; display: flex; flex-direction: column; }
.header { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-bottom: 15px; flex-shrink: 0; }
.header-title { flex: 1 1 auto; margin: 0; overflow: hidden; text-overflow: ellipsis; font-size: 16px; color: #606266; }
.header-actions { flex-shrink: 0; display: flex; gap: 10px; }
.card-list { flex-grow: 1; overflow-y: auto; padding: 5px; background-color: #f9fafb; }
.box-card { margin-bottom: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; font-weight: bold; }
.card-header > div { display: flex; align-items: center; gap: 10px; }
.remark-btn { padding-left: 8px; padding-right: 8px; }
.original-text-item .el-input { margin-bottom: 5px; }
.struct-list { margin-top: 20px; border-top: 1px solid #f0f2f5; padding-top: 15px; }
.struct-list h4 { margin-top: 0; margin-bottom: 10px; color: #303133; font-size: 16px; }
.inner-card { background-color: #ffffff; margin-bottom: 15px; border: 1px solid #e4e7ed; }
.inner-card-header { font-weight: normal; font-size: 14px; color: #303133; }
.form-row { display: flex; align-items: center; margin-bottom: 10px; }
.form-label { font-size: 14px; color: #606266; width: 150px; flex-shrink: 0; text-align: right; padding-right: 12px; }
.fields-section { margin-top: 15px; padding-top: 15px; border-top: 1px solid #f2f6fc; }
.fields-label { font-weight: bold; margin-bottom: 10px; color: #606266; }
.field-row .form-label { font-weight: normal; color: #909399; }
.error-message, .loading-message { text-align: center; padding: 20px; font-size: 1.2em; }
.add-struct-form { margin-top: 15px; }
.add-struct-form h5 { margin-top: 0; margin-bottom: 15px; }
.field-key-input { width: 150px; margin-right: 5px; }
.form-actions { margin-top: 15px; text-align: right; }
</style>