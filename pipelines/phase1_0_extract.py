import sys
import argparse
import logging
from pathlib import Path

# 将项目根目录加入 sys.path 以便导入 core
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from core.config_mgr import load_global_config
from core.log_mgr import setup_logging
from core.file_handler import FileHandler, TextUtils
from core.llm_handler import LLMHandler

logger = logging.getLogger(__name__)

# --- 常量定义 ---
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
MODEL_KEY_PHASE1 = 'model_phase1'

def handle_special_case_section(seg_title: str, seg_text: str):
    """处理特殊规则板块（如适应症），不消耗 Token"""
    logger.info(f"正在处理特殊板块: 【{seg_title}】")
    data = [{
        "段编号": "1",
        "原文内容": seg_text,
        "标签预测": ["适应症"]
    }]
    summary = {
        "板块": seg_title,
        "length": len(seg_text),
        "处理方式": "特殊规则",
        "结果条数": len(data),
        "原文预览": seg_text[:50].replace("\n", " ").strip()
    }
    return data, summary

def handle_generic_section(
    llm: LLMHandler,
    seg_title: str, 
    seg_text: str, 
    drug_name: str, 
    prompt_dir: Path
):
    """处理常规板块，调用 LLM"""
    logger.info(f"正在处理常规板块: 【{seg_title}】 (调用LLM)")
    prompt_path = prompt_dir / f"{seg_title}.txt"

    if not prompt_path.exists():
        logger.warning(f"跳过: 未找到提示词文件 {prompt_path}")
        return [], {"板块": seg_title, "处理方式": "跳过(无Prompt)", "结果条数": 0}

    prompt_template = FileHandler.read_text(prompt_path)
    prompt = prompt_template.format(drug_name=drug_name, text=seg_text)

    # 调用核心 LLM 处理器，期望返回 List[Dict]
    # fallback_data 用于在出错时保留原文信息
    fallback = {"原文内容": seg_text, "error": "Processing Failed"}
    
    result = llm.chat_completion_json(
        prompt=prompt,
        expected_type=list,
        temperature=0.1,
        fallback_data=fallback
    )

    summary = {
        "板块": seg_title,
        "length": len(seg_text),
        "处理方式": "LLM调用",
        "结果条数": len(result) if isinstance(result, list) else 0,
        "原文预览": seg_text[:50].replace("\n", " ").strip()
    }
    return result, summary

def main():
    parser = argparse.ArgumentParser(description="Phase 1.0: 结构化提取")
    PROMPT_DIR = BASE_DIR / "prompts" / "phase1" / "板块"
    parser.add_argument("--input_file", type=str, required=True, help="Markdown文件路径")
    parser.add_argument("--output_dir", type=str, required=True, help="输出目录")
    parser.add_argument("--prompt-dir", type=str, default=str(PROMPT_DIR))
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    args = parser.parse_args()

    # 1. 初始化
    config = load_global_config(args.config_path)
    llm = LLMHandler(config=config, phase=MODEL_KEY_PHASE1) # 自动加载 'model_phase1'
    # 如果 config 中指定的 model_phase1 不是我们想要的，可以在调用时覆盖，或者这里不做处理默认使用配置

    save_dir = Path(args.output_dir)
    prompt_dir = Path(args.prompt_dir)

    # 2. 读取与切分
    instruction_text = FileHandler.read_text(args.input_file)
    drug_name = Path(args.input_file).stem
    
    # 使用 TextUtils 切分
    raw_segments = TextUtils.split_by_marker(instruction_text)
    segments = [
        {"title": TextUtils.extract_title(seg), "text": seg[2:].strip()}
        for seg in raw_segments if seg.strip()
    ]

    logger.info(f"开始处理药品: {drug_name}, 共 {len(segments)} 个板块")

    # 3. 循环处理
    index_summary = []
    
    for seg in segments:
        title_clean = seg["title"].replace("【", "").replace("】", "")
        text = seg["text"]

        if title_clean == "适应症":
            processed_data, summary = handle_special_case_section(title_clean, text)
        else:
            # 可以在这里显式传入 model=config['openai']['model_phase1']，也可以依赖 LLMHandler 默认值
            processed_data, summary = handle_generic_section(
                llm, title_clean, text, drug_name, prompt_dir
            )
        
        index_summary.append(summary)

        if processed_data:
            FileHandler.save_json(processed_data, save_dir / f"{title_clean}.json")

    # 4. 保存索引
    FileHandler.save_json(index_summary, save_dir / "index.json")
    logger.info("Phase 1.0 完成")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE1.0.log')
    try:
        main()
    except Exception as e:
        logger.critical("未捕获的异常", exc_info=True)
        sys.exit(1)