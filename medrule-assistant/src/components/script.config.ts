// src/components/script.config.ts

export interface ScriptArgument {
    name: string; // 例如 '--input_file'
    label: string; // 在 UI 上显示的标签，例如 '输入文件'
    type: 'string' | 'number' | 'boolean';
    defaultValue?: any;
    required: boolean;
}

export interface ScriptConfig {
    path: string; // 脚本相对于 extract 目录的路径
    name: string; // 在下拉菜单中显示的名字
    description: string;
    args: ScriptArgument[];
}

export const availableScripts: ScriptConfig[] = [
    {
        path: 'run_pipeline.py',
        name: '完整工作流 (run_pipeline.py)',
        description: '从头到尾运行整个提取流程。',
        args: [
            { name: '--input_file', label: '说明书MD文件路径', type: 'string', required: true, defaultValue: 'instructions_MD/xxxx.md' },
            { name: '--output-dir-name', label: '结果目录名 (必填)', type: 'string', required: true },
            { name: '--start-from', label: '起始阶段 (可选)', type: 'string', required: false },
            { name: '--end-at', label: '结束阶段 (可选)', type: 'string', required: false }
        ]
    },
    {
        path: 'phase1_0_extract.py',
        name: '阶段1: 板块提取',
        description: '仅运行板块提取脚本。',
        args: [
            { name: '--input_file', label: '说明书MD文件路径', type: 'string', required: true, defaultValue: './instructions_MD/xxxx.md'  },
            { name: '--output_dir', label: '输出目录', type: 'string', required: true },
        ]
    },
    {
        path: 'phase1_1_merge.py',
        name: '阶段1.1: 合并第一阶段结果',
        description: '仅运行合并第一阶段结果脚本。',
        args: [
            { name: '--dir_path', label: '包含 JSON 文件的目录路径', type: 'string', required: true }
        ]
    },
    {
        path: 'phase1_2_validate_schema.py',
        name: '阶段1.2: 审核原文内容是否无价值',
        description: '仅运行审核原文内容是否无价值的脚本。',
        args: [
            // { name: '--prompt_path', label: '提示词路径', type: 'string', required: false, defaultValue: './prompts/phase1/无价值段落检测.txt' },
            { name: '--input_file', label: '阶段1.1输出的JSON文件路径 (sections_merged.json)', type: 'string', required: true }
        ]
    },
    {
        path: 'phase1_3_validate_labels.py',
        name: '阶段1.3: 验证审核项标签的正确性',
        description: '仅运行验证预测的审核项标签的脚本。',
        args: [
            { name: '--input_file', label: '阶段1.2输出的JSON文件路径 (sections_merged_schema_validated.json)', type: 'string', required: true },
            // { name: '--definitions_file', label: '审核项定义的JSON文件路径', type: 'string', required: false, defaultValue: './prompts/phase1/审核项定义.json' },
            // { name: '--config_path', label: '配置文件的路径', type: 'string', required: false, defaultValue: './config/config.yaml' },
            // { name: '--prompt_file', label: '用于验证标签的提示词模板文件路径', type: 'string', required: false, defaultValue: './prompts/phase1/审核项判断.txt' }
        ]
    },
    {
        path: 'phase2_0_extract_conditions.py',
        name: '阶段2: 前提条件提取',
        description: '仅运行前提条件提取脚本。',
        args: [
            { name: '--input_file', label: '经过第一阶段验证后的JSON文件路径 (sections_merged_labels_validated.json)', type: 'string', required: true },
            // { name: '--prompt_file', label: '用于提取前提条件的提示词模板文件路径', type: 'string', required: false, defaultValue: './prompts/phase2/前提条件.txt' }
        ]
    },
    {
        path: 'phase2_1_validate_rules.py',
        name: '阶段2.1: 验证前提条件',
        description: '仅运行验证前提条件的脚本。',
        args: [
            { name: '--input_file', label: '阶段2 输出的JSON文件路径 (conditions.json)', type: 'string', required: true }
        ]
    },
    {
        path: 'phase3_0_extract_struct.py',
        name: '阶段3: 字段结构化提取',
        description: '仅运行字段结构化提取脚本。',
        args: [
            { name: '--input_file', label: '阶段2.1 提取了前提条件的JSON文件路径 (conditions_rules_validated.json)', type: 'string', required: true },
            // { name: '--structure-file', label: '定义了表结构和字段的JSON文件路径', type: 'string', required: false, defaultValue: './prompts/table_structure_updated.json' },
            // { name: '--prompt-with-cond', label: '带前提条件的提示词模板路径', type: 'string', required: false, defaultValue: './prompts/phase3/结构化字段抽取_有前提.txt' },
            // { name: '--prompt-no-cond', label: '无前提条件的提示词模板路径', type: 'string', required: false, defaultValue: './prompts/phase3/结构化字段抽取_无前提.txt' }
        ]
    },
    {
        path: 'phase3_1_filter_clean.py',
        name: '阶段3.1: 清理结构化提取结果',
        description: '仅运行清理结构化提取结果的脚本。',
        args: [
            { name: '--input_file', label: '阶段 3 输出的JSON文件路径 (struct_raw.json)', type: 'string', required: true }
        ]
    },
    {
        path: 'phase3_2_postprocess.py',
        name: '阶段3.2: 验证结构化提取结果',
        description: '仅运行验证结构化提取结果的脚本。',
        args: [
            { name: '--input_file', label: '阶段 3.1 输出的JSON文件路径 (struct_cleaned.json)', type: 'string', required: true },
        ]    
    },
    {
        path: 'phase4_0_normalize.py',
        name: '阶段4: 字段规范化',
        description: '仅运行字段规范化脚本。',
        args: [
            { name: '--input_file', label: '阶段 3.2 输出的JSON文件路径 (struct_postprocessed.json)', type: 'string', required: true },
        ]
    }
    // TODO: 在这里添加其他脚本的配置...
];