import sys
import argparse
import logging
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from core.log_mgr import setup_logging
from core.file_handler import FileHandler
# 引入规则
try:
    from rules.incompatibility import INCOMPATIBLE_PAIRS, VALID_CONDITIONS
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("未找到 rules 模块，使用空规则。")
    INCOMPATIBLE_PAIRS = []
    VALID_CONDITIONS = set()

logger = logging.getLogger(__name__)
LOG_DIR = BASE_DIR / "logs"

def build_rules_map(rules: list) -> dict:
    """构建规则查找表: AuditItem -> Set[ConditionsToRemove]"""
    rules_map = defaultdict(set)
    for main_item, cond_to_remove in rules:
        rules_map[main_item].add(cond_to_remove)
    return rules_map

def apply_rules(data: list, rules_map: dict) -> list:
    cleaned_data = []
    
    for item in data:
        main_item = item.get("审核项")
        conditions = item.get("前提条件", [])
        
        # 1. 过滤不在 VALID_CONDITIONS 中的非法前提条件
        if VALID_CONDITIONS:
            conditions = [c for c in conditions if c in VALID_CONDITIONS]

        # 2. 应用互斥规则
        if main_item in rules_map:
            to_remove = rules_map[main_item]
            original_len = len(conditions)
            # 过滤
            conditions = [c for c in conditions if c not in to_remove]
            
            if len(conditions) < original_len:
                logger.debug(f"规则生效: [{main_item}] 移除了 {original_len - len(conditions)} 个条件")

        # 更新 item
        new_item = item.copy()
        new_item["前提条件"] = conditions
        cleaned_data.append(new_item)
        
    return cleaned_data

def main():
    parser = argparse.ArgumentParser(description="Phase 2.1: 规则验证与清理")
    parser.add_argument("--input_file", type=str, required=True)
    args = parser.parse_args()

    # 1. 加载
    data = FileHandler.load_json(args.input_file)
    logger.info(f"加载 {len(data)} 条数据，应用 {len(INCOMPATIBLE_PAIRS)} 条互斥规则。")

    # 2. 处理
    rules_map = build_rules_map(INCOMPATIBLE_PAIRS)
    cleaned_data = apply_rules(data, rules_map)

    # 3. 保存
    # 文件名替换: conditions.json -> conditions_rules_validated.json
    input_path = Path(args.input_file)
    new_name = input_path.stem.replace("conditions", "conditions_rules_validated")
    if new_name == input_path.stem:
        new_name += "_rules_validated"
    
    output_path = input_path.with_name(f"{new_name}.json")
    FileHandler.save_json(cleaned_data, output_path)
    
    logger.info(f"Phase 2.1 完成。清理后结果: {output_path}")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE2.1.log')
    try:
        main()
    except Exception as e:
        logger.critical("Phase 2.1 崩溃", exc_info=True)
        sys.exit(1)