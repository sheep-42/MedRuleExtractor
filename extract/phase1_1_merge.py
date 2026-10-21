import json
import os
import argparse
from pathlib import Path
import logging
from logging_config import setup_logging

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"

def merge_json_files_in_directory(directory_path):
    directory_path = Path(directory_path)
    merged_data = []
    segment_counter = 1  # 初始化段编号计数器

    # 要排除的文件名列表
    exclude_files = [
        "index.json",
        "merged_output.json",
        "成份.json",
        "药品名称.json",
        "不良反应.json",
        "phase1_labels_validated.json",
        "phase1_labels_validation_logs.json",
        "phase1_validation_log.json",
        "phase1_valuable_output.json"
    ]

    for filename in os.listdir(directory_path):
        if filename in exclude_files:
            logger.info(f"跳过 {filename} 文件")
            continue

        if not filename.endswith(".json"):
            logger.info(f"跳过非 JSON 文件：{filename}")
            continue

        file_path = directory_path / filename
        with open(file_path, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
                # 文件名前后加【】，去除 .json 后缀
                file_label = f"【{filename[:-5]}】"
                for item in data:
                    if item.get("标签预测"):
                        # 修改原文内容
                        original_content = item.get("原文内容", "")
                        if not original_content.startswith(file_label):
                            item["原文内容"] = file_label + "\n\n" + original_content
                        item["段编号"] = str(segment_counter)
                        segment_counter += 1
                        merged_data.append(item)
            except json.JSONDecodeError as e:
                logger.error(f"无法解析文件 {filename}: {e}", exc_info=True)

    output_file_path = directory_path.parent / "sections_merged.json"
    with open(output_file_path, "w", encoding="utf-8") as output_file:
        json.dump(merged_data, output_file, ensure_ascii=False, indent=4)

    logger.info(f"合并完成，输出文件： {output_file_path}")


if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE1.1.log')
    parser = argparse.ArgumentParser(description="合并说明书 JSON 文件")
    parser.add_argument("--dir_path", type=str, required=True, help="包含 JSON 文件的目标目录路径")
    args = parser.parse_args()

    merge_json_files_in_directory(args.dir_path)

# python extract/phase1_merge.py --dir_path "./results/氟唑帕利胶囊/run_001/stage_1/sections"
