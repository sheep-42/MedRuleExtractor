import os
import json
import argparse
import logging
from logging_config import setup_logging
import sys
import copy
from collections import Counter, defaultdict
from itertools import groupby
from typing import Dict, Any, List, Union, Set
from pathlib import Path

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"

# --- 文件加载/保存辅助函数 ---

def load_json(path: str) -> List[Dict[str, Any]]:
    """从JSON文件健壮地加载数据。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"加载或解析JSON文件失败: {path}, 错误: {e}")
        raise

def save_json(data: List[Dict[str, Any]], path: str):
    """将数据保存为格式化的JSON文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已成功保存到: {path}")

# --- 核心逻辑函数 ---

# 功能一：合并 item 内部的结构
def merge_fields(fields_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """合并多个字段字典，对字段值进行智能去重和拼接。"""
    # (This function remains unchanged from the previous version)
    merged_values: Dict[str, Set[Union[str, int, float, bool]]] = {}
    for fields in fields_list:
        if not isinstance(fields, dict): continue
        for key, value in fields.items():
            if value is None or value == "null": continue
            if key not in merged_values: merged_values[key] = set()
            if isinstance(value, str):
                merged_values[key].update({v.strip() for v in value.split(',') if v.strip()})
            else:
                merged_values[key].add(value)
    final_fields = {}
    for key, value_set in merged_values.items():
        if not value_set: continue
        if len(value_set) == 1:
            final_fields[key] = value_set.pop()
        else:
            sorted_values = sorted(list(value_set), key=str)
            final_fields[key] = ",".join(map(str, sorted_values))
    return final_fields

def merge_structures_in_item(item: Dict[str, Any], whitelist: Set[str]) -> Dict[str, Any]:
    """
    处理单个记录，仅合并“表名”在白名单内的、重复的“审核项”。
    
    Args:
        item: 待处理的数据项。
        whitelist: 一个包含表名的集合，只有这些表名才会被合并。
    """
    if not whitelist:
        # If the whitelist is empty, no merging will occur.
        return item
        
    if "结构" not in item or not isinstance(item["结构"], list):
        return item

    audit_structs = sorted([s for s in item["结构"] if s.get("类别") == "审核项"], key=lambda x: x.get("表名", ""))
    other_structs = [s for s in item["结构"] if s.get("类别") != "审核项"]
    
    merged_audit_structs = []
    # 使用 groupby 高效地按“表名”对审核项进行分组
    for table_name, group in groupby(audit_structs, key=lambda x: x.get("表名")):
        if not table_name: continue
        
        group_list = list(group)
        
        # **核心修改**: 只有当表名在白名单内且数量>1时才合并
        if len(group_list) > 1 and table_name in whitelist:
            logger.info(f"表名 '{table_name}' 在白名单内，将合并 {len(group_list)} 个审核项。")
            merged_struct = {
                "类别": "审核项",
                "表名": table_name,
                "字段": merge_fields([s.get("字段", {}) for s in group_list])
            }
            merged_audit_structs.append(merged_struct)
        else:
            # 如果不符合合并条件（不在白名单内或只有一个），则原样添加
            merged_audit_structs.extend(group_list)
            
    # 重建该记录的“结构”列表
    item["结构"] = merged_audit_structs + other_structs
    return item

# 功能二：删除冗余前提条件
def remove_redundant_preconditions(data: List[Dict[str, Any]], whitelist: Set[str]) -> List[Dict[str, Any]]:
    """统计审核项表名出现次数，并对在白名单内的、唯一的审核项，删除其前提条件。"""
    # (This function remains unchanged)
    if not whitelist:
        logger.info("前提条件删除白名单为空，跳过此步骤。")
        return data
    logger.info(f"将对以下白名单中的审核项执行冗余前提条件检查: {whitelist}")
    audit_table_counter = Counter(s["表名"] for item in data for s in item.get("结构", []) if s.get("类别") == "审核项" and s.get("表名"))
    cleaned_data = []
    for item in data:
        struct_list = item.get("结构", [])
        item_audit_tables = {s["表名"] for s in struct_list if s.get("类别") == "审核项" and s.get("表名")}
        should_remove = any(name in whitelist and audit_table_counter.get(name, 0) == 1 for name in item_audit_tables)
        if should_remove:
            logger.info(f"审核项 '{item_audit_tables & whitelist}' 在白名单内且是唯一的，将移除其前提条件。")
            item["结构"] = [s for s in struct_list if s.get("类别") != "前提条件"]
        cleaned_data.append(item)
    return cleaned_data

# --- 新增功能三：合并结构完全相同的 item ---

def get_struct_signature(struct_list: List[Dict[str, Any]]) -> str:
    """
    为结构列表生成一个唯一的、规范化的签名字符串。
    该签名对结构内元素的顺序和字段内键的顺序不敏感。
    """
    if not struct_list:
        return "[]"
    
    # 使用深拷贝以避免修改原始数据
    normalized_list = []
    for s_orig in struct_list:
        s = copy.deepcopy(s_orig)
        # 规范化字段字典，按键排序
        if isinstance(s.get("字段"), dict):
            s["字段"] = {k: s["字段"][k] for k in sorted(s["字段"])}
        normalized_list.append(s)

    # 规范化结构列表，按类别和表名排序
    sorted_list = sorted(normalized_list, key=lambda x: (x.get("类别", ""), x.get("表名", "")))
    
    # 使用json.dumps生成最终的、可哈希的签名
    return json.dumps(sorted_list, ensure_ascii=False, sort_keys=True)

def merge_identical_structure_items(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    合并具有完全相同“结构”的记录。
    合并后的记录将包含多个`原文内容_N`字段，并保留一份“结构”副本。
    """
    # 使用defaultdict按结构签名对item进行分组
    struct_groups = defaultdict(list)
    for item in data:
        # 使用.get("结构", [])确保即使没有结构键也不会出错
        signature = get_struct_signature(item.get("结构", []))
        struct_groups[signature].append(item)

    # 构造合并后的新数据列表
    final_data = []
    for group in struct_groups.values():
        if len(group) == 1:
            # 如果分组只有一个item，直接保留
            final_data.append(group[0])
        else:
            # 如果有多个item，进行合并
            logger.info(f"发现 {len(group)} 个结构相同的记录，将合并它们的原文内容。")
            
            # 使用字典推导式创建 "原文内容_N" 字段
            # 注意：group[0]中可能已经有 "原文内容_N" 格式，需先处理
            merged_item = {}
            content_idx = 1
            for g_item in group:
                # 检查g_item是否已经是合并过的
                if "原文内容_1" in g_item:
                    # 如果是，则提取其所有的原文内容
                    for k, v in g_item.items():
                        if k.startswith("原文内容_"):
                            merged_item[f"原文内容_{content_idx}"] = v
                            content_idx += 1
                else: # 是原始item
                    merged_item[f"原文内容_{content_idx}"] = g_item["原文内容"]
                    content_idx += 1

            # 保留一份结构副本
            merged_item["结构"] = group[0]["结构"]
            final_data.append(merged_item)
            
    return final_data

# --- 主执行函数 ---

def main():
    """主执行函数"""
    parser = argparse.ArgumentParser(description="后处理第三阶段的结构化结果")
    parser.add_argument("--input_file", type=str, required=True, help="第三阶段的原始结构化JSON文件路径")
    parser.add_argument(
        "--merge-whitelist",
        type=str,
        default="re_adapt", # Default to the example you provided
        help="需要合并的审核项表名白名单，用逗号分隔"
    )    
    parser.add_argument(
        "--precondition-whitelist", 
        type=str, 
        default="re_usage_once,re_usage_day,re_usage_frequency,re_usage_allow_way,re_usage_deny_way",
        help="参与冗余前提条件删除的审核项表名白名单，用逗号分隔"
    )
    args = parser.parse_args()

    # --- 1. 加载数据 ---
    raw_data = load_json(args.input_file)

    # --- 2. 功能一：合并每个item内重复的审核项 (使用白名单) ---
    logger.info("步骤 1/3: 开始合并每个记录中重复的审核项...")
    merge_whitelist = {name.strip() for name in args.merge_whitelist.split(',') if name.strip()}
    logger.info(f"将对以下白名单中的审核项执行合并操作: {merge_whitelist}")
    data_after_merge = [merge_structures_in_item(item, whitelist=merge_whitelist) for item in raw_data]
    
    # --- 3. 功能二：删除冗余的前提条件 (使用白名单) ---
    logger.info("步骤 2/3: 开始分析并删除冗余的前提条件...")
    whitelist = {name.strip() for name in args.precondition_whitelist.split(',') if name.strip()}
    data_after_cleanup = remove_redundant_preconditions(data_after_merge, whitelist=whitelist)
    
    # --- 4. 新增功能三：合并结构完全相同的 item ---
    logger.info("步骤 3/3: 开始合并结构完全相同的记录...")
    final_data = merge_identical_structure_items(data_after_cleanup)

    # --- 5. 保存结果 ---
    output_path = args.input_file.replace("struct_cleaned.json", "struct_postprocessed.json")
    if output_path == args.input_file:
        output_path = f"{args.input_file.replace('cleaned', 'postprocessed')}"

    save_json(final_data, output_path)

    print("\n" + "="*50)
    print(f"后处理完成！共生成 {len(final_data)} 条最终记录。")
    print(f"结果已保存至: {output_path}")
    print("="*50)

if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE3.2.log')
    # 2. 用 try...except 包装主逻辑
    try:
        main()
        logger.info("任务成功完成。")
    except Exception as e:
        # 3. 在捕获到任何未处理的异常时，使用 logger 记录
        # logger.critical() 是比 error 更高的级别，适合记录导致程序终止的错误
        # exc_info=True 是关键！它会自动将异常信息和完整的 Traceback 附加到日志中
        logger.critical("脚本执行过程中发生未捕获的致命错误！", exc_info=True)
        
        # 4. 以非零状态码退出，让调用者（web_app.py）知道任务失败了
        sys.exit(1)