import subprocess
import argparse
import logging
from logging_config import setup_logging
import sys
import os
from pathlib import Path
import glob
import sys

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"

# --- 工作流阶段定义 ---
PIPELINE_STAGES = [
    {
        "name": "phase1.0",
        "script_name": "phase1_0_extract.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase1_0_extract.py")),
        "description": "提取板块信息",
        "input_from": None,
        "stage_num": 1,
        "get_args": lambda input_path, output_dir: ["--input_file", input_path, "--output_dir", str(output_dir / "stage_1" / "sections")]
    },
    {
        "name": "phase1.1",
        "script_name": "phase1_1_merge.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase1_1_merge.py")),
        "description": "合并第一阶段结果",
        "input_from": "phase1.0",
        "stage_num": 1,
        "get_args": lambda input_path, _: ["--dir_path", str(Path(input_path).parent)]
    },
    {
        "name": "phase1.2",
        "script_name": "phase1_2_validate_schema.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase1_2_validate_schema.py")),
        "description": "验证内容价值",
        "input_from": "phase1.1",
        "stage_num": 1,
        "get_args": lambda input_path, _: ["--input_file", input_path]
    },
    {
        "name": "phase1.3",
        "script_name": "phase1_3_validate_labels.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase1_3_validate_labels.py")),
        "description": "验证标签正确性",
        "input_from": "phase1.2",
        "stage_num": 1,
        "get_args": lambda input_path, _: ["--input_file", input_path]
    },
    {
        "name": "phase2.0",
        "script_name": "phase2_0_extract_conditions.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase2_0_extract_conditions.py")),
        "description": "提取前提条件",
        "input_from": "phase1.3",
        "stage_num": 2,
        "get_args": lambda input_path, _: ["--input_file", input_path]
    },
    {
        "name": "phase2.1",
        "script_name": "phase2_1_validate_rules.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase2_1_validate_rules.py")),
        "description": "应用规则验证前提条件",
        "input_from": "phase2.0",
        "stage_num": 2,
        "get_args": lambda input_path, _: ["--input_file", input_path]
    },
    {
        "name": "phase3.0",
        "script_name": "phase3_0_extract_struct.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase3_0_extract_struct.py")),
        "description": "结构化字段提取",
        "input_from": "phase2.1",
        "stage_num": 3,
        "get_args": lambda input_path, _: ["--input_file", input_path]
    },
    {
        "name": "phase3.1",
        "script_name": "phase3_1_filter_clean.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase3_1_filter_clean.py")),
        "description": "过滤和清理结构化数据",
        "input_from": "phase3.0",
        "stage_num": 3,
        "get_args": lambda input_path, _: ["--input_file", input_path]
    },
    {
        "name": "phase3.2",
        "script_name": "phase3_2_postprocess.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase3_2_postprocess.py")),
        "description": "最终验证和合并",
        "input_from": "phase3.1",
        "stage_num": 3,
        "get_args": lambda input_path, _: ["--input_file", input_path]
    },
    {
        "name": "phase3.3", 
        "script_name": "phase3_3_validate_rules.py",  
        "script_path": str(BASE_DIR.joinpath("extract", "phase3_3_validate_rules.py")),  
        "description": "结构化结果规则验证",  
        "input_from": "phase3.2",
        "stage_num": 3, 
        "get_args": lambda input_path, _: ["--input_file", input_path]
    },
    {
        "name": "phase4.0",
        "script_name": "phase4_0_normalize.py",
        "script_path": str(BASE_DIR.joinpath("extract", "phase4_0_normalize.py")),
        "description": "字段规范化",
        "input_from": "phase3.3",
        "stage_num": 4,
        "get_args": lambda input_path, _: ["--input_file", input_path]
    }
]

# --- 辅助函数 ---
def run_script(script_path, *args):
    """
    实时运行指定的 Python 脚本，并将其输出流式传输到当前终端。
    """
    command = [sys.executable, script_path] + list(args)
    logger.info(f"执行命令: {' '.join(command)}")
    try:
        process = subprocess.run(
            command,
            check=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        return process
    except subprocess.CalledProcessError as e:
        logger.error(f"命令执行失败: {' '.join(e.cmd)}")
        logger.error(f"返回码: {e.returncode}")
        logger.error("请检查上面由子脚本直接打印的错误日志。")
        raise

# (get_output_file 函数保持不变)
from pathlib import Path

def get_output_file(script_name: str, input_file: str, current_run_dir: Path) -> str:
    """
    根据脚本名称和当前运行目录，推断输出文件路径。
    遵循新的命名规范。

    Args:
        script_name: 执行的脚本文件名 (例如 'phase1_0_extract.py').
        input_file: 当前脚本的输入文件路径 (主要用于定位 stage 目录).
        current_run_dir: 本次运行的根目录 (例如 '.../results/药品名/run_001').

    Returns:
        推断出的输出文件绝对路径字符串。
    """
    # --- Phase 1 ---
    if script_name == "phase1_0_extract.py":
        # extract 的产物是一个目录，我们返回其下的 index.json 作为后续步骤的输入信标
        output_dir = current_run_dir / "stage_1" / "sections"
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / "index.json")
    
    elif script_name == "phase1_1_merge.py":
        # merge 的产物在 stage_1 目录下
        output_dir = current_run_dir / "stage_1"
        return str(output_dir / "sections_merged.json")

    elif script_name == "phase1_2_validate_schema.py":
        output_dir = current_run_dir / "stage_1"
        return str(output_dir / "sections_merged_schema_validated.json")

    elif script_name == "phase1_3_validate_labels.py":
        output_dir = current_run_dir / "stage_1"
        # 这是阶段1的最终产物，也是阶段2的输入
        return str(output_dir / "sections_merged_labels_validated.json")

    # --- Phase 2 ---
    elif script_name == "phase2_0_extract_conditions.py":
        output_dir = current_run_dir / "stage_2"
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / "conditions.json")

    elif script_name == "phase2_1_validate_rules.py":
        output_dir = current_run_dir / "stage_2"
        # 这是阶段2的最终产物，也是阶段3的输入
        return str(output_dir / "conditions_rules_validated.json")

    # --- Phase 3 ---
    elif script_name == "phase3_0_extract_struct.py":
        output_dir = current_run_dir / "stage_3"
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / "struct_raw.json")

    elif script_name == "phase3_1_filter_clean.py":
        output_dir = current_run_dir / "stage_3"
        return str(output_dir / "struct_cleaned.json")

    elif script_name == "phase3_2_postprocess.py":
        output_dir = current_run_dir / "stage_3"
        return str(output_dir / "struct_postprocessed.json")
    
    elif script_name == "phase3_3_validate_rules.py":
        output_dir = current_run_dir / "stage_3"
        # 修正2：生成独立输出文件（而非复用上游结果）
        return str(output_dir / "struct_validated_rules.json")

    # --- Phase 4 ---
    elif script_name == "phase4_0_normalize.py":
        output_dir = current_run_dir / "stage_4"
        output_dir.mkdir(parents=True, exist_ok=True)
        # 这是整个工作流的最终产物
        return str(output_dir / "struct_final_normalized.json")

    else:
        raise ValueError(f"未知的脚本名称，无法推断输出文件: {script_name}")


def main():
    parser = argparse.ArgumentParser(
        description="运行医学规则提取工作流",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--input_file", type=str, required=True, help="待处理的说明书 Markdown 文件路径")
    parser.add_argument(
        "--output-dir-name",
        type=str,
        required=True,
        help="本次运行的结果将保存在 'results/<output-dir-name>' 目录下"
    )
    parser.add_argument("--start-from", type=str, default=None, help="指定开始的阶段 (例如: 'phase1.0')")
    parser.add_argument("--end-at", type=str, default=None, help="指定结束的阶段 (可选, 包含此阶段)")

    args = parser.parse_args()

    # --- 目录和路径设置 ---
    input_file = Path(args.input_file)
    results_base_dir = Path("./results")
    current_run_dir = results_base_dir / args.output_dir_name
    logging.info(f"本次运行结果将保存到: {current_run_dir}")
    current_run_dir.mkdir(parents=True, exist_ok=True) # 确保目录存在

    # --- 工作流执行 ---
    stage_outputs = {"initial": str(input_file)}
    stage_names = [s["name"] for s in PIPELINE_STAGES]
    start_index = 0

    if args.start_from:
        if args.start_from not in stage_names:
            logging.error(f"错误: 未知的起始阶段名称 '{args.start_from}'。可用阶段: {', '.join(stage_names)}")
            sys.exit(1)
        start_index = stage_names.index(args.start_from)
    if start_index > 0:
        logging.info(f"从阶段 [{args.start_from}] 开始，正在推算之前阶段的输出路径...")
        # 循环遍历所有在 start_index 之前的阶段
        for j in range(start_index):
            skipped_stage = PIPELINE_STAGES[j]
            skipped_stage_name = skipped_stage["name"]

            # 确定这个被跳过阶段的输入
            if skipped_stage["input_from"]:
                # 它的输入应该已经存在于 stage_outputs 中了
                if skipped_stage["input_from"] not in stage_outputs:
                    # 这是一个逻辑矛盾，说明 pipeline 定义有问题，提前报错
                    logging.error(f"逻辑错误：无法推算 {skipped_stage_name} 的输入，因为 {skipped_stage['input_from']} 的输出未知。")
                    sys.exit(1)
                input_for_skipped = stage_outputs[skipped_stage["input_from"]]
            else: # 第一个阶段
                input_for_skipped = stage_outputs["initial"]
            
            # 计算并存储这个被跳过阶段的理论输出路径
            stage_outputs[skipped_stage_name] = get_output_file(
                skipped_stage["script_name"],
                input_for_skipped,
                current_run_dir
            )
            logging.info(f"  -> 推断 {skipped_stage_name} 的输出为: {stage_outputs[skipped_stage_name]}")

    end_index = len(PIPELINE_STAGES) - 1
    if args.end_at:
        if args.end_at not in stage_names:
            logging.error(f"错误: 未知的结束阶段名称 '{args.end_at}'。可用阶段: {', '.join(stage_names)}")
            sys.exit(1)
        end_index = stage_names.index(args.end_at)
    
    if start_index > end_index:
        logging.error("错误: 起始阶段不能在结束阶段之后。")
        sys.exit(1)

    # --- 循环执行管线 ---
    for i in range(start_index, end_index + 1):
        stage = PIPELINE_STAGES[i]
        stage_name = stage["name"]
        logging.info("-" * 60)

        # 确定当前阶段的输入
        if stage["input_from"]:
            # 经过上面的填充，这里现在应该是安全的
            input_path = stage_outputs[stage["input_from"]]
        else: # 第一个阶段
            input_path = stage_outputs["initial"]

        # 验证输入文件是否存在 (只对真实执行的第一个阶段进行)
        if i == start_index and stage["input_from"]:
            logging.info(f"从阶段 [{stage_name}] 继续，检查输入文件: {input_path}")
            if not Path(input_path).exists():
                logging.error(f"错误: 无法继续，因为起始阶段所需的输入文件不存在: {input_path}")
                sys.exit(1)

        # 执行当前阶段
        logging.info(f"执行阶段 {i+1-start_index}/{end_index-start_index+1}: [{stage_name}] {stage['description']}")
        logging.info(f"输入文件: {input_path}")

        script_args = stage["get_args"](input_path, current_run_dir)
        try:
            run_script(stage["script_path"], *script_args)
        except subprocess.CalledProcessError:
            logging.error(f"阶段 {stage_name} 执行失败。工作流中断。")
            sys.exit(1)
        
        # 计算并存储当前阶段的输出，为下一阶段做准备
        output_path = get_output_file(
            stage["script_name"],
            input_path,
            current_run_dir
        )
        stage_outputs[stage_name] = output_path
        logging.info(f"阶段 {stage_name} 完成。输出保存到: {output_path}")
    
    # 循环结束后的最终日志
    logging.info("=" * 60)
    if args.end_at and end_index < len(PIPELINE_STAGES) - 1:
        logging.info(f"工作流已在指定的结束阶段 [{args.end_at}] 成功执行后停止。")
    else:
        logging.info("工作流全部阶段执行完成!")
    logging.info("=" * 60)


if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PIPELINE.log')
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

# --- 使用示例 ---
# 1. 从头开始，到 phase1.3 结束
# python run_pipeline.py --input_file "path/to/input.md" --end-at phase1.3

# 2. 从 phase1.1 开始，到 phase2.1 结束 (需要指定 run_number)
# python run_pipeline.py --input_file "path/to/input.md" --start-from phase1.1 --run-number 1 --end-at phase2.1