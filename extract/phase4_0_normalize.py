import os
import json
from pathlib import Path
import re
import argparse
import logging
from logging_config import setup_logging
import sys
from typing import Dict, Any, List, Callable

import yaml
from openai import OpenAI, APIError
from es_client import ESClient

# --- 标准配置与辅助函数 ---
logger = logging.getLogger(__name__) # 好习惯：获取以模块名命名的 logger
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR.joinpath("config", "config.yaml")
PROMPT_DIR = BASE_DIR.joinpath("prompts", "phase4")
MODEL_KEY_PHASE4 = 'model_phase4'

def load_config(path: str) -> Dict[str, Any]:#读取 YAML 配置文件
    # ... (标准加载函数) ...
    try:
        with open(path, 'r', encoding="utf-8") as f: return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"配置文件未找到: {path}", exc_info=True)
        raise

def load_json(path: str) -> Any:#JSON 文件的读写
    # ... (标准加载函数) ...
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"加载或解析JSON文件失败: {path}, 错误: {e}", exc_info=True)
        raise

def save_json(data: Any, path: str):
    # ... (标准保存函数) ...
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已成功保存到: {path}")

def extract_json_block(text: str) -> str:#从 Markdown 包裹的文本中提取 JSON
    pattern = r"```json\s*(.*?)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

def parse_llm_json_response(content: str) -> Dict[str, Any]:
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
            return json.loads(repair_content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}. 返回错误结构体。")
            logger.warning(f"原始模型输出:\n---\n{content}\n---")
            return {
                "error": "JSON解析失败",
                "error_details": str(e),
                "raw_response": content
            }

# --- 字段更新器 (Field Updaters) ---
# 每个处理器独有的部分，负责将LLM结果写回原字段

def update_usage_allow_way_fields(struct: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:#给药途径
    """为 re_usage_allow_way 更新字段。"""
    new_fields = llm_result.get("字段")
    reason = llm_result.get("理由")
    if isinstance(new_fields, dict) and "usage_allow_way" in new_fields and "usage_allow_way_name" in new_fields:
        struct['字段']['usage_allow_way'] = new_fields['usage_allow_way']
        struct['字段']['usage_allow_way_name'] = new_fields['usage_allow_way_name']
        if new_fields['usage_allow_way'] == None:
            struct['字段']['usage_allow_way'] = reason
        if new_fields['usage_allow_way_name'] == None:
            struct['字段']['usage_allow_way_name'] = reason
        logger.info(f"成功规范化 -> {new_fields['usage_allow_way']} ({new_fields['usage_allow_way_name']})")
    else:
        logger.warning(f"模型未返回有效格式，无法规范化。原始返回: {llm_result}")
    return struct

def update_usage_deny_way_fields(struct: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """为 re_usage_deny_way 更新字段。"""
    new_fields = llm_result.get("字段")
    reason = llm_result.get("理由")
    if isinstance(new_fields, dict) and "usage_deny_way" in new_fields and "usage_deny_way_name" in new_fields:
        struct['字段']['usage_deny_way'] = new_fields['usage_deny_way']
        struct['字段']['usage_deny_way_name'] = new_fields['usage_deny_way_name']
        if new_fields['usage_deny_way'] == None:
            struct['字段']['usage_deny_way'] = reason
        if new_fields['usage_deny_way_name'] == None:
            struct['字段']['usage_deny_way_name'] = reason
        logger.info(f"成功规范化 -> {new_fields['usage_deny_way']} ({new_fields['usage_deny_way_name']})")
    else:
        logger.warning(f"模型未返回有效格式，无法规范化。原始返回: {llm_result}")
    return struct

def update_qu_useway_fields(struct: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """为 qu_useway 更新字段。"""
    new_fields = llm_result.get("字段") 
    reason = llm_result.get("理由")
    if isinstance(new_fields, dict) and "useway_black" in new_fields and "useway_white" in new_fields:
        struct['字段']['useway_black'] = new_fields['useway_black']
        struct['字段']['useway_white'] = new_fields['useway_white']
        if new_fields['useway_white'] == None:
            struct['字段']['useway_white'] = reason
        if new_fields['useway_black'] == None:
            struct['字段']['useway_black'] = reason
        logger.info(f"成功规范化 -> 白名单:{new_fields['useway_white']}, 黑名单:{new_fields['useway_black']}")
    else:
        logger.warning(f"模型未返回有效格式，无法规范化。原始返回: {llm_result}")
    return struct

def update_re_in_fields(struct: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:#相互作用
    """为 re_in 更新字段。"""
    new_fields = llm_result.get("字段")
    reason = llm_result.get("理由")
    if isinstance(new_fields, dict)  and "ina" in new_fields and "ina_name" in new_fields and  "inb" in new_fields and "inb_name" in new_fields:
        #struct['字段']['ina_type'] = new_fields['ina_type']
        struct['字段']['ina'] = new_fields['ina']
        struct['字段']['ina_name'] = new_fields['ina_name']
        #struct['字段']['inb_type'] = new_fields['inb_type']
        struct['字段']['inb'] = new_fields['inb']
        struct['字段']['inb_name'] = new_fields['inb_name']
        #struct['字段']['in_exclude'] = new_fields['in_exclude']
        if new_fields['ina'] == None:
            struct['字段']['ina'] = reason
        if new_fields['ina_name'] == None:
            struct['字段']['ina_name'] = reason
        if new_fields['inb'] == None:
            struct['字段']['inb'] = reason
        if new_fields['inb_name'] == None:
            struct['字段']['inb_name'] = reason
        logger.info(f"成功规范化 -> 相互A编码:{new_fields['ina']},相互A名称:{new_fields['ina_name']},相互B编码:{new_fields['inb']},相互B名称:{new_fields['inb_name']}")
    else:
        logger.warning(f"模型未返回有效格式，无法规范化。原始返回: {llm_result}")
    return struct

def update_re_pw_fields(struct: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:#
    """为 re_pw 更新字段。"""
    new_fields = llm_result.get("字段")
    reason = llm_result.get("理由")
    if isinstance(new_fields, dict) and  "pwa" in new_fields and  "pwa_name" in new_fields and  "pwb" in new_fields and "pwb_name" in new_fields:
        struct['字段']['pwa'] = new_fields['pwa']
        struct['字段']['pwa_name'] = new_fields['pwa_name']
        #struct['字段']['pwb_type'] = new_fields['pwb_type']
        struct['字段']['pwb'] = new_fields['pwb']
        struct['字段']['pwb_name'] = new_fields['pwb_name']
        #struct['字段']['pw_exclude'] = new_fields['pw_exclude']
        if new_fields['pwa'] == None:
            struct['字段']['pwa'] = reason
        if new_fields['pwa_name'] == None:
            struct['字段']['pwa_name'] = reason
        if new_fields['pwb'] == None:
            struct['字段']['pwb'] = reason
        if new_fields['pwb_name'] == None:
            struct['字段']['pwb_name'] = reason
        logger.info(f"成功规范化 -> 配伍A编码:{new_fields['pwa']},配伍A名称:{new_fields['pwa_name']},配伍B编码:{new_fields['pwb']},配伍B名称:{new_fields['pwb_name']}")
    else:
        logger.warning(f"模型未返回有效格式，无法规范化。原始返回: {llm_result}")
    return struct

def update_re_re_fields(struct: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:#重复开药
    """为 re_re 更新字段。"""
    new_fields = llm_result.get("字段")
    reason = llm_result.get("理由")
    if isinstance(new_fields, dict) and "rea" in new_fields and  "rea_name" in new_fields and "reb" in new_fields and "reb_name" in new_fields:
       # struct['字段']['rea_type'] = new_fields['rea_type']
        struct['字段']['rea'] = new_fields['rea']
        struct['字段']['rea_name'] = new_fields['rea_name']
        #struct['字段']['reb_type'] = new_fields['reb_type']
        struct['字段']['reb'] = new_fields['reb']
        struct['字段']['reb_name'] = new_fields['reb_name']
        #struct['字段']['re_exclude'] = new_fields['re_exclude']
        if new_fields['rea'] == None:
            struct['字段']['rea'] = reason
        if new_fields['rea_name'] == None:
            struct['字段']['rea_name'] = reason
        if new_fields['reb'] == None:
            struct['字段']['reb'] = reason
        if new_fields['reb_name'] == None:
            struct['字段']['reb_name'] = reason
        logger.info(f"成功规范化 -> 重复A编码:{new_fields['rea']},重复A名称:{new_fields['rea_name']},重复B编码:{new_fields['reb']},重复B名称:{new_fields['reb_name']}")
    else:
        logger.warning(f"模型未返回有效格式，无法规范化。原始返回: {llm_result}")
    return struct

# --- 通用规范化处理器 ---

def run_normalization_process(
    item: Dict[str, Any],
    struct: Dict[str, Any],
    config: Dict[str, Any],
    shared_clients: Dict[str, Any]
) -> Dict[str, Any]:
    """
    一个通用的、由配置驱动的规范化流程。
    """
    table_name = struct.get('表名')
    logger.info(f"正在规范化表 '{table_name}' for 原文: '{item.get('原文内容', '')[:30]}...'")
    
    # 1. 提取查询词 (由配置定义)
    current_fields = struct.get("字段", {})
    search_terms = config['source_field_extractor'](current_fields)
    if not search_terms:
        logger.warning(f"表 '{table_name}' 未能提取到查询词，跳过规范化。")
        return struct

    # 2. 查询ES (由配置定义)
    try:
        condition = {config['es_search_key']: search_terms}
        es_results = shared_clients['es'].search(
            condition=condition, index_names=[config['es_index']], limit=25, offset=0
        )
        for item in es_results:
            item.pop('id', None)
            if '药品ID' in item:
                item.pop('药品ID', None)
            
        if not es_results:
            logger.warning(f"使用'{search_terms}'在ES中未检索到任何结果，无法进行规范化。")
            return struct 
    except Exception as e:
        logger.error(f"查询Elasticsearch时出错: {e}", exc_info=True)
        return struct

    # 3. 准备并调用LLM (通用逻辑)
    for res_item in es_results:
        res_item.pop('id', None)
        
    original_text = next((v for k, v in item.items() if k.startswith("原文内容")), "")
    original_text += "\n" + json.dumps(current_fields, ensure_ascii=False, indent=2)
    standard_options_json = json.dumps(es_results, ensure_ascii=False, indent=2)
    
    prompt_template_path = Path(config['prompt_template_dir']) / f"{table_name}.txt"
    try:
        prompt_template = prompt_template_path.read_text(encoding="utf-8")
        prompt = prompt_template.format(original_text=original_text, standard_options_json=standard_options_json)
    except FileNotFoundError:
        logger.error(f"未找到提示词模板: {prompt_template_path}", exc_info=True)
        return struct

    try:
        response = shared_clients['openai'].chat.completions.create(
            model=shared_clients['model_name'],
            messages=[
                {"role": "system", "content": "你是一位严谨的医学术语规范化专家。"}, 
                {"role": "user", "content": prompt}
            ],
            extra_body={"enable_thinking": False},
            temperature=0, 
            max_tokens=1024, 
            response_format={'type': 'json_object'}
        )
        content = response.choices[0].message.content
        logger.info(f"模型返回内容: {content}")
        llm_result = parse_llm_json_response(content)
        logger.info(f"模型返回: {llm_result}")
    except APIError as e:
        logger.error(f"API调用失败: {e}", exc_info=True)
        return struct

    # 4. 更新字段 (由配置定义)
    return config['field_updater'](struct, llm_result)



# --- 主执行函数 ---

def main():
    parser = argparse.ArgumentParser(description="对第三阶段后处理结果进行字段规范化")
    parser.add_argument("--input_file", type=str, required=True, help="第三阶段后处理过的JSON文件路径")
    parser.add_argument("--prompts-dir", type=str, default=PROMPT_DIR, help="规范化提示词模板所在目录")
    parser.add_argument("--config-path", type=str, default=CONFIG_PATH, help="配置文件的路径")
    args = parser.parse_args()

    # 1. 初始化和加载资源
    config = load_config(args.config_path)
    openai_config = config.get('openai', {})
    shared_clients = {
        'openai': OpenAI(base_url=openai_config.get('base_url'), api_key=openai_config.get('api_key')),
        'model_name': openai_config.get(MODEL_KEY_PHASE4),
        'es': ESClient()
    }

    # 2. 定义处理器配置 (可扩展性的核心)
    NORMALIZER_CONFIGS = {
        're_usage_allow_way': {
            'source_field_extractor': lambda fields: [t.strip() for t in fields.get("usage_allow_way_name", "").split(',')],
            'es_index': 'medical_route_dict',
            'es_search_key': 'route_name_text',
            'prompt_template_dir': args.prompts_dir,
            'field_updater': update_usage_allow_way_fields
        },
        "re_usage_deny_way": {
            'source_field_extractor': lambda fields: [t.strip() for t in fields.get("usage_deny_way_name", "").split(',')],
            'es_index': 'medical_route_dict',
            'es_search_key': 'route_name_text',
            'prompt_template_dir': args.prompts_dir,
            'field_updater': update_usage_deny_way_fields
        },
        'qu_useway': {
            'source_field_extractor': lambda fields: [t.strip() for t in ((fields.get("useway_white") or "") + "," + (fields.get("useway_black") or "")).split(',') if t.strip()],
            'es_index': 'medical_route_dict',
            'es_search_key': 'route_name_text',
            'prompt_template_dir': args.prompts_dir,
            'field_updater': update_qu_useway_fields
        },

        "re_in":
        {
            'source_field_extractor': lambda fields: [
            t.strip()
            for t in 
            (fields.get("ina") or "")+ "," + (fields.get("ina_name") or "")
            + "," + (fields.get("inb") or "")+ "," + (fields.get("inb_name") or "").split(",")
            if t.strip()],

            'es_index': 'medical_drug_info',
            'es_search_key': '药品名称',
            'prompt_template_dir': args.prompts_dir,
            'field_updater': update_re_in_fields
        },
        "re_pw":
        {
            'source_field_extractor': lambda fields: [
            t.strip()
            for t in (
            (fields.get("pwa_name") or "")+","+(fields.get("pwa"))
            + "," +(fields.get("pwb_name") or "")+","+(fields.get("pwb"))
            
            ).split(",")
            if t.strip()],

            'es_index': 'medical_drug_info',
            'es_search_key': '药品名称',
            'prompt_template_dir': args.prompts_dir,
            'field_updater': update_re_pw_fields
        },
        "re_re":
        {
            'source_field_extractor': lambda fields: [
            t.strip()
            for t in (
            (fields.get("rea") or "") + "," + (fields.get("rea_name") or "")
            +  "," + (fields.get("reb") or "")+ "," + (fields.get("reb_name") or "")
        ).split(",")
        if t.strip()],

            'es_index': 'medical_drug_info',
            'es_search_key': '药品名称',
            'prompt_template_dir': args.prompts_dir,
            'field_updater': update_re_re_fields
        }
        # 要添加新的处理器？在这里加一个新的字典就行！
        
    }

    # 3. 处理数据
    input_data = load_json(args.input_file)
    normalized_data = []

    for item in input_data:
        new_struct_list = []
        for struct in item.get("结构", []):
            table_name = struct.get("表名")
            if table_name in NORMALIZER_CONFIGS:
                # 调用通用处理器，并传入该表对应的配置
                config_for_table = NORMALIZER_CONFIGS[table_name]
                updated_struct = run_normalization_process(item, struct, config_for_table, shared_clients)
                new_struct_list.append(updated_struct)
            else:
                new_struct_list.append(struct)
        
        item["结构"] = new_struct_list
        normalized_data.append(item)
    
    # 4. 保存结果
    input_dir = os.path.dirname(args.input_file)
    if 'stage_3' not in input_dir:
        logger.error(f"输入文件路径 '{args.input_file}' 不符合预期的 '.../stage_3/...' 结构，无法自动生成输出路径。")
        return
    output_dir = input_dir.replace("stage_3", "stage_4")
    output_path = os.path.join(output_dir, f"struct_final_normalized.json")

    save_json(normalized_data, output_path)

    print("\n" + "="*50)
    logger.info(f"字段规范化完成！结果已保存至: {output_path}")
    print("="*50)

if __name__ == "__main__":
    setup_logging(log_file=LOG_DIR / 'PHASE4.0.log')
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



        '''
        输入: stage_3 的 JSON 文件 (--input_file)
        │
        ▼
 ┌─────────────────────┐
 │ load_json           │  ← 读取 JSON 数据
 └─────────────────────┘
        │
        ▼
 循环遍历每个 item
        │
        ▼
 循环遍历 item["结构"] 中的 struct
        │
        ├── 判断表名 (table_name)
        │       │
        │       ├─ 如果在 NORMALIZER_CONFIGS 里
        │       │        │
        │       │        ▼
        │       │  run_normalization_process
        │       │        │
        │       │        ├─ 1) 提取查询词 (source_field_extractor)
        │       │        │
        │       │        ├─ 2) 查询 ES (es_index, es_search_key)
        │       │        │
        │       │        ├─ 3) 读取 Prompt 模板
        │       │        │
        │       │        ├─ 4) 调用 OpenAI 模型 (chat.completions)
        │       │        │
        │       │        ├─ 5) parse_llm_json_response
        │       │        │
        │       │        └─ 6) 更新 struct (field_updater)
        │       │
        │       └─ 否则: 保留原始 struct
        │
        ▼
 把更新后的 struct 放回 item["结构"]
        │
        ▼
把所有 item 加入 normalized_data
        │
        ▼
 ┌─────────────────────┐
 │ save_json           │  ← 保存到 stage_4/struct_final_normalized.json
 └─────────────────────┘
        │
        ▼
输出: 规范化后的 JSON 文件

        '''