import sys
import argparse
import logging
import re
from pathlib import Path
from typing import Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from core.config_mgr import load_global_config
from core.log_mgr import setup_logging
from core.file_handler import FileHandler

logger = logging.getLogger(__name__)
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"

# 默认配置
DEFAULT_TARGET_TABLES = {
    "re_pw", "re_in", "re_sp_age", "re_sp_kidney", 
    "re_sp_lactation", "re_sp_liver", "re_sp_pregnancy", "re_taboo"
}

DEFAULT_RULE_LEVELS = {
    "拦截": {"keywords": r"严禁|禁用|禁服|忌用|禁忌|不可|不能|忌|避免", "priority": 4},
    "警告": {"keywords": r"", "priority": 3},
    "提示": {"keywords": r"慎用|不宜|谨慎|不推荐|不适用|慎重", "priority": 2},
    "监测": {"keywords": r"加强观察|加强监护", "priority": 1}
}

class RuleValidator:
    def __init__(self, config: dict):
        # 尝试从配置加载，否则用默认
        self.target_tables = set(config.get("target_tables", DEFAULT_TARGET_TABLES))
        self.rule_levels = config.get("rule_level_keywords", DEFAULT_RULE_LEVELS)

    def determine_level(self, text: str) -> dict:
        text = text.replace('\n', ' ')
        matches = []
        
        for level, info in self.rule_levels.items():
            if level == "警告": continue # 默认值
            kw = info.get("keywords")
            if kw and re.search(kw, text, re.IGNORECASE):
                matches.append((level, info["priority"]))
        
        if not matches:
            return {"等级": "警告", "值": 3}
        
        # 取优先级最高的
        matches.sort(key=lambda x: x[1], reverse=True)
        top = matches[0]
        return {"等级": top[0], "值": top[1]}

    def process_item(self, item: dict) -> dict:
        # 提取原文 (支持多个原文内容字段)
        texts = []
        # 按键名排序确保顺序
        keys = sorted([k for k in item.keys() if k.startswith("原文内容")])
        for k in keys:
            val = item[k]
            if val: texts.append(str(val).strip())
        
        full_text = "\n".join(texts)
        
        # 检查是否涉及目标表
        structs = item.get("结构", [])
        is_target = any(
            s.get("表名", "").lower() in self.target_tables 
            for s in structs
        )

        rule_info = {"等级": "警告", "值": 3}
        if is_target and full_text:
            rule_info = self.determine_level(full_text)
            
        # 注入结果
        item["规则"] = [rule_info]
        return item

def main():
    parser = argparse.ArgumentParser(description="Phase 3.3: 规则等级判定")
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--config_path", type=str, default=str(CONFIG_PATH))
    args = parser.parse_args()

    config = load_global_config(args.config_path)
    validator = RuleValidator(config)

    data = FileHandler.load_json(args.input_file)
    logger.info(f"开始规则判定，共 {len(data)} 条...")

    # 仅处理包含“结构”的有效数据
    processed = []
    for item in data:
        if "结构" in item:
            processed.append(validator.process_item(item))
            
    output_path = Path(args.input_file).with_name("struct_validated_rules.json")
    FileHandler.save_json(processed, output_path)
    logger.info(f"Phase 3.3 完成。保存至: {output_path}")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE3.3.log')
    try:
        main()
    except Exception as e:
        logger.critical("Phase 3.3 崩溃", exc_info=True)
        sys.exit(1)