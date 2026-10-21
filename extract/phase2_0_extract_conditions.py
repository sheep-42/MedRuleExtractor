import os
import json
import re
import argparse
import logging
import sys
from logging_config import setup_logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import yaml
from openai import OpenAI, APIError
from PG_select import load_examples_for_prompt

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

# --- 常量定义 ---
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR.joinpath("config", "config.yaml")
PROMPT_PATH = BASE_DIR.joinpath("prompts", "phase2", "前提条件.txt")
MODEL_KEY_PHASE2 = 'model_phase2'

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

# --- API 调用与解析 (核心异常处理优化) ---

def parse_llm_json_response(content: str, fallback_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    健壮地解析LLM返回的JSON字符串，并在失败时提供详细的错误信息。
    """
    cleaned_content = content.strip()
    if cleaned_content.startswith("```json") and cleaned_content.endswith("```"):
        cleaned_content = cleaned_content[7:-3].strip()
    cleaned_content = extract_json_block(cleaned_content)
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as e:
        repair_content = cleaned_content.replace("\\", "\\\\")  # 修复反斜杠问题
        try:
            if isinstance(json.loads(repair_content), dict):
                return json.loads(repair_content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}. 返回错误结构体。")
            logger.warning(f"原始模型输出:\n---\n{content}\n---")
            return {
                **fallback_data, # 将原文内容等信息带入
                "前提条件": [],
                "error": "JSON解析失败",
                "error_details": str(e),
                "raw_response": content
            }

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
                {"role": "system", "content": "你是医学说明书分析专家，你的任务是根据用户提供的【原文内容】和【审核项】，精准地抽取出执行该审核项所需的【前提条件】。"},
                {"role": "user", "content": prompt}
            ],
            extra_body={"enable_thinking": False},
            temperature=0.1,
            max_tokens=8192,
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

# --- 核心业务逻辑 ---

def process_item(
    item: Dict[str, Any], 
    client: OpenAI, 
    prompt_template: str, 
    model_name: str
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    处理单个数据项，返回处理结果和API日志。
    """
    text = item.get("原文内容")
    label = item.get("标签预测")

    if not text or not label:
        logger.warning(f"跳过内容或标签为空的项: {item}")
        return None

    # 根据业务逻辑跳过特定标签
    if "不良反应" in label:
        logger.info(f"跳过审核项 '不良反应'")
        return None
    
    if "适应症" in label:
        # "适应症"默认没有前提条件
        logger.info(f"处理特殊审核项 '适应症'")
        response_data = {
            "原文内容": text,
            "审核项": label,
            "前提条件": []
        }
        return response_data, {"prompt": "特殊审核项处理", "原文内容": text, "审核项": label, "前提条件": []}

    # 准备 Few-shot 示例
    example_block = load_examples_for_prompt(stage=2, label_tuples=[("审核项", label)])
    if example_block:
        example_block = f"\n---\n\n【参考示例】\n**请仔细学习示例！**\n\n{example_block}\n"
    
    prompt = prompt_template.format(text=text, label=label, examples=example_block or "")
    
    logger.info(f"正在处理审核项: {label}, 原文: '{text[:50]}...'")

    # fallback_data 确保即使API调用失败，我们也能追踪到是哪个原文出的问题
    fallback_data = {"原文内容": text, "审核项": label}
    response_data = analyze_text_with_llm(client, prompt, model_name, fallback_data)
    
    # 构造标准化的处理结果
    processed_result = {
        "原文内容": text,
        "审核项": label,
        "前提条件": response_data.get("前提条件", [])
    }
    
    # 如果有错误，也记录在结果中
    if "error" in response_data:
        processed_result["错误信息"] = {
            "error": response_data["error"],
            "details": response_data.get("error_details"),
            "raw_response": response_data.get("raw_response")
        }

    # 构造用于调试的API日志
    api_log = {**response_data, "prompt": prompt}
    
    logger.info(f"处理完成: 前提条件={processed_result['前提条件']}")
    return processed_result, api_log


def main():
    """主执行函数"""
    parser = argparse.ArgumentParser(description="使用LLM分析说明书段落，提取前提条件")
    parser.add_argument(
        "--input_file",
        type=str,
        required=True,
        help="经过第一阶段验证后的JSON文件路径"
    )
    parser.add_argument(
        "--prompt_file",
        type=str,
        default=PROMPT_PATH,
        help="用于提取前提条件的提示词模板文件路径"
    )
    args = parser.parse_args()

    # --- 1. 初始化和加载资源 ---
    config = load_config(CONFIG_PATH)
    openai_config = config.get('openai', {})
    
    client = OpenAI(
        base_url=openai_config.get('base_url'),
        api_key=openai_config.get('api_key')
    )
    
    model_name = openai_config.get(MODEL_KEY_PHASE2)
    if not model_name:
        logger.error(f"在 {CONFIG_PATH} 中未找到模型配置: '{MODEL_KEY_PHASE2}'", exc_info=True)
        return

    try:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt_template = f.read()
    except FileNotFoundError:
        logger.error(f"提示词文件未找到: {args.prompt_file}", exc_info=True)
        return

    phase1_data = load_json(args.input_file)
    
    # --- 2. 处理数据 ---
    processed_results = []
    api_logs = []

    for item in phase1_data:
        result_tuple = process_item(item, client, prompt_template, model_name)
        if result_tuple:
            processed_result, api_log = result_tuple
            processed_results.append(processed_result)
            api_logs.append(api_log)

    # --- 3. 保存结果 ---
    # 自动派生输出目录：将输入路径中的 'stage_1' 替换为 'stage_2'
    input_dir = os.path.dirname(args.input_file)
    if 'stage_1' not in input_dir:
        logger.error(f"输入文件路径 '{args.input_file}' 不符合预期的 '.../stage_1/...' 结构，无法自动生成输出路径。")
        return

    output_dir = input_dir.replace("stage_1", "stage_2")

    results_path = os.path.join(output_dir, f"conditions.json")
    logs_path = os.path.join(output_dir, f"conditions_logs.json")

    # save_json 函数会自动创建不存在的目录 (因为 os.makedirs(..., exist_ok=True))
    save_json(processed_results, results_path)
    save_json(api_logs, logs_path)

    print("\n" + "="*50)
    logger.info("处理完成！")
    logger.info(f"前提条件提取结果 ({len(processed_results)}条) 已保存至: {results_path}")
    logger.info(f"完整API交互日志 ({len(api_logs)}条) 已保存至: {logs_path}")
    print("="*50)


if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE2.0.log')
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