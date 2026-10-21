import sys
import argparse
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from core.log_mgr import setup_logging
from core.file_handler import FileHandler

logger = logging.getLogger(__name__)
LOG_DIR = BASE_DIR / "logs"

def is_struct_valid(struct_item: dict) -> bool:
    """判断结构元素是否有效（字段中至少有一个非空值）"""
    fields = struct_item.get("字段", {})
    if not fields or not isinstance(fields, dict):
        return False
    return not all(v is None for v in fields.values())

def clean_data(data: list) -> list:
    cleaned = []
    for record in data:
        # 获取 LLM 返回的结构化部分
        # 兼容性处理：Phase 3.0 返回的 "结构化结果" 可能直接包含数据，或者是包含 "结构" 键的字典
        struct_res = record.get("结构化结果", {})
        
        # 提取核心列表
        struct_list = struct_res.get("结构") if isinstance(struct_res, dict) else None
        
        if not isinstance(struct_list, list) or not struct_list:
            # 尝试直接从 record 获取（如果格式有变）
            struct_list = record.get("结构")
            if not isinstance(struct_list, list):
                continue
        
        valid_items = []
        has_audit_item = False

        for item in struct_list:
            if not isinstance(item, dict): continue
            
            if is_struct_valid(item):
                valid_items.append(item)
                if item.get("类别") == "审核项":
                    has_audit_item = True
        
        # 规则：必须包含至少一个有效的审核项
        if has_audit_item:
            # 重构 record，拉平结构
            new_record = {
                "原文内容": record.get("原文内容"),
                "审核项": record.get("审核项"),
                "结构": valid_items
            }
            cleaned.append(new_record)
            
    return cleaned

def append_extra_files(data: list, current_file_path: Path):
    """尝试追加 '成份.json' 和 '药品名称.json'"""
    # 路径推导: .../stage_3/xxx -> .../stage_1/sections/xxx
    if 'stage_3' not in str(current_file_path):
        return

    stage1_dir = Path(str(current_file_path.parent).replace('stage_3', 'stage_1'))
    target_files = ["成份.json", "药品名称.json"]
    
    for fname in target_files:
        fpath = stage1_dir / "sections" / fname
        try:
            extra_data = FileHandler.load_json(fpath)
            if isinstance(extra_data, list):
                data.extend(extra_data)
            else:
                data.append(extra_data)
            logger.info(f"已追加文件: {fname}")
        except Exception:
            # 文件不存在是正常的，不做处理
            pass

def main():
    parser = argparse.ArgumentParser(description="Phase 3.1: 清理与验证")
    parser.add_argument("--input_file", type=str, required=True)
    args = parser.parse_args()

    data = FileHandler.load_json(args.input_file)
    logger.info(f"加载原始数据: {len(data)} 条")

    cleaned_data = clean_data(data)
    logger.info(f"清理后有效数据: {len(cleaned_data)} 条")

    # 追加额外文件
    append_extra_files(cleaned_data, Path(args.input_file))

    # 保存
    output_path = Path(args.input_file).with_name("struct_cleaned.json")
    FileHandler.save_json(cleaned_data, output_path)
    logger.info(f"Phase 3.1 完成。保存至: {output_path}")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE3.1.log')
    try:
        main()
    except Exception as e:
        logger.critical("Phase 3.1 崩溃", exc_info=True)
        sys.exit(1)