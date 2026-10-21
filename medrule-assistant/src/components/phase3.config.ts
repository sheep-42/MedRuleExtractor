// src/components/phase3.config.ts

export interface TableOption {
  value: string;
  label: string;
}

export const categoryOptions: TableOption[] = [
  { value: '审核项', label: '审核项' },
  { value: '前提条件', label: '前提条件' },
];

export const tableMap: Record<string, TableOption[]> = {
  '审核项': [
    { value: 're_taboo', label: 're_taboo (禁忌症)' },
    { value: 're_allergy', label: 're_allergy (过敏)' },
    { value: 're_sp_age', label: 're_sp_age (特殊人群-年龄)' },
    { value: 're_sp_sex', label: 're_sp_sex (特殊人群-性别)' },
    { value: 're_sp_kidney', label: 're_sp_kidney (特殊人群-肾功能)' },
    { value: 're_sp_liver', label: 're_sp_liver (特殊人群-肝功能)' },
    { value: 're_sp_lactation', label: 're_sp_lactation (特殊人群-哺乳)' },
    { value: 're_sp_pregnancy', label: 're_sp_pregnancy (特殊人群-妊娠)' },
    { value: 're_me', label: 're_me (浓度)' },
    { value: 're_volume', label: 're_volume (浓度体积)' },
    { value: 're_me_link', label: 're_me_link (浓度药品关联)' },
    { value: 're_in', label: 're_in (相互作用)' },
    { value: 're_pw', label: 're_pw (配伍禁忌)' },
    { value: 're_adapt', label: 're_adapt (适应症)' },
    { value: 're_usage_once', label: 're_usage_once (用法用量-单次剂量)' },
    { value: 're_usage_day', label: 're_usage_day (用法用量-单日剂量)' },
    { value: 're_usage_frequency', label: 're_usage_frequency (用法用量-给药频次)' },
    { value: 're_usage_allow_way', label: 're_usage_allow_way (用法用量-允许的给药途径)' },
    { value: 're_usage_deny_way', label: 're_usage_deny_way (用法用量-禁止的给药途径)' },
    { value: 're_usage_total', label: 're_usage_total (用法用量-药品总量)' },
    { value: 're_usage_treatment', label: 're_usage_treatment (用法用量-疗程)' },
    { value: 're_usage_pre', label: 're_usage_pre (用法用量-可以提前几天开药)' },
    { value: 're_re', label: 're_re (重复用药)' },
  ],
  '前提条件': [
    { value: 'qu_age', label: 'qu_age (年龄)' },
    { value: 'qu_sex', label: 'qu_sex (性别)' },
    { value: 'qu_weight', label: 'qu_weight (体重)' },
    { value: 'qu_surface', label: 'qu_surface (体表面积)' },
    { value: 'qu_gestate_week', label: 'qu_gestate_week (孕周)' },
    { value: 'qu_special', label: 'qu_special (妊娠哺乳状态)' },
    { value: 'qu_diagnosis', label: 'qu_diagnosis (诊断)' },
    { value: 'qu_frequency', label: 'qu_frequency (频次)' },
    { value: 'qu_lis', label: 'qu_lis (检验值)' },
    { value: 'qu_illness', label: 'qu_illness (病情)' },
    { value: 'qu_order_type', label: 'qu_order_type (医嘱类型)' },
    { value: 'qu_purp', label: 'qu_purp (用药目的)' },
    { value: 'qu_drug', label: 'qu_drug (药品)' },
    { value: 'qu_drug_form', label: 'qu_drug_form (剂型)' },
    { value: 'qu_usage_once', label: 'qu_usage_once (单次剂量)' },
    { value: 'qu_useway', label: 'qu_useway (给药途径)' },
    { value: 'qu_drug_union', label: 'qu_drug_union (联合用药)' },
  ]
};