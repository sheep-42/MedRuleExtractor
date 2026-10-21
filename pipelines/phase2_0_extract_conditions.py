import sys
import argparse
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# 假设 PG_select 存在
try:
    from PG_select import load_examples_for_prompt
except ImportError:
    def load_examples_for_prompt(**kwargs): return ""

from core.config_mgr import load_global_config
from core.log_mgr import setup_logging
from core.file_handler import FileHandler
from core.llm_handler import LLMHandler

logger = logging.getLogger(__name__)

# --- 常量 ---
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
PROMPT_PATH = BASE_DIR / "prompts" / "phase2" / "前提条件.txt"
MODEL_KEY_PHASE2 = 'model_phase2'

def extract_condition(
    llm: LLMHandler, 
    item: dict, 
    prompt_template: str, 
    model_name: str
):
    """提取单条数据的前提条件"""
    text = item.get("原文内容")
    label = item.get("标签预测") # Phase 1.3 输出的是 "标签预测"

    if not text or not label:
        return None, None

    # 业务规则：跳过不良反应
    if "不良反应" in label:
        return None, None
    
    # 业务规则：适应症无前提条件
    if "适应症" in label:
        result = {"原文内容": text, "审核项": label, "前提条件": []}
        return result, {"prompt": "Skipped (Indication)", "result": result}

    # 准备 Few-shot
    examples = load_examples_for_prompt(stage=2, label_tuples=[("审核项", label)])
    example_block = f"\n---\n【参考示例】\n{examples}\n" if examples else ""

    # 调用 LLM
    prompt = prompt_template.format(text=text, label=label, examples=example_block)
    fallback = {"原文内容": text, "审核项": label, "前提条件": []}
    
    llm_resp = llm.chat_completion_json(
        prompt=prompt,
        model=model_name,
        expected_type=dict,
        temperature=0.1,
        fallback_data=fallback
    )

    # 构造标准结果
    # 注意：Phase 1.3 输出的 key 是 "标签预测"，Phase 2 输出改为 "审核项" 以符合后续流程
    processed_result = {
        "原文内容": text,
        "审核项": label,
        "前提条件": llm_resp.get("前提条件", [])
    }
    
    # 保留错误信息以便排查
    if "error" in llm_resp:
        processed_result["错误信息"] = llm_resp.get("错误信息") or llm_resp

    log_entry = {
        "prompt": prompt[:200] + "...",
        "raw_response": llm_resp
    }

    return processed_result, log_entry

def main():
    parser = argparse.ArgumentParser(description="Phase 2.0: 前提条件提取")
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--prompt_file", type=str, default=str(PROMPT_PATH))
    parser.add_argument("--config_path", type=str, default=str(CONFIG_PATH))
    args = parser.parse_args()

    # 1. 初始化
    config = load_global_config(args.config_path)
    llm = LLMHandler(config)
    model_name = config['openai'].get(MODEL_KEY_PHASE2)
    
    if not model_name:
        logger.error(f"配置缺失: {MODEL_KEY_PHASE2}")
        return

    # 2. 加载资源
    data = FileHandler.load_json(args.input_file)
    prompt_tpl = FileHandler.read_text(args.prompt_file)

    results = []
    logs = []

    # 3. 执行
    logger.info(f"开始提取前提条件，共 {len(data)} 条...")
    for i, item in enumerate(data):
        res, log = extract_condition(llm, item, prompt_tpl, model_name)
        if res:
            results.append(res)
            logs.append(log)
        
        if (i+1) % 50 == 0:
            logger.info(f"已处理 {i+1} 条...")

    # 4. 自动计算输出路径 (stage_1 -> stage_2)
    input_dir = Path(args.input_file).parent
    # 简单的路径替换逻辑，假定目录结构标准
    # 如果 input_dir 是 .../stage_1/abc.json，则 output_dir 为 .../stage_2/
    if 'stage_1' in str(input_dir):
        output_dir = Path(str(input_dir).replace('stage_1', 'stage_2'))
    else:
        # 如果路径不标准，则在该目录下新建 stage_2
        output_dir = input_dir.parent / "stage_2"
    
    FileHandler.save_json(results, output_dir / "conditions.json")
    FileHandler.save_json(logs, output_dir / "conditions_logs.json")
    
    logger.info(f"Phase 2.0 完成。结果保存在: {output_dir}")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE2.0.log')
    try:
        main()
    except Exception as e:
        logger.critical("Phase 2.0 崩溃", exc_info=True)
        sys.exit(1)