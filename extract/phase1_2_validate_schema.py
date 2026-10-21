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
from openai import OpenAI
# from PG_select import load_examples_for_prompt # 如果未使用，可以注释掉

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

# --- 常量定义 ---
# 将配置中的键名定义为常量，避免在代码中出现“魔法字符串”
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR.joinpath("config", "config.yaml")
PROMPT_PATH = BASE_DIR.joinpath("prompts", "phase1", "无价值段落检测.txt")
MODEL_KEY_PHASE1 = 'model_phase1_1' # 在config.yaml中定义的模型名称键
# 这些标签的段落需要通过LLM进行二次验证，判断是否缺乏特殊指令


VALIDATION_REQUIRED_LABELS = {
    '相互作用', '特殊人群-年龄', '特殊人群-肾功能', 
    '特殊人群-肝功能', '特殊人群-妊娠', '特殊人群-哺乳', '特殊人群-性别'
}

# --- 辅助函数 ---

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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已成功保存到: {path}")

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
                is_neutral = "true" in content.lower()
                return {
                    "原文内容": original_text,
                    "是否缺乏特殊指令": is_neutral, 
                    "理由": f"JSON解析成功，但非字典格式。原始输出: {content}"
                }
        except json.JSONDecodeError as e:
            # 当严格的JSON解析失败时，记录错误并执行回退策略
            logger.warning(f"JSON解析失败: {e}. 将执行回退策略。")
            logger.warning(f"原始模型输出:\n---\n{content}\n---")
            
            # 回退策略：基于关键词进行猜测。
            # 警告：这种方法并不完全可靠。例如，如果模型输出 "The statement is not true..."，
            # 这个逻辑会错误地判断为 True。
            is_neutral = "true" in content.lower()
            
            return {
                "原文内容": original_text,
                "是否缺乏特殊指令": is_neutral, 
                "理由": f"JSON解析失败，回退逻辑判断。原始输出: {content}"
            }

def audit_label_validator(
    client: OpenAI, 
    prompt_template: str, 
    text: str,
    model_name: str
) -> Dict[str, Any]:
    """
    使用大模型验证内容是否为通用性或模糊性描述。
    
    Args:
        client: OpenAI客户端实例。
        prompt_template: 包含 {text} 占位符的提示词模板。
        text: 需要验证的原文内容。
        model_name: 要使用的模型名称。

    Returns:
        一个包含验证结果的字典。
    """    
    prompt = prompt_template.format(text=text)

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                # 使用你优化后的System Prompt
                {"role": "system", "content": "你是医学说明书信息结构化处理助手。"},
                {"role": "user", "content": prompt}
            ],
            extra_body={"enable_thinking": False},
            temperature=0.01,
            max_tokens=4096,
            response_format={'type': 'json_object'}
        )
        content = response.choices[0].message.content
        logger.info(f"模型返回内容: {content}")
        return parse_llm_json_response(content, text)
    except Exception as e:
        # 处理API调用本身的异常，例如网络问题、认证失败等
        logger.error(f"调用OpenAI API时发生错误: {e}", exc_info=True)
        return {
            "原文内容": text,
            "是否缺乏特殊指令": False, # 默认为False，表示需要人工检查
            "理由": f"API调用失败: {e}"
        }

def validate_and_process_item(
    item: Dict[str, Any], 
    client: OpenAI, 
    prompt_template: str, 
    model_name: str
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    验证单个数据项，判断是否保留。

    Args:
        item: 待处理的数据项.
        ... (其他依赖项) ...

    Returns:
        一个元组 (valuable_item, log_entry):
        - valuable_item: 如果保留，则为原始item；如果丢弃，则为None.
        - log_entry: 用于记录的详细日志信息.
    """
    text = item.get("原文内容")
    labels = item.get("标签预测", [])
    
    # 检查当前项的标签是否需要LLM验证
    # 使用集合交集可以非常高效地判断
    needs_validation = bool(set(labels) & VALIDATION_REQUIRED_LABELS)
    
    is_generic = False  # 默认为 False (保留)
    reason = "无需LLM验证，自动保留" # 默认理由

    if needs_validation:
        # 只有在需要时才调用LLM
        llm_result = audit_label_validator(client, prompt_template, text, model_name)
        # 根据你的键名 "是否缺乏特殊指令" 更新状态
        is_generic = llm_result.get("是否缺乏特殊指令", False)
        reason = llm_result.get("理由", "LLM未提供理由")
    
    # 构建统一的日志条目
    log_entry = {
        "原文内容": text,
        "标签预测": labels,
        "是否丢弃": is_generic,
        "理由": reason
    }
    
    if is_generic:
        # 如果是通用性描述，则标记为待丢弃 (返回None)
        return None, log_entry
    else:
        # 否则，标记为有价值 (返回原始item)
        return item, log_entry

def main():
    """主执行函数"""
    parser = argparse.ArgumentParser(description="说明书段落审核与验证")
    parser.add_argument(
        "--prompt_path",
        type=str,
        default=PROMPT_PATH,
        help="用于判断的提示词路径"
    )
    parser.add_argument(
        "--input_file",
        type=str,
        required=True,
        help="待处理的说明书段落JSON文件路径"
    )
    args = parser.parse_args()

    # --- 1. 初始化和加载资源 ---
    config = load_config(CONFIG_PATH)
    openai_config = config['openai']
    
    client = OpenAI(
        base_url=openai_config['base_url'],
        api_key=openai_config['api_key']
    )
    
    model_name = openai_config.get(MODEL_KEY_PHASE1)
    if not model_name:
        logger.error(f"在 {CONFIG_PATH} 中未找到模型配置: '{MODEL_KEY_PHASE1}'", exc_info=True)
        return

    try:
        with open(args.prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
    except FileNotFoundError:
        logger.error(f"提示词文件未找到: {args.prompt_path}", exc_info=True)
        return

    phase1_data = load_json(args.input_file)
    
    # --- 2. 处理数据 ---
    valuable_results = []
    validation_logs = []

    for i, item in enumerate(phase1_data):
        text = item.get("原文内容")
        labels = item.get("标签预测", [])

        if not text or not labels:
            logger.warning(f"跳过第 {i+1} 项，因其内容或标签为空。")
            continue
        
        logger.info(f"正在处理第 {i+1}/{len(phase1_data)} 项: {labels} - '{text[:50]}...'")
        
        # 调用封装好的处理函数
        valuable_item, log_entry = validate_and_process_item(
            item, client, prompt_template, model_name
        )

        # 记录日志
        validation_logs.append(log_entry)

        # 只有在返回了有价值的条目时，才将其添加到最终结果中
        if valuable_item:
            valuable_results.append(valuable_item)

        # 打印清晰的处理结果
        result_text = "丢弃" if log_entry["是否丢弃"] else "保留"
        print(f"-> 验证结果: {result_text} (理由: {log_entry['理由']})\n")

    # --- 3. 保存结果 ---
    base_dir = os.path.dirname(args.input_file)
    valuable_output_path = os.path.join(base_dir, "sections_merged_schema_validated.json")
    validation_log_path = os.path.join(base_dir, "sections_merged_schema_validated_log.json")

    save_json(valuable_results, valuable_output_path)
    save_json(validation_logs, validation_log_path)

    print("="*50)
    logger.info("处理完成！")
    logger.info(f"有价值结果 ({len(valuable_results)}条) 已保存至: {valuable_output_path}")
    logger.info(f"全部验证日志 ({len(validation_logs)}条) 已保存至: {validation_log_path}")
    print("="*50)


if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE1.2.log')
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