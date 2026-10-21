<!-- src/components/editors/Phase1_3Editor.vue -->
<template>
  <div class="editor-container">
    <div class="header">
      <h3>编辑器: {{ filePath }}</h3>
      <div class="header-actions">
        <el-button 
          v-if="isEditable"
          type="warning" 
          plain
          :icon="List" 
          @click="openDeleted12" 
        >
          P1.2 废弃项
        </el-button>
        <el-button 
          v-if="isEditable"
          type="warning" 
          plain
          :icon="List" 
          @click="openDeleted13" 
        >
          P1.3 废弃项
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

    <!-- 标签列表按医学审核顺序展示 -->
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
              <el-button class="button" type="danger" :icon="Delete" circle :disabled="!isEditable" @click="removeItem(itemIndex)" />
            </div>
          </div>
        </template>
        <div class="card-content">
          <el-input
            v-model="item.originalText"
            :disabled="!isEditable"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 10 }"
            class="original-text"
          />
          <div class="tags-section">
            <p class="tags-label">标签预测:</p>
            <!-- 【修改 2a】每个卡片只有一个标签，使用 v-model 直接绑定 item.tags[0] -->
            <div class="tag-wrapper">
              <el-select
                v-model="item.tags[0]"
                :disabled="!isEditable"
                placeholder="选择标签"
                filterable
                @change="handleTagChange"
              >
                <el-option
                  v-for="presetTag in medicalReviewOrder"
                  :key="presetTag"
                  :label="presetTag"
                  :value="presetTag"
                />
              </el-select>
              <!-- 移除了 addTag 和 removeTag 按钮，因为现在是严格的一对一关系 -->
            </div>
          </div>
        </div>
      </el-card>
      
      <!-- 添加新条目的卡片 -->
      <el-card class="add-new-card">
        <template #header>
          <span>添加新条目</span>
        </template>
        <el-form :model="newItem" label-position="top">
          <el-form-item label="原文内容">
            <el-input v-model="newItem.originalText" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="标签预测">
            <!-- 【修改 2a】添加新条目时也改为单选 -->
            <el-select v-model="newItem.tag" :disabled="!isEditable" filterable placeholder="请选择一个标签" style="width: 100%;">
              <el-option
                v-for="tag in medicalReviewOrder"
                :key="tag"
                :label="tag"
                :value="tag"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="success" :disabled="!isEditable" @click="addNewItem">添加到列表</el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </div>

    <div v-if="error" class="error-message">{{ error }}</div>
    <div v-if="isLoading && !error" class="loading-message">加载中...</div>

    <!-- Phase 1.2 废弃项弹窗 -->
    <el-dialog v-model="showDeleted12" title="Phase 1.2 (schema) 废弃项" width="80%">
      <el-table :data="deletedItems12" style="width: 100%" max-height="500">
        <el-table-column prop="原文内容" label="原文内容" show-overflow-tooltip />
        <el-table-column label="标签预测" width="200">
          <template #default="scope">
            <el-tag v-for="tag in scope.row['标签预测']" :key="tag" size="small" style="margin-right: 5px;">
              {{ tag }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="理由" label="删除理由" width="300" />
      </el-table>
    </el-dialog>

    <!-- Phase 1.3 废弃项弹窗 -->
    <el-dialog v-model="showDeleted13" title="Phase 1.3 (labels) 废弃项" width="80%">
      <el-table :data="deletedItems13" style="width: 100%" max-height="500">
        <el-table-column prop="原文内容" label="原文内容" show-overflow-tooltip />
        <el-table-column prop="审核项" label="审核项" width="150" />
        <el-table-column prop="理由" label="删除理由" width="300" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts"> 
import { ref, watch, reactive } from 'vue';
import { previewFile, saveFile, logEdit } from '../../api';
import { ElMessage, ElMessageBox } from 'element-plus';
import { DocumentChecked, Delete, Plus, ChatDotSquare, List } from '@element-plus/icons-vue';

// 定义常量替代“魔术字符串”
const ORIGINAL_TEXT_KEY = '原文内容';
const TAG_PREDICTION_KEY = '标签预测';

// 定义数据结构
interface EditableItem {
  id: number;
  originalText: string;
  tags: [string]; // 明确表示这是一个只有一个元素的数组，更符合逻辑
  remark?: string;
}

const props = defineProps<{
  filePath: string | undefined;
  isEditable: boolean;
}>();

// 医学审核顺序标签列表
const medicalReviewOrder = [
  "适应症", "禁忌症", "用法用量-单次剂量", "用法用量-单日剂量", "用法用量-给药频次",
  "用法用量-允许的给药途径", "用法用量-禁止的给药途径", "用法用量-药品总量", "用法用量-疗程",
  "特殊人群-年龄", "特殊人群-性别", "特殊人群-肾功能", "特殊人群-肝功能", "特殊人群-哺乳", "特殊人群-妊娠",
  "相互作用", "不良反应", "过敏", "浓度", "浓度体积", "浓度药品关联", "配伍禁忌"
];

// 响应式变量
const isLoading = ref(false);
const isSaving = ref(false);
const error = ref('');
const originalData = ref<EditableItem[]>([]); 
const editableData = ref<EditableItem[]>([]);
let idCounter = 0;

const showDeleted12 = ref(false);
const showDeleted13 = ref(false);
const deletedItems12 = ref<any[]>([]);
const deletedItems13 = ref<any[]>([]);

// 打开 Phase 1.2 废弃项
const openDeleted12 = async () => {
  if (!props.filePath) return;
  const dir = props.filePath.substring(0, props.filePath.lastIndexOf('/'));
  // 注意文件名是单数 _log
  const logPath = `${dir}/sections_merged_schema_validated_log.json`;
  
  try {
    const data = await previewFile(logPath);
    if (Array.isArray(data)) {
      deletedItems12.value = data.filter((item: any) => item['是否丢弃'] === true);
    } else {
      deletedItems12.value = [];
      ElMessage.warning('日志文件格式不正确');
    }
    showDeleted12.value = true;
  } catch (e) {
    ElMessage.warning('无法加载 Phase 1.2 日志文件 (sections_merged_schema_validated_log.json)');
    console.error(e);
  }
};

// 打开 Phase 1.3 废弃项
const openDeleted13 = async () => {
  if (!props.filePath) return;
  const dir = props.filePath.substring(0, props.filePath.lastIndexOf('/'));
  // 注意文件名是复数 _logs
  const logPath = `${dir}/sections_merged_labels_validated_logs.json`;
  
  try {
    const data = await previewFile(logPath);
    if (Array.isArray(data)) {
      // 过滤出 "判断" 为 "错误" 的项
      deletedItems13.value = data.filter((item: any) => item['判断'] === '错误');
    } else {
      deletedItems13.value = [];
      ElMessage.warning('日志文件格式不正确');
    }
    showDeleted13.value = true;
  } catch (e) {
    ElMessage.warning('无法加载 Phase 1.3 日志文件 (sections_merged_labels_validated_logs.json)');
    console.error(e);
  }
};

// 调整 newItem 结构以匹配单选
const newItem = reactive({
  originalText: '',
  tag: '', // 使用单个 tag 字符串
});

// 提炼排序逻辑为独立函数
function compareItemsByMedicalOrder(a: EditableItem, b: EditableItem): number {
  const tagA = a.tags[0];
  const tagB = b.tags[0];
  const indexA = medicalReviewOrder.indexOf(tagA);
  const indexB = medicalReviewOrder.indexOf(tagB);

  if (indexA === -1 && indexB === -1) return tagA.localeCompare(tagB); // 两个都是未知标签
  if (indexA === -1) return 1; // A是未知标签，放后面
  if (indexB === -1) return -1; // B是未知标签，放后面
  return indexA - indexB; // 按医学审核顺序排列
}


// 编辑备注
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

// 加载文件数据
async function loadFile() {
  if (!props.filePath) return;
  isLoading.value = true;
  error.value = '';
  idCounter = 0;
  
  try {
    const rawData: { [ORIGINAL_TEXT_KEY]: string; [TAG_PREDICTION_KEY]: string }[] = await previewFile(props.filePath);
    
    let structuredData: EditableItem[] = rawData.map(item => ({
      id: idCounter++,
      originalText: item[ORIGINAL_TEXT_KEY],
      tags: [item[TAG_PREDICTION_KEY]] // 每个标签作为独立条目，包装在数组中
    }));
    
    // 使用提炼出的排序函数
    structuredData.sort(compareItemsByMedicalOrder);
    
    originalData.value = JSON.parse(JSON.stringify(structuredData));
    editableData.value = JSON.parse(JSON.stringify(structuredData));

  } catch (e: any) {
    error.value = `加载文件失败: ${e.message}`;
  } finally {
    isLoading.value = false;
  }
}

// 当用户修改了卡片的标签后，重新排序整个列表
function handleTagChange() {
  editableData.value.sort(compareItemsByMedicalOrder);
}

// 移除条目
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

// 添加新条目
function addNewItem() {
  if (!newItem.originalText.trim()) {
    ElMessage.warning('原文内容不能为空！');
    return;
  }
  if (!newItem.tag) {
    ElMessage.warning('请选择一个标签！');
    return;
  }
  
  const itemToAdd: EditableItem = {
    id: idCounter++,
    originalText: newItem.originalText,
    tags: [newItem.tag],
  };

  editableData.value.push(itemToAdd);
  
  // 清空表单
  newItem.originalText = '';
  newItem.tag = '';
  ElMessage.success('新条目已添加！');
  
  // 添加后使用提炼出的排序函数重新排序
  editableData.value.sort(compareItemsByMedicalOrder);
}

// 保存更改
async function saveChanges() {
  if (!props.filePath || !props.isEditable) return;
  isSaving.value = true;
  
  try {
    const dataToSave: { [ORIGINAL_TEXT_KEY]: string; [TAG_PREDICTION_KEY]: string }[] = [];
    for (const item of editableData.value) {
      const tag = item.tags[0]; // 每个条目只有一个标签
      if (tag && tag.trim()) {
        dataToSave.push({
          [ORIGINAL_TEXT_KEY]: item.originalText,
          [TAG_PREDICTION_KEY]: tag
        });
      }
    }

    await Promise.all([
      saveFile(props.filePath, dataToSave),
      logEdit(props.filePath, {
        before: originalData.value,
        // 使用深拷贝创建不可变快照
        after: JSON.parse(JSON.stringify(editableData.value))
      })
    ]);
    
    ElMessage.success('保存成功！');
    await loadFile();
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e.message}`);
  } finally {
    isSaving.value = false;
  }
}

watch(() => props.filePath, loadFile, { immediate: true });
</script>

<style scoped>
.editor-container { height: 100%; display: flex; flex-direction: column; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding: 0 10px; }
.header-actions { display: flex; gap: 10px; }
.card-list { flex-grow: 1; overflow-y: auto; padding: 10px; background-color: #f9fafb; }
.box-card { margin-bottom: 15px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.remark-btn {
  padding-left: 8px;
  padding-right: 8px;
}
.original-text { width: 100%; margin-bottom: 15px; }
.tags-section { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 10px; }
.tags-label { margin: 0; color: #666; font-size: 14px; }
.tag-wrapper { display: flex; align-items: center; gap: 5px; }
.add-new-card { border: 2px dashed #ccc; margin-top: 10px; }
.error-message { color: #ff4d4f; text-align: center; padding: 20px; }
.loading-message { color: #666; text-align: center; padding: 20px; }
</style>