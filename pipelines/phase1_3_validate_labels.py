import sys
import argparse
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

logger = logging.getLogger(__name__)

# 假设 PG_select 位于同级目录
try:
    from PG_select import load_examples_for_prompt
except ImportError:
    # 简单的 mock，以防文件不存在时不中断基本流程（可选）
    logger.warning("PG_select 模块未找到，Few-shot 示例将不可用。")
    def load_examples_for_prompt(**kwargs): return ""

from core.config_mgr import load_global_config
from core.log_mgr import setup_logging
from core.file_handler import FileHandler
from core.llm_handler import LLMHandler

# --- 常量 ---
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
DEFINITIONS_PATH = BASE_DIR / "prompts" / "definitions.json"
PROMPT_PATH = BASE_DIR / "prompts" / "phase1" / "审核项判断.txt"
MODEL_KEY_VALIDATION = 'model_phase1_2'

def load_definitions(path: Path):
    """加载定义文件并转换为 Dict[label, definition]"""
    raw_data = FileHandler.load_json(path)
    definitions = {}
    for item in raw_data:
        if isinstance(item, dict):
            definitions.update(item)
    return definitions

def validate_label(
    llm: LLMHandler, 
    text: str, 
    label: str, 
    definition: str, 
    prompt_template: str, 
    model_name: str
):
    """验证单个 (文本, 标签) 对的正确性"""
    
    # 1. 业务规则过滤
    if "不良反应" in label:
        return None, {"text": text, "label": label, "result": "skipped", "reason": "Skip rule"}

    # 2. 准备 Few-shot
    examples = load_examples_for_prompt(stage=1, label_tuples=[("审核项", label)])
    example_block = f"\n---\n【参考示例】\n{examples}\n" if examples else ""

    # 3. 构造 Prompt
    prompt = prompt_template.format(
        text=text, label=label, definition=definition, examples=example_block
    )

    # 4. 调用 LLM
    fallback = {"判断": "错误", "理由": "LLM Error", "原文内容": text, "审核项": label}
    result = llm.chat_completion_json(
        prompt=prompt,
        model=model_name,
        expected_type=dict,
        temperature=0.1,
        fallback_data=fallback
    )

    is_correct = result.get("判断") == "正确"
    reason = result.get("理由", "无理由")

    # 构造返回结果
    if is_correct:
        # 验证通过，返回标准化数据结构
        output_item = {"原文内容": text, "标签预测": label}
    else:
        output_item = None

    log_entry = {
        "原文内容": text,
        "审核项": label,
        "判断": result.get("判断"),
        "理由": reason,
        "prompt_snapshot": prompt[:200] + "..." 
    }
    
    return output_item, log_entry

def main():
    parser = argparse.ArgumentParser(description="Phase 1.3: 标签正确性验证")
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--definitions_file", type=str, default=str(DEFINITIONS_PATH))
    parser.add_argument("--prompt_file", type=str, default=str(PROMPT_PATH))
    parser.add_argument("--config_path", type=str, default=str(CONFIG_PATH))
    args = parser.parse_args()

    # 1. 初始化
    config = load_global_config(args.config_path)
    llm = LLMHandler(config)
    model_name = config['openai'].get(MODEL_KEY_VALIDATION)
    if not model_name:
        logger.error(f"配置中缺少 {MODEL_KEY_VALIDATION}")
        return

    # 2. 加载数据
    definitions = load_definitions(Path(args.definitions_file))
    prompt_template = FileHandler.read_text(args.prompt_file)
    data = FileHandler.load_json(args.input_file)

    validated_results = []
    validation_logs = []

    # 3. 处理循环
    logger.info(f"开始验证标签，共 {len(data)} 个段落...")
    
    for item in data:
        text = item.get("原文内容")
        labels = item.get("标签预测", [])
        
        if not text or not labels: continue

        # 这里的逻辑有变化：原数据是一对多(一个文本多个标签)，验证后拆分为一对一
        # 这是为了更精细的控制
        for label in labels:
            defn = definitions.get(label)
            if not defn:
                logger.warning(f"未找到标签定义: {label}，跳过")
                continue

            valid_item, log = validate_label(
                llm, text, label, defn, prompt_template, model_name
            )
            
            validation_logs.append(log)
            if valid_item:
                validated_results.append(valid_item)

    # 4. 保存
    input_path = Path(args.input_file)
    output_dir = input_path.parent
    
    FileHandler.save_json(validated_results, output_dir / "sections_merged_labels_validated.json")
    FileHandler.save_json(validation_logs, output_dir / "sections_merged_labels_validated_logs.json")

    logger.info(f"Phase 1.3 完成。有效条目: {len(validated_results)}")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE1.3.log')
    try:
        main()
    except Exception as e:
        logger.critical("Phase 1.3 执行失败", exc_info=True)
        sys.exit(1)