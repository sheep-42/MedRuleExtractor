import sys
import argparse
import logging
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# 尝试导入 PG_select，如果不存在则使用 mock
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
STRUCTURE_FILE = BASE_DIR / "prompts" / "table_structure_updated.json"
PROMPT_WITH_COND = BASE_DIR / "prompts" / "phase3" / "结构化字段抽取_有前提.txt"
PROMPT_NO_COND = BASE_DIR / "prompts" / "phase3" / "结构化字段抽取_无前提.txt"
MODEL_KEY_PHASE3 = 'model_phase3'

def extract_struct(
    llm: LLMHandler, 
    item: dict, 
    model_name: str,
    prompt_tpl_yes: str, 
    prompt_tpl_no: str,
    remark_to_table: dict,
    drug_name: str
):
    """提取单条数据的结构化字段"""
    text = item.get("原文内容", "")
    main_label = item.get("审核项", "")
    condition_labels = item.get("前提条件", [])

    if not text or not main_label:
        return None, None

    # 获取表定义
    main_table = remark_to_table.get(main_label)
    if not main_table:
        logger.warning(f"未知审核项 '{main_label}'，跳过")
        return None, None

    # 准备字段定义 JSON
    # 核心字段定义
    main_fields_def = json.dumps({main_table["表名"]: main_table.get("字段", {})}, ensure_ascii=False, indent=2)
    
    # 前提条件表定义
    condition_tables = [remark_to_table[cl] for cl in condition_labels if cl in remark_to_table]
    
    # 准备 Few-shot 示例
    label_tuples = [("审核项", main_label)] + [("前提条件", cl) for cl in condition_labels]
    examples = load_examples_for_prompt(stage=3, label_tuples=label_tuples)
    example_block = f"\n---\n【参考示例】\n{examples}\n" if examples else ""

    # 选择提示词模板并填充
    if condition_tables:
        cond_fields_def = json.dumps(
            {t["表名"]: t.get("字段", {}) for t in condition_tables}, 
            ensure_ascii=False, indent=2
        )
        cond_labels_str = [t["备注"] for t in condition_tables] # List[str] 会被转化为字符串表示
        prompt = prompt_tpl_yes.format(
            drug_name=drug_name, text=text, main_label=main_label, 
            main_fields=main_fields_def, condition_labels=cond_labels_str, 
            condition_fields=cond_fields_def, examples=example_block
        )
    else:
        prompt = prompt_tpl_no.format(
            drug_name=drug_name, text=text, main_label=main_label, 
            main_fields=main_fields_def, examples=example_block
        )

    # 调用 LLM
    fallback = {
        "原文内容": text, "审核项": main_label, "前提条件": condition_labels,
        "结构化结果": {}
    }
    
    llm_resp = llm.chat_completion_json(
        prompt=prompt,
        model=model_name,
        expected_type=dict,
        temperature=0.1,
        fallback_data=fallback
    )

    # 构造结果
    # 注意：LLMHandler 已经处理了解析错误，如果出错 llm_resp 会包含 error 字段
    # 这里我们只提取有效的结构化部分
    final_result = {
        "原文内容": text,
        "审核项": main_label,
        "前提条件": condition_labels,
        "结构化结果": llm_resp # 直接保存 LLM 返回的完整字典 (通常包含 "结构": [...])
    }

    # 如果有错误，保留错误信息
    if "error" in llm_resp:
         final_result["错误信息"] = llm_resp

    log_entry = {
        "prompt": prompt[:300] + "...",
        "response": llm_resp
    }

    return final_result, log_entry

def main():
    parser = argparse.ArgumentParser(description="Phase 3.0: 结构化字段提取")
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--structure-file", type=str, default=str(STRUCTURE_FILE))
    parser.add_argument("--prompt-with-cond", type=str, default=str(PROMPT_WITH_COND))
    parser.add_argument("--prompt-no-cond", type=str, default=str(PROMPT_NO_COND))
    parser.add_argument("--config_path", type=str, default=str(CONFIG_PATH))
    args = parser.parse_args()

    # 1. 初始化
    config = load_global_config(args.config_path)
    llm = LLMHandler(config)
    model_name = config['openai'].get(MODEL_KEY_PHASE3)
    
    if not model_name:
        logger.error(f"配置缺失: {MODEL_KEY_PHASE3}")
        return

    # 2. 加载资源
    data = FileHandler.load_json(args.input_file)
    table_structures = FileHandler.load_json(args.structure_file)
    prompt_yes = FileHandler.read_text(args.prompt_with_cond)
    prompt_no = FileHandler.read_text(args.prompt_no_cond)

    # 构建查找表：备注名 -> 表定义
    remark_to_table = {entry["备注"]: entry for entry in table_structures}

    # 获取药品名称 (假设目录结构为 .../DrugName/stage_2/...)
    drug_name = Path(args.input_file).parent.parent.name
    # 或者如果不确定目录结构，可以用 Path(args.input_file).parts[...] 尝试获取，这里保留原逻辑的变体
    if "run_" in drug_name: # 简单的fallback
        drug_name = "未识别药品"

    results = []
    logs = []

    # 3. 执行
    logger.info(f"开始提取结构化字段，共 {len(data)} 条...")
    for i, item in enumerate(data):
        res, log = extract_struct(
            llm, item, model_name, prompt_yes, prompt_no, remark_to_table, drug_name
        )
        if res:
            results.append(res)
            logs.append(log)
        
        if (i+1) % 20 == 0:
            logger.info(f"已处理 {i+1} 条...")

    # 4. 保存 (stage_2 -> stage_3)
    input_dir = Path(args.input_file).parent
    if 'stage_2' in str(input_dir):
        output_dir = Path(str(input_dir).replace('stage_2', 'stage_3'))
    else:
        output_dir = input_dir.parent / "stage_3"
    
    FileHandler.save_json(results, output_dir / "struct_raw.json")
    FileHandler.save_json(logs, output_dir / "struct_raw_logs.json")
    logger.info(f"Phase 3.0 完成。结果保存至: {output_dir}")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE3.0.log')
    try:
        main()
    except Exception as e:
        logger.critical("Phase 3.0 崩溃", exc_info=True)
        sys.exit(1)