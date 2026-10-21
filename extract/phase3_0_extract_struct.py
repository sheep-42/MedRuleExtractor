import os
import json
import re
import argparse
from pathlib import Path
import logging
from logging_config import setup_logging
import sys
from typing import Dict, Any, List, Optional, Tuple

import yaml
from openai import OpenAI, APIError
# Assuming PG_select module is available and correct
from PG_select import load_examples_for_prompt

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

# --- 常量定义 ---
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR.joinpath("config", "config.yaml")
STRUCTURE_FILE = BASE_DIR.joinpath("prompts", "table_structure_updated.json")
PROMPT_WITH_COND = BASE_DIR.joinpath("prompts", "phase3", "结构化字段抽取_有前提.txt")
PROMPT_NO_COND = BASE_DIR.joinpath("prompts", "phase3", "结构化字段抽取_无前提.txt")
MODEL_KEY_PHASE3 = 'model_phase3'

# --- 文件与配置加载 (复用之前的优秀实践) ---

def load_config(config_path: str) -> Dict[str, Any]:
    """从YAML文件加载配置。"""
    try:
        with open(config_path, 'r', encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"配置文件未找到: {config_path}", exc_info=True)
        raise
    except yaml.YAMLError as e:
        logger.error(f"解析配置文件失败: {e}", exc_info=True)
        raise

def load_json(path: str) -> List[Dict[str, Any]]:
    """从JSON文件加载数据。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"数据文件未找到: {path}", exc_info=True)
        raise
    except json.JSONDecodeError as e:
        logger.error(f"解析JSON文件失败: {path}, 错误: {e}", exc_info=True)
        raise

def load_text(path: str) -> str:
    """从文本文件加载内容。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"文本文件未找到: {path}", exc_info=True)
        raise

def save_json(data: List[Dict[str, Any]], path: str):
    """将数据保存为格式化的JSON文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已成功保存到: {path}")

def extract_json_block(text: str) -> str:
    pattern = r"```json\s*(.*?)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

# --- API 调用与解析 ---

def parse_llm_json_response(content: str, fallback_data: Dict[str, Any]) -> Dict[str, Any]:
    """健壮地解析LLM返回的JSON字符串，并在失败时提供详细的错误信息。"""
    cleaned_content = content.strip()
    if cleaned_content.startswith("```json") and cleaned_content.endswith("```"):
        cleaned_content = cleaned_content[7:-3].strip()
    cleaned_content = extract_json_block(cleaned_content)
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as e:
        repair_content = cleaned_content.replace("\\", "\\\\")  # 修复反斜杠问题
        try:
            if isinstance(repair_content, dict):
                return json.loads(repair_content)
            else:
                return {
                    **fallback_data,
                    "error": "JSON解析成功，但非字典类型",
                    "error_details": str(e),
                    "raw_response": content
                }
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}. 返回错误结构体。")
            logger.warning(f"原始模型输出:\n---\n{content}\n---")
            return {
                **fallback_data,
                "error": "JSON解析失败",
                "error_details": str(e),
                "raw_response": content
            }

def extract_structured_data_with_llm(
    client: OpenAI, 
    prompt: str, 
    model_name: str,
    fallback_data: Dict[str, Any]
) -> Dict[str, Any]:
    """调用OpenAI API进行结构化字段提取。"""
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是医学说明书结构化字段提取专家。你的任务是根据提供的原文、审核项、以及字段定义，精准地从原文中抽取出信息，并填充到指定的JSON结构中。"},
                {"role": "user", "content": prompt}
            ],
            extra_body={"enable_thinking": False},
            temperature=0.1,
            max_tokens=16384,
            response_format={'type': 'json_object'}
        )
        content = response.choices[0].message.content
        logger.info(f"模型返回内容: {content}")
        return parse_llm_json_response(content, fallback_data)
    except APIError as e:
        logger.error(f"OpenAI API 调用失败: {e}")
        return {
            **fallback_data,
            "error": "API调用失败",
            "error_details": str(e),
            "raw_response": None
        }

# --- 核心业务逻辑 ---

def process_item(
    item: Dict[str, Any],
    client: OpenAI,
    model_name: str,
    prompt_tpl_yes: str,
    prompt_tpl_no: str,
    remark_to_table: Dict[str, Any],
    drug_name: str
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """处理单个数据项，提取结构化字段。"""
    text = item.get("原文内容", "")
    main_label = item.get("审核项", "")
    condition_labels = item.get("前提条件", [])

    if not text or not main_label:
        logger.warning(f"跳过内容或审核项为空的项: {item}")
        return None

    main_table = remark_to_table.get(main_label)
    if not main_table:
        logger.warning(f"在结构定义中未找到审核项 '{main_label}'，跳过此项。")
        return None

    condition_tables = [remark_to_table[cl] for cl in condition_labels if cl in remark_to_table]
    
    main_fields_def = json.dumps({main_table["表名"]: main_table.get("字段", {})}, ensure_ascii=False, indent=2)

    label_tuples = [("审核项", main_label)] + [("前提条件", cl) for cl in condition_labels]
    examples = load_examples_for_prompt(stage=3, label_tuples=label_tuples) or ""
    if examples:
        examples = f"\n---\n\n【参考示例】\n**请仔细学习示例！**\n\n{examples}\n"

    if condition_tables:
        cond_fields_def = json.dumps({t["表名"]: t.get("字段", {}) for t in condition_tables}, ensure_ascii=False, indent=2)
        prompt = prompt_tpl_yes.format(
            drug_name=drug_name, text=text, main_label=main_label, main_fields=main_fields_def,
            condition_labels=[t["备注"] for t in condition_tables], condition_fields=cond_fields_def, examples=examples
        )
    else:
        prompt = prompt_tpl_no.format(
            drug_name=drug_name, text=text, main_label=main_label, main_fields=main_fields_def, examples=examples
        )

    logger.info(f"正在处理审核项: '{main_label}', 原文: '{text[:50]}...'")
    
    fallback_data = {"原文内容": text, "审核项": main_label, "前提条件": condition_labels}
    structured_result = extract_structured_data_with_llm(client, prompt, model_name, fallback_data)

    # 将上下文信息和错误信息（如果有）添加到最终结果中
    final_result = {
        **fallback_data, 
        "结构化结果": {k: v for k, v in structured_result.items() if k not in ["error", "error_details", "raw_response"]}
    }
    if "error" in structured_result:
        final_result["错误信息"] = {
            "error": structured_result["error"],
            "details": structured_result.get("error_details"),
            "raw_response": structured_result.get("raw_response")
        }

    api_log = {**final_result, "prompt": prompt}

    structured_result["原文内容"] = text
    
    logger.info(f"处理完成: {final_result['结构化结果']}")
    return structured_result, api_log

def main():
    """主执行函数"""
    parser = argparse.ArgumentParser(description="使用LLM进行说明书字段的结构化提取")
    parser.add_argument("--input_file", type=str, required=True, help="第二阶段提取了前提条件的JSON文件路径")
    parser.add_argument("--structure-file", type=str, default=STRUCTURE_FILE, help="定义了表结构和字段的JSON文件路径")
    parser.add_argument("--prompt-with-cond", type=str, default=PROMPT_WITH_COND, help="带前提条件的提示词模板路径")
    parser.add_argument("--prompt-no-cond", type=str, default=PROMPT_NO_COND, help="无前提条件的提示词模板路径")
    
    args = parser.parse_args()

    # --- 1. 初始化和加载资源 ---
    config = load_config(CONFIG_PATH)
    openai_config = config.get('openai', {})
    client = OpenAI(base_url=openai_config.get('base_url'), api_key=openai_config.get('api_key'))
    model_name = openai_config.get(MODEL_KEY_PHASE3)
    if not model_name:
        logger.error(f"在 {CONFIG_PATH} 中未找到模型配置: '{MODEL_KEY_PHASE3}'")
        return

    table_structures = load_json(args.structure_file)
    phase2_results = load_json(args.input_file)
    prompt_tpl_yes = load_text(args.prompt_with_cond)
    prompt_tpl_no = load_text(args.prompt_no_cond)

    drug_name = Path(args.input_file).parent.parent.name

    remark_to_table = {entry["备注"]: entry for entry in table_structures}

    # --- 2. 处理数据 ---
    final_results = []
    api_logs = []
    
    for item in phase2_results:
        result_tuple = process_item(
            item, client, model_name, prompt_tpl_yes, prompt_tpl_no, remark_to_table, drug_name
        )
        if result_tuple:
            final_result, api_log = result_tuple
            final_results.append(final_result)
            api_logs.append(api_log)

    # --- 3. 保存结果 ---
    input_dir = os.path.dirname(args.input_file)
    if 'stage_2' not in input_dir:
        logger.error(f"输入文件路径 '{args.input_file}' 不符合预期的 '.../stage_2/...' 结构，无法自动生成输出路径。")
        return
    output_dir = input_dir.replace("stage_2", "stage_3")
    
    results_path = os.path.join(output_dir, f"struct_raw.json")
    logs_path = os.path.join(output_dir, f"struct_raw_logs.json")

    save_json(final_results, results_path)
    save_json(api_logs, logs_path)

    print("\n" + "="*50)
    logger.info("处理完成！")
    logger.info(f"结构化提取结果 ({len(final_results)}条) 已保存至: {results_path}")
    logger.info(f"完整API交互日志 ({len(api_logs)}条) 已保存至: {logs_path}")
    print("="*50)

if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE3.0.log')
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