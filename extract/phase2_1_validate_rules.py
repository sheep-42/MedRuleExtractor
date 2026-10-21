# --- 规则定义 ---
# 定义“审核项”与不应共存的“前提条件”的配对规则
# 格式为: ("审核项", "要移除的前提条件")
# INCOMPATIBLE_PAIRS = [
#     ("特殊人群-妊娠", "性别"),
#     ("特殊人群-哺乳", "性别"),
#     # 在这里继续添加更多的规则...
#     # 例如: ("用法用量-单次剂量", "相互作用"),
# ]

import json
import os
import argparse
import logging
from logging_config import setup_logging
import sys
from typing import List, Dict, Any
from collections import defaultdict
from pathlib import Path

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

# --- 规则定义 ---
# 定义“审核项”与不应共存的“前提条件”的配对规则
# 格式为: ("审核项", "要移除的前提条件")
INCOMPATIBLE_PAIRS = [
    ("特殊人群-妊娠", "性别"),
    ("特殊人群-哺乳", "性别"),
    ("相互作用", "联合用药"),
    ("特殊人群-肾功能", "检验值"),
    ("特殊人群-肝功能", "检验值"),
    ("用法用量-禁止的给药途径", "给药途径"),
    ("用法用量-允许的给药途径", "给药途径"),
    ("特殊人群-妊娠", "妊娠哺乳状态"),
    ("特殊人群-哺乳", "妊娠哺乳状态"),
    ("特殊人群-年龄", "年龄"),
    ("用法用量-给药频次", "频次"),
    ("用法用量-单次剂量", "单次剂量"),
    ("禁忌症", "诊断"),
    ("特殊人群-肾功能", "肾功能"),
    ("特殊人群-肝功能", "肝功能"),
    # 在这里可以轻松地添加更多规则
    # ("一些审核项", "一些不相关的前提"), 
]

VALID_CONDITIONS = ['年龄', '性别', '体重', '体表面积', '孕周', '妊娠哺乳状态', '诊断', '频次', '检验值', '病情', '医嘱类型', '用药目的', '药品', '剂型', '单次剂量', '给药途径', '联合用药']

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"

# --- 工具函数 ---

def load_json(path: str) -> List[Dict[str, Any]]:
    """从JSON文件健壮地加载数据。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"文件未找到: {path}", exc_info=True)
        raise
    except json.JSONDecodeError as e:
        logger.error(f"解析JSON文件失败: {path}, 错误: {e}", exc_info=True)
        raise

def save_json(data: List[Dict[str, Any]], path: str):
    """将数据保存为格式化的JSON文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已成功保存到: {path}")

def build_rules_map(rules: List[tuple]) -> Dict[str, set]:
    """
    将规则列表转换为高效的查找映射。
    例如: [("A", "B"), ("A", "C")] -> {"A": {"B", "C"}}
    使用集合(set)可以实现O(1)的快速查找。
    """
    rules_map = defaultdict(set)
    for main_item, condition_to_remove in rules:
        rules_map[main_item].add(condition_to_remove)
    return rules_map

def apply_rules_to_data(data: List[Dict[str, Any]], rules_map: Dict[str, set]) -> List[Dict[str, Any]]:
    """
    遍历数据并应用规则来清理前提条件。
    """
    cleaned_data = []
    for item in data:
        main_audit_item = item.get("审核项")
        original_conditions = item.get("前提条件", [])

        for condition in original_conditions:
            if condition not in VALID_CONDITIONS:
                original_conditions.remove(condition)
        
        # 如果该审核项没有对应的规则，或者没有前提条件，则直接保留
        if not main_audit_item or not original_conditions or main_audit_item not in rules_map:
            cleaned_data.append(item)
            continue

        # 获取需要为当前审核项移除的前提条件集合
        conditions_to_remove = rules_map[main_audit_item]
        
        # 使用列表推导式高效地过滤掉不兼容的前提条件
        new_conditions = [
            cond for cond in original_conditions if cond not in conditions_to_remove
        ]
        
        # 记录被移除的项，用于日志输出
        removed_count = len(original_conditions) - len(new_conditions)
        if removed_count > 0:
            removed_set = set(original_conditions) - set(new_conditions)
            logger.info(
                f"规则应用: 对于审核项 '{main_audit_item}', 移除了前提条件: {list(removed_set)}"
            )

        # 创建一个新的记录副本并更新其前提条件
        new_item = item.copy()
        new_item["前提条件"] = new_conditions
        cleaned_data.append(new_item)
        
    return cleaned_data

def main():
    """主执行函数"""
    parser = argparse.ArgumentParser(description="应用硬编码规则清理第二阶段的输出结果")
    parser.add_argument("--input_file", type=str, required=True, help="第二阶段输出的JSON文件路径")
    args = parser.parse_args()

    # --- 1. 加载数据和构建规则 ---
    logger.info(f"正在加载待处理文件: {args.input_file}")
    stage2_data = load_json(args.input_file)
    
    logger.info("正在构建规则查找映射...")
    rules_map = build_rules_map(INCOMPATIBLE_PAIRS)
    logger.info(f"规则构建完成，共计 {len(rules_map)} 条审核项规则。")

    # --- 2. 应用规则 ---
    logger.info("开始应用规则清理数据...")
    cleaned_data = apply_rules_to_data(stage2_data, rules_map)

    # --- 3. 保存结果 ---
    # 自动生成输出路径，例如：conditions.json -> conditions_rules_validated.json
    output_path = args.input_file.replace("conditions.json", "conditions_rules_validated.json")
    if output_path == args.input_file: # 防止文件名不含.json时出错
        output_path = f"{args.input_file}_rules_validated"
    
    save_json(cleaned_data, output_path)

    print("\n" + "="*50)
    logger.info(f"规则应用完成，清理后的结果已保存至: {output_path}")
    print("="*50)

if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE2.1.log')
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