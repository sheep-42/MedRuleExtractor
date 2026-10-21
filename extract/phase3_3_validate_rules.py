import json
import os
import re
import argparse
from typing import List, Dict, Any
from pathlib import Path
import yaml

# --- 常量定义（核心配置）---
BASE_DIR = Path(__file__).resolve().parent.parent

# 1. 需进行规则判断的目标表名集合（已与特殊板块一一对应）
TARGET_TABLES = {
    "re_pw", 
    "re_in", 
    "re_sp_age", 
    "re_sp_kidney", 
    "re_sp_lactation", 
    "re_sp_liver", 
    "re_sp_pregnancy", 
    "re_taboo"
}

# 2. 规则等级配置（优先级从高到低）
RULE_LEVEL_KEYWORDS = {
    "拦截": {
        "keywords": r"严禁|禁用|禁服|忌用|禁忌|不可|不能|忌|避免",
        "priority": 4  # 最高优先级
    },
    "警告": {
        "keywords": r"",  # 警告无关键词，仅作为默认值
        "priority": 3
    },
    "提示": {
        "keywords": r"慎用|不宜|谨慎|不推荐|不适用|慎重",
        "priority": 2
    },
    "监测": {
        "keywords": r"加强观察|加强监护",
        "priority": 1  # 最低优先级
    }
}

# --- 工具函数 ---
def load_config(config_path: str) -> None:
    """从YAML配置文件加载配置（覆盖默认值）"""
    global RULE_LEVEL_KEYWORDS, TARGET_TABLES
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                # 覆盖规则等级配置
                if "rule_level_keywords" in config and isinstance(config["rule_level_keywords"], dict):
                    RULE_LEVEL_KEYWORDS = config["rule_level_keywords"]
                # 覆盖目标表名
                if "target_tables" in config and isinstance(config["target_tables"], (list, set)):
                    TARGET_TABLES = set(config["target_tables"])
    except Exception as e:
        print(f"警告：配置文件加载失败，使用默认配置。错误：{str(e)}")

def load_json_data(file_path: str) -> List[Dict[str, Any]]:
    """加载JSON数据（支持单条字典或多条列表）"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"输入文件不存在：{file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        # 确保返回列表格式
        return [data] if isinstance(data, dict) else data

def save_json_data(data: List[Dict[str, Any]], file_path: str) -> None:
    """保存JSON数据（确保中文不转义，自动创建目录）"""
    output_dir = os.path.dirname(file_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)

def get_item_table_name(item: Dict[str, Any]) -> str:
    """提取条目中的表名（从结构字段获取）"""
    structures = item.get("结构", [])
    for struct in structures:
        if isinstance(struct, dict) and "表名" in struct:
            return struct["表名"].strip().lower()  # 统一小写，避免大小写问题
    return ""

def determine_rule_info(text: str) -> Dict[str, Any]:
    """核心规则判断逻辑：根据关键词匹配等级"""
    cleaned_text = text.replace('\n', ' ')  # 预处理文本
    matched_levels = []
    
    # 遍历所有等级，仅匹配非警告等级（警告无关键词）
    for level, config in RULE_LEVEL_KEYWORDS.items():
        if level == "警告":
            continue  # 跳过警告，它仅作为默认值
        # 关键词非空且匹配时记录等级
        if config["keywords"] and re.search(config["keywords"], cleaned_text, re.IGNORECASE):
            matched_levels.append((level, config["priority"]))
    
    # 确定最终等级
    if not matched_levels:
        # 无任何匹配时默认警告
        return {"等级": "警告", "值": 3}
    else:
        # 按优先级排序，取最高优先级
        matched_levels.sort(key=lambda x: x[1], reverse=True)
        final_level, final_priority = matched_levels[0]
        return {"等级": final_level, "值": final_priority}

def extract_original_text(item: Dict[str, Any]) -> str:
    """提取并拼接'原文内容'字段，支持多段（如 原文内容_1, 原文内容_2 ...）"""
    texts: List[str] = []

    # 基础字段
    base_value = item.get("原文内容")
    if isinstance(base_value, str) and base_value.strip():
        texts.append(base_value.strip())
    elif isinstance(base_value, list):
        texts.extend([str(v).strip() for v in base_value if str(v).strip()])

    # 编号字段
    numbered: List[tuple] = []
    for key, value in item.items():
        if not isinstance(key, str):
            continue
        m = re.match(r"^原文内容_(\d+)$", key)
        if m and isinstance(value, str) and value.strip():
            try:
                idx = int(m.group(1))
            except ValueError:
                continue
            numbered.append((idx, value.strip()))
    numbered.sort(key=lambda x: x[0])

    texts.extend([v for _, v in numbered])

    return "\n".join(texts).strip()

def add_rule_to_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """为单个条目添加规则字段（包含表名过滤）"""
    # 1. 提取表名并判断是否为目标表
    item_table = get_item_table_name(item)
    is_target_table = item_table in TARGET_TABLES
    
    # 2. 提取原文内容
    original_text = extract_original_text(item)
    
    # 3. 根据表名决定是否执行规则判断
    if is_target_table and original_text:
        # 目标表名且有文本：执行规则判断
        rule_info = determine_rule_info(original_text)
    else:
        # 非目标表名或无文本：默认警告
        rule_info = {"等级": "警告", "值": 3}
    
    # 4. 添加规则字段并返回
    item_with_rule = item.copy()
    item_with_rule["规则"] = [rule_info]
    return item_with_rule

def batch_process_items(input_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量处理所有条目"""
    processed_items = []
    for item in input_data:
        # 仅处理包含核心字段的条目
        if "结构" in item:
            combined_text = extract_original_text(item)
            if combined_text:
                processed_items.append(add_rule_to_item(item))
    return processed_items

# --- 主函数 ---
def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="phase3.3 结构化结果规则验证（精简版）")
    parser.add_argument("--input_file", type=str, required=True, help="输入JSON文件路径（来自phase3.2）")
    parser.add_argument("--output_file", type=str, default=None, help="输出JSON文件路径（可选）")
    parser.add_argument("--config_file", type=str, default=None, help="配置文件路径（可选）")
    args = parser.parse_args()

    # 处理输出路径（默认适配工作流）
    if not args.output_file:
        input_dir = os.path.dirname(args.input_file)
        args.output_file = os.path.join(input_dir, "struct_validated_rules.json")

    try:
        # 加载配置（优先用户指定，其次默认配置）
        if args.config_file:
            load_config(args.config_file)
        else:
            # 尝试加载默认配置
            default_config = str(BASE_DIR.joinpath("config", "config.yaml"))
            if os.path.exists(default_config):
                load_config(default_config)

        # 加载输入数据
        input_data = load_json_data(args.input_file)
        if not input_data:
            print(f"警告：输入文件 {args.input_file} 中没有有效数据")
            return

        # 批量处理数据
        processed_data = batch_process_items(input_data)
        if not processed_data:
            print(f"警告：没有符合要求的数据（需包含'结构'字段且至少一个'原文内容'段）")
            return

        # 保存处理结果
        save_json_data(processed_data, args.output_file)
        print(f"成功：共处理 {len(processed_data)} 条数据，结果已保存到 {args.output_file}")

    except Exception as e:
        print(f"错误：处理过程中发生异常 - {str(e)}")
        raise  # 抛出异常，供工作流捕获并记录日志

if __name__ == "__main__":
    main()
