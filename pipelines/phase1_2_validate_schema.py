import sys
import argparse
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from core.config_mgr import load_global_config
from core.log_mgr import setup_logging
from core.file_handler import FileHandler
from core.llm_handler import LLMHandler

logger = logging.getLogger(__name__)

# --- 常量 ---
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
PROMPT_PATH = BASE_DIR / "prompts" / "phase1" / "无价值段落检测.txt"
MODEL_KEY_VALIDATION = 'model_phase1_1' # 注意：这里使用特定的模型键名

VALIDATION_REQUIRED_LABELS = {
    '相互作用', '特殊人群-年龄', '特殊人群-肾功能', 
    '特殊人群-肝功能', '特殊人群-妊娠', '特殊人群-哺乳', '特殊人群-性别'
}

def validate_item(llm: LLMHandler, item: dict, prompt_template: str, model_name: str):
    """
    对单个数据项进行验证。
    如果标签属于 VALIDATION_REQUIRED_LABELS，则调用 LLM 判断是否缺乏特殊指令。
    """
    text = item.get("原文内容", "")
    labels = item.get("标签预测", [])
    
    # 判断是否需要验证
    needs_validation = bool(set(labels) & VALIDATION_REQUIRED_LABELS)
    
    if not needs_validation:
        return item, {"原文内容": text, "标签预测": labels, "是否丢弃": False, "理由": "无需验证"}

    # 调用 LLM
    prompt = prompt_template.format(text=text)
    fallback = {"是否缺乏特殊指令": False, "理由": "LLM调用失败，默认保留"}
    
    result = llm.chat_completion_json(
        prompt=prompt,
        model=model_name,
        expected_type=dict,
        temperature=0.01,
        fallback_data=fallback
    )

    # 逻辑：如果 "是否缺乏特殊指令" 为 True，则丢弃
    should_discard = result.get("是否缺乏特殊指令", False)
    reason = result.get("理由", "无理由")

    log_entry = {
        "原文内容": text,
        "标签预测": labels,
        "是否丢弃": should_discard,
        "理由": reason
    }

    return (None if should_discard else item), log_entry

def main():
    parser = argparse.ArgumentParser(description="Phase 1.2: 无价值段落检测")
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--prompt_path", type=str, default=str(PROMPT_PATH))
    parser.add_argument("--config_path", type=str, default=str(CONFIG_PATH))
    args = parser.parse_args()

    # 1. 初始化
    config = load_global_config(args.config_path)
    llm = LLMHandler(config)
    
    # 获取特定阶段的模型名称
    model_name = config['openai'].get(MODEL_KEY_VALIDATION)
    if not model_name:
        logger.error(f"配置中缺少 {MODEL_KEY_VALIDATION}")
        return

    # 2. 加载资源
    prompt_template = FileHandler.read_text(args.prompt_path)
    data = FileHandler.load_json(args.input_file)

    valuable_results = []
    validation_logs = []

    # 3. 批处理
    logger.info(f"开始验证 {len(data)} 条数据...")
    for i, item in enumerate(data):
        valid_item, log = validate_item(llm, item, prompt_template, model_name)
        
        validation_logs.append(log)
        if valid_item:
            valuable_results.append(valid_item)
        
        if (i+1) % 10 == 0:
            logger.info(f"已处理 {i+1}/{len(data)}...")

    # 4. 保存
    input_path = Path(args.input_file)
    output_dir = input_path.parent
    
    FileHandler.save_json(valuable_results, output_dir / "sections_merged_schema_validated.json")
    FileHandler.save_json(validation_logs, output_dir / "sections_merged_schema_validated_log.json")
    
    logger.info(f"Phase 1.2 完成。保留: {len(valuable_results)}, 丢弃: {len(data) - len(valuable_results)}")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE1.2.log')
    try:
        main()
    except Exception as e:
        logger.critical("执行失败", exc_info=True)
        sys.exit(1)