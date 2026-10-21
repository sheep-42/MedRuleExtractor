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

EXCLUDE_FILES = {
    "index.json", "merged_output.json", "成份.json", 
    "药品名称.json", "不良反应.json", "phase1_labels_validated.json",
    "phase1_labels_validation_logs.json", "phase1_validation_log.json",
    "phase1_valuable_output.json"
}

def merge_json_files(directory_path: Path):
    merged_data = []
    segment_counter = 1
    directory_path = Path(directory_path)

    if not directory_path.exists():
        logger.error(f"目录不存在: {directory_path}")
        return

    # 获取目录下所有 json 文件
    files = sorted([f for f in directory_path.iterdir() if f.suffix == '.json'])

    for file_path in files:
        if file_path.name in EXCLUDE_FILES:
            continue

        try:
            data = FileHandler.load_json(file_path)
            # 简单校验数据格式
            if not isinstance(data, list):
                logger.warning(f"文件 {file_path.name} 格式不是列表，跳过")
                continue

            file_label = f"【{file_path.stem}】"
            
            for item in data:
                if not isinstance(item, dict): continue
                
                # 添加板块标题到原文
                original_content = item.get("原文内容", "")
                if not original_content.startswith(file_label):
                    item["原文内容"] = f"{file_label}\n\n{original_content}"
                
                # 重新编号
                item["段编号"] = str(segment_counter)
                segment_counter += 1
                
                if item.get("标签预测"): # 只保留有标签的数据
                    merged_data.append(item)

        except Exception as e:
            logger.error(f"处理文件 {file_path.name} 时出错: {e}")

    output_path = directory_path.parent / "sections_merged.json"
    FileHandler.save_json(merged_data, output_path, indent=4)
    logger.info(f"合并完成，共 {len(merged_data)} 条数据，保存至: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Phase 1.1: 合并 JSON")
    parser.add_argument("--dir_path", type=str, required=True, help="sections 目录路径")
    args = parser.parse_args()
    
    merge_json_files(args.dir_path)

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE1.1.log')
    try:
        main()
    except Exception as e:
        logger.critical("合并过程中发生严重错误", exc_info=True)
        sys.exit(1)