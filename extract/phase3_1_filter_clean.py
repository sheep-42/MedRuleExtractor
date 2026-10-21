import json
import os
import argparse
import logging
from logging_config import setup_logging
import sys
from pathlib import Path
from typing import List, Dict, Any

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"

# --- 工具函数 ---

def load_json(path: str) -> Any:
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

def save_json(data: Any, path: str):
    """将数据保存为格式化的JSON文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已成功保存到: {path}")

def is_struct_element_valid(struct_item: Dict[str, Any]) -> bool:
    """
    判断一个结构元素是否有效。
    有效的条件是：其 "字段" 字典中至少有一个值不为 null。
    """
    # .get("字段", {}) 确保即使没有 "字段" 键也不会出错
    fields = struct_item.get("字段", {})
    if not fields or not isinstance(fields, dict):
        return False # 如果字段不是字典或为空，视为无效
    
    # all() 在空迭代上返回 True，所以要先检查 fields 是否为空
    return not all(value is None for value in fields.values())

def filter_and_clean_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    根据指定规则过滤和清理数据列表。
    """
    cleaned_data = []
    for record in data:
        # 规则 1: 检查 "结构" 键及其内容是否为非空列表
        struct_list = record.get("结构")
        if not isinstance(struct_list, list) or not struct_list:
            logger.warning(f"跳过记录，因其'结构'键缺失、为null或为空列表: {record.get('原文内容', '无原文')[:30]}...")
            continue

        # 将所有有效的 "审核项" 和 "前提条件" 分别筛选出来
        valid_audit_items = []
        valid_condition_items = []

        for struct_item in struct_list:
            if not isinstance(struct_item, dict):
                continue # 跳过非字典类型的元素

            # 规则 2: 判断结构元素本身是否有效
            if is_struct_element_valid(struct_item):
                item_type = struct_item.get("类别")
                if item_type == "审核项":
                    valid_audit_items.append(struct_item)
                elif item_type == "前提条件":
                    valid_condition_items.append(struct_item)
                else:
                    logger.warning(f"跳过记录中的未知类别元素: {item_type}，内容: {struct_item.get('字段', {})}")
        
        # 规则 3: 最终采纳决策
        # 如果不存在任何有效的 "审核项"，则丢弃整个记录
        if not valid_audit_items:
            logger.info(f"丢弃记录，因其不包含任何有效的'审核项': {record.get('原文内容', '无原文')[:30]}...")
            continue
        
        # 重建记录：只保留有效的元素
        record["结构"] = valid_audit_items + valid_condition_items

        # 去掉record中可能存在的其他不必要的键
        if "prompt" in record:
            record.pop("prompt")

        cleaned_data.append(record)
        
    return cleaned_data

def main():
    """主执行函数"""
    parser = argparse.ArgumentParser(description="清理并验证结构化提取的结果")
    parser.add_argument("--input_file", type=str, required=True, help="待清理的第三阶段JSON文件路径")

    args = parser.parse_args()

    # --- 1. 加载数据 ---
    logger.info(f"正在加载待清理文件: {args.input_file}")
    raw_data = load_json(args.input_file)

    # --- 2. 执行清理逻辑 ---
    logger.info("开始执行清理和验证逻辑...")
    cleaned_data = filter_and_clean_data(raw_data)
    logger.info(f"清理完成，有效记录数: {len(cleaned_data)} / 原始记录数: {len(raw_data)}")

    # --- 3. 追加额外数据 ---
    # 自动派生 '成份.json'、'药品名称.json' 的路径
    input_dir = os.path.dirname(args.input_file)
    if 'stage_3' not in input_dir:
        logger.warning(
            f"输入文件路径 '{args.input_file}' 不符合 '.../stage_3/...' 结构，无法自动定位 '成份.json'。将跳过文件追加步骤。"
        )
    else:
        stage1_dir = input_dir.replace("stage_3", "stage_1")
        append_file_path_1 = os.path.join(stage1_dir, "sections", "成份.json")
        append_file_path_2 = os.path.join(stage1_dir, "sections", "药品名称.json")

        for append_file_path in [append_file_path_1, append_file_path_2]:
            logger.info(f"尝试加载并追加自动定位的文件: {append_file_path}")
            try:
                append_data = load_json(append_file_path)
                # 确保追加的是一个独立的元素或列表
                if isinstance(append_data, list):
                    cleaned_data.extend(append_data)
                else:
                    cleaned_data.append(append_data)
                logger.info("文件追加成功。")
            except FileNotFoundError:
                logger.warning(f"未找到自动定位的追加文件: {append_file_path}。这可能是正常情况，将跳过追加步骤。")
            except Exception as e:
                # 其他加载错误（如JSON格式问题）
                logger.error(f"加载追加文件 '{append_file_path}' 时出错: {e}。将跳过追加步骤。", exc_info=True)


    # --- 4. 保存结果 ---
    # 自动生成输出路径
    output_path = args.input_file.replace("struct_raw.json", "struct_cleaned.json")
    if output_path == args.input_file: # 防止文件名不含.json时出错
        output_path = f"{args.input_file.replace('raw', 'cleaned')}"

    save_json(cleaned_data, output_path)
    print("\n" + "="*50)
    logger.info(f"处理完成，清理后的结果已保存至: {output_path}")
    print("="*50)

if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE3.1.log')
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