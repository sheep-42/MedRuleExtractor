import os
import json
import re
import argparse
import logging
import sys
from logging_config import setup_logging
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import yaml
from openai import OpenAI, APIError

# Assume these utility functions are in a 'text_utils.py' file or similar
from text_utils import read_md_as_string, split_by_marker, extract_title

# --- 配置 logging ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger

# --- 常量定义 ---
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR.joinpath("config", "config.yaml")
MODEL_KEY_PHASE1 = 'model_phase1'

# --- 文件与配置加载 (复用之前的优秀实践) ---

def load_config(config_path: str) -> Dict[str, Any]:
    """从YAML文件加载配置。"""
    try:
        with open(config_path, 'r', encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"配置文件未找到: {config_path}")
        raise
    except yaml.YAMLError as e:
        logger.error(f"解析配置文件失败: {e}")
        raise

def save_json(data: Any, path: str):
    """将数据保存为格式化的JSON文件，并自动创建目录。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)#取出文件路径中的目录部分
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"文件已成功保存到: {path}")


def extract_json_block(text: str) -> str:
    pattern = r"```json\s*(.*?)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

# --- API 调用与解析 (针对列表输出进行优化) ---

def parse_llm_list_response(content: str) -> List[Dict[str, Any]]:
    """
    健壮地解析LLM返回的期望为列表的JSON字符串。
    - 能处理Markdown代码块。
    - 能处理模型错误地返回单个字典而不是列表的情况。
    """
    cleaned_content = content.strip()#去开头结尾的空格
    if cleaned_content.startswith("```json") and cleaned_content.endswith("```"):
        cleaned_content = cleaned_content[7:-3].strip()#去掉 Markdown 代码块包裹

    cleaned_content = extract_json_block(cleaned_content)#调用辅助函数提取 JSON 部分

    try:
        data = json.loads(cleaned_content)#从字符串解析成真正的Python对象 list / dict 等
    except json.JSONDecodeError as e:
        logger.warning(f"直接解析失败 ({e})，尝试修复反斜杠后重试...")
        repaired_content = cleaned_content.replace("\\", "\\\\")  # 将'\'替换为'\\'，以避免转义字符问题
        try:
            data = json.loads(repaired_content)
        except json.JSONDecodeError as final_e:
            # 如果解析失败，记录错误并返回空列表
            logger.error(f"修复反斜杠后，JSON解析仍然失败: {final_e}.", exc_info=True)
            logger.error(f"原始模型输出:\n---\n{content}\n---")
            return []
    
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        # 如果返回的是单个有效字典，将其包装在列表中返回
        logger.warning("模型返回了单个字典而非列表，已自动包装。")
        return [data]
    else:
        logger.warning(f"解析结果既不是有效列表也不是有效字典。原始输出: {cleaned_content}...")
        return []

def classify_with_llm(
    client: OpenAI, 
    prompt: str, 
    model_name: str
) -> List[Dict[str, Any]]:
    """调用OpenAI API进行分类，并处理其响应。"""
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是医学说明书审核助手，负责根据用户指令对说明书段落进行分类和信息提取。"},
                {"role": "user", "content": prompt}
            ],
            extra_body={"enable_thinking": False},
            temperature=0.1,## 随机性，越低越确定
            max_tokens=16384, # Note: This is the max for GPT-4-Turbo, adjust if needed
            response_format={'type': 'json_object'}# 让模型返回“严格 JSON”
        )
        content = response.choices[0].message.content#返回一个 response 对象，其中最常用的是第一条候选
        logger.info(f"模型返回内容: {content}")  # 仅打印前200个字符以避免日志过长
        return parse_llm_list_response(content)
    except APIError as e:
        logger.error(f"OpenAI API 调用失败: {e}", exc_info=True)
        return []

# --- 核心业务逻辑 ---

def handle_special_case_section(
    seg_title: str, 
    seg_text: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    处理特殊规则的板块（如“适应症”），不调用LLM。
    返回处理结果和用于索引的摘要信息。
    """
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

def handle_generic_section_with_llm(
    client: OpenAI,
    model_name: str,
    seg_title: str, 
    seg_text: str, 
    drug_name: str, 
    prompt_dir: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    处理需要调用LLM的常规板块。
    返回处理结果和用于索引的摘要信息。
    """
    logger.info(f"正在处理常规板块: 【{seg_title}】 (将调用LLM)")
    prompt_template_path = Path(prompt_dir) / f"{seg_title}.txt"

    if not prompt_template_path.exists():
        logger.warning(f"未找到板块 '{seg_title}' 的提示词文件，跳过此板块。路径: {prompt_template_path}")
        summary = {"板块": seg_title, "处理方式": "跳过 (无Prompt)", "结果条数": 0}
        return [], summary

    try:
        prompt_template = prompt_template_path.read_text(encoding="utf-8")
        prompt = prompt_template.format(drug_name=drug_name, text=seg_text)
        
        logger.info(f"原文预览: {seg_text[:100].replace(os.linesep, ' ')}...")
        output = classify_with_llm(client, prompt, model_name)
        
        summary = {
            "板块": seg_title,
            "length": len(seg_text),
            "处理方式": "LLM调用",
            "结果条数": len(output),
            "原文预览": seg_text[:50].replace("\n", " ").strip()
        }
        return output, summary

    except Exception as e:
        logger.error(f"处理板块 '{seg_title}' 时发生未知错误: {e}", exc_info=True)
        summary = {"板块": seg_title, "处理方式": f"错误 ({e})", "结果条数": 0}
        return [], summary

def main():
    """主执行函数"""
    parser = argparse.ArgumentParser(description="医学说明书结构化提取 - 阶段1")
    PROMPT_DIR = BASE_DIR / "prompts" / "phase1" / "板块"
    parser.add_argument("--input_file", type=str, required=True, help="待处理的说明书 Markdown 文件路径")
    parser.add_argument("--prompt-dir", type=str, default=str(PROMPT_DIR), help="1阶段提示词所在目录的路径")
    parser.add_argument("--config-path", type=str, default=CONFIG_PATH, help="配置文件的路径")
    parser.add_argument("--output_dir", type=str, required=True, help="本阶段所有输出的目标目录 (由 run_pipeline.py 传递)")
    args = parser.parse_args()

    # --- 1. 初始化和加载资源 ---
    config = load_config(args.config_path)
    openai_config = config.get('openai', {})
    client = OpenAI(base_url=openai_config.get('base_url'), api_key=openai_config.get('api_key'))
    model_name = openai_config.get(MODEL_KEY_PHASE1)
    if not model_name:
        logger.error(f"在 {args.config_path} 中未找到模型配置: '{MODEL_KEY_PHASE1}'")
        return

    try:
        instruction_text = read_md_as_string(args.input_file)
        drug_name = Path(args.input_file).stem
    except FileNotFoundError:
        logger.error(f"输入文件未找到: {args.input_file}")
        return

    logger.info(f"开始处理药品: {drug_name} (总字数: {len(instruction_text)})")
    
    segments = [
        {"title": extract_title(seg), "text": seg[2:].strip()}
        for seg in split_by_marker(instruction_text) if seg.strip()
    ]
    
    # --- 2. 创建输出目录 ---
    save_dir = Path(args.output_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"所有输出将保存至: {save_dir}")

    # --- 3. 循环处理各个板块 ---
    index_summary = []
    
    for seg in segments:
        seg_title = seg["title"].replace("【", "").replace("】", "")
        seg_text = seg["text"]

        if seg_title == "适应症":
            processed_data, summary = handle_special_case_section(seg_title, seg_text)
        else:
            processed_data, summary = handle_generic_section_with_llm(
                client, model_name, seg_title, seg_text, drug_name, args.prompt_dir
            )
        
        index_summary.append(summary)
        
        # 只有在处理后有数据时才保存文件
        if processed_data:
            output_path = save_dir / f"{seg_title}.json"
            save_json(processed_data, str(output_path))

    # --- 4. 保存最终的索引文件 ---
    save_json(index_summary, str(save_dir / "index.json"))

    print("\n" + "="*50)
    logger.info("阶段1处理全部完成！")
    print(f"所有结果已保存至目录: {save_dir}")
    print("="*50)

if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE1.0.log') 
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