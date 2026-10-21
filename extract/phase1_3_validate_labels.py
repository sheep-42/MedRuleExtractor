import os
import json
import re
import argparse
import logging
from logging_config import setup_logging
import sys
from pathlib import Path
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
MODEL_KEY_VALIDATION = 'model_phase1_2' # Use a specific model key in config
DEFINITIONS_PATH = BASE_DIR.joinpath("prompts", "definitions.json")
PROMPT_PATH = BASE_DIR.joinpath("prompts", "phase1", "审核项判断.txt")

# --- 文件与配置加载 ---

def load_config(path: str) -> Dict[str, Any]:
    # ... (Standard load_config function) ...
    try:
        with open(path, 'r', encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"配置文件未找到: {path}", exc_info=True)
        raise

def load_json(path: str) -> List[Dict[str, Any]]:
    # ... (Standard load_json function) ...
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"加载或解析JSON文件失败: {path}, 错误: {e}", exc_info=True)
        raise

def save_json(data: Any, path: str):
    # ... (Standard save_json function) ...
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已成功保存到: {path}")

def load_label_definitions(path: str) -> Dict[str, str]:
    """加载标签定义文件，并转换为 '标签: 定义' 的字典。"""
    data = load_json(path)
    definitions = {}
    for item in data:
        if isinstance(item, dict):
            definitions.update(item)
    logger.info(f"成功加载 {len(definitions)} 条标签定义。")
    return definitions

# --- API 调用与解析 ---

def extract_json_block(text: str) -> str:
    pattern = r"```json\s*(.*?)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

def parse_llm_json_response(content: str, original_text: str) -> Dict[str, Any]:
    """
    健壮地解析LLM返回的可能包含Markdown的JSON字符串。
    如果解析失败，则进行回退处理。
    """
    cleaned_content = content.strip()
    
    # 尝试去除常见的Markdown代码块标记
    if cleaned_content.startswith("```json") and cleaned_content.endswith("```"):
        cleaned_content = cleaned_content[7:-3].strip()

    cleaned_content = extract_json_block(cleaned_content)
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as e:
        # 如果直接解析失败，尝试修复反斜杠问题
        repaired_content = cleaned_content.replace("\\", "\\\\")  # 将'\'替换为'\\'，以避免转义字符问题
        try:
            if isinstance(json.loads(repaired_content), dict):
                return json.loads(repaired_content)
            else:
                return {"判断": "正确", "理由": f"JSON解析成功，但非字典格式。原始输出: {content}"}
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}. 将执行回退策略。")
            logger.warning(f"原始模型输出:\n---\n{content}\n---")
            if "错误" in cleaned_content:
                return {"判断": "错误", "理由": f"JSON解析失败，回退逻辑判断。原始输出: {content}"}
            if "正确" in cleaned_content:
                return {"判断": "正确", "理由": f"JSON解析失败，回退逻辑判断。原始输出: {content}"}
            
            return {"判断": "正确", "理由": f"JSON解析失败，关键词判断也失败。原始输出: {content}"}

def analyze_text_with_llm(
    client: OpenAI, 
    prompt: str, 
    model_name: str,
    fallback_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    调用OpenAI API并处理其响应。
    """
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是一位严谨的医学说明书审核专家。"},
                {"role": "user", "content": prompt}
            ],
            extra_body={"enable_thinking": False},
            temperature=0.1,
            max_tokens=4096,
            response_format={'type': 'json_object'}
        )
        content = response.choices[0].message.content
        logger.info(f"模型返回内容: {content}")
        parsed_response = parse_llm_json_response(content, fallback_data)
        return parsed_response

    except APIError as e:
        logger.error(f"OpenAI API 调用失败: {e}", exc_info=True)
        return {
            **fallback_data,
            "前提条件": [],
            "error": "API调用失败",
            "error_details": str(e),
            "raw_response": None
        }

def process_item(
    item: Dict[str, Any], 
    client: OpenAI, 
    prompt_template: str, 
    model_name: str
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    处理单个数据项，调用LLM进行验证。
    使用LLM验证一个(原文, 标签)对的正确性。
    """
    text = item.get("text")
    label = item.get("label")
    definition = item.get("definition")

    if not text or not label:
        logger.warning(f"跳过内容或标签为空的项: {item}")
        return None
    
    # 根据业务逻辑跳过特定标签
    if "不良反应" in label:
        logger.info(f"跳过审核项 '不良反应'")
        return None
    
    # 准备 Few-shot 示例
    example_block = load_examples_for_prompt(stage=1, label_tuples=[("审核项", label)])

    if example_block:
        example_block = f"\n---\n\n【参考示例】\n**以下是与该审核项相关的真实判断示例，请仔细学习其内在逻辑：**\n\n{example_block}\n"
    else:
        return {
            "原文内容": text,
            "标签预测": label
        }, {
            "prompt": "无示例",
            "原文内容": text,
            "审核项": label,
            "理由": "无相关示例"
        }

    prompt = prompt_template.format(text=text, label=label, definition=definition, examples=example_block or "")

    logger.info(f"正在验证 -> 标签: '{label}', 原文: '{text[:50]}...'")

    # fallback_data 确保即使API调用失败，我们也能追踪到是哪个原文出的问题
    fallback_data = {"原文内容": text, "审核项": label}
    response_data = analyze_text_with_llm(client, prompt, model_name, fallback_data)
    
    if response_data.get("判断") == "正确":
        processed_result = {
            "原文内容": text,
            "标签预测": label # 输出为单标签项，因为是逐一验证的
        }
        print(f"[保留] 标签 '{label}' 验证通过。")
    else:
        processed_result = None
        print(f"[丢弃] 标签 '{label}' 验证不通过。理由: {response_data.get('理由')}")

    api_log = {**response_data, "prompt": prompt, "原文内容": text, "审核项": label}

    return processed_result, api_log

# --- 主流程 ---

def main():
    parser = argparse.ArgumentParser(description="阶段1.3: 验证第一阶段预测的审核项标签的正确性")
    parser.add_argument("--input_file", type=str, required=True, help="阶段1.2验证后的JSON文件路径 (sections_merged_schema_validated.json)")
    parser.add_argument("--definitions_file", type=str, default=DEFINITIONS_PATH, help="包含审核项定义的JSON文件路径")
    parser.add_argument("--config_path", type=str, default=CONFIG_PATH, help="配置文件的路径")
    parser.add_argument("--prompt_file", type=str, default=PROMPT_PATH, help="用于验证标签的提示词模板文件路径")
    args = parser.parse_args()

    # 1. 初始化和加载资源
    config = load_config(args.config_path)
    openai_config = config.get('openai', {})
    client = OpenAI(
        base_url=openai_config.get('base_url'), api_key=openai_config.get('api_key')
    )
    model_name = openai_config.get(MODEL_KEY_VALIDATION)
    if not model_name:
        logger.error(f"在 {CONFIG_PATH} 中未找到模型配置: '{MODEL_KEY_VALIDATION}'", exc_info=True)
        return
    
    try:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt_template = f.read()
    except FileNotFoundError:
        logger.error(f"提示词文件未找到: {args.prompt_file}", exc_info=True)
        return
    
    label_definitions = load_label_definitions(args.definitions_file)
    phase1_data = load_json(args.input_file)

    # 2. 处理数据
    validated_results = []
    validation_logs = []

    for item in phase1_data:
        text = item.get("原文内容")
        labels = item.get("标签预测", [])

        if not text or not labels:
            continue

        # 因为一个原文可能对应多个标签，所以逐一验证
        for label in labels:
            definition = label_definitions.get(label)
            if not definition:
                logger.warning(f"未找到标签 '{label}' 的定义，跳过此项验证。")
                validation_logs.append({"原文内容": text, "标签": label, "判断": "跳过", "理由": "无定义"})
                continue
            # 准备验证项
            item = {
                "text": text,
                "label": label,
                "definition": definition
            }

            # 调用 LLM 验证标签
            result_tuple = process_item(item, client, prompt_template, model_name)
            if result_tuple:
                processed_result, api_log = result_tuple
                if processed_result:
                    validated_results.append(processed_result)
                validation_logs.append(api_log)
            

    # 3. 保存结果
    base_dir = os.path.dirname(args.input_file)
    results_path = os.path.join(base_dir, "sections_merged_labels_validated.json")
    logs_path = os.path.join(base_dir, "sections_merged_labels_validated_logs.json")

    save_json(validated_results, results_path)
    save_json(validation_logs, logs_path)

    print("\n" + "="*50)
    logger.info("阶段1.3 标签正确性验证完成！")
    logger.info(f"共保留 {len(validated_results)} 条有效数据。")
    logger.info(f"验证后结果已保存至: {results_path}")
    logger.info(f"详细验证日志已保存至: {logs_path}")
    print("="*50)

if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE1.3.log')
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