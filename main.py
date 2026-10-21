import logging
import asyncio
import json
import time
import re
import copy
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Request
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from contextlib import asynccontextmanager
from itertools import groupby

# 导入你的核心组件
from core.config_mgr import load_global_config
from core.file_handler import FileHandler, TextUtils
from core.llm_handler import LLMHandler

# --- 1. 增强型日志配置 ---
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_filename = LOG_DIR / f"api_service_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_filename, encoding="utf-8")
    ]
)
logger = logging.getLogger("DrugParserAPI")

# --- 2. 全局状态加载 ---
BASE_DIR = Path(__file__).resolve().parent
logger.info(BASE_DIR)
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
PROMPT_DIR = BASE_DIR / "prompts" / "phase1"
DEFINITIONS_PATH = BASE_DIR / "prompts" / "definitions.json"

config = load_global_config(str(CONFIG_PATH))
llm = LLMHandler(config)
definitions = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 启动逻辑 (Startup) ---
    logger.info("正在初始化...")
    app.state.definitions = {}
    try:
        raw_def = FileHandler.load_json(DEFINITIONS_PATH)
        for item in raw_def:
            if isinstance(item, dict):
                app.state.definitions.update(item)
        logger.info(f"成功加载标签定义: {len(app.state.definitions)} 条")
    except Exception as e:
        logger.error(f"初始化失败: {e}")
    
    yield  # 应用开始运行，处理请求
    
    # --- 关闭逻辑 (Shutdown) ---
    app.state.definitions.clear()
    logger.info("应用关闭，资源清理完成")

app = FastAPI(title="药物说明书结构化处理 API (带详细日志版)", lifespan=lifespan)

# --- 3. 数据模型 ---
class ProcessRequest(BaseModel):
    md_content: str
    drug_name: str

class SectionResult(BaseModel):
    原文内容: str
    是否保留: bool
    不保留的原因: Optional[str] = None
    预测的标签: List[str]

class BypassItem(BaseModel):
    原文内容: str
    结构: List[Dict[str, Any]]

class ResponseData(BaseModel):
    handling_results: List[SectionResult]
    bypass_results: Dict[str, List[BypassItem]]

class APIResponse(BaseModel):
    response: str
    code: int = 200
    message: str = "success"
    data: Optional[ResponseData] = None

# --- 需要 bypass 验证流程的特殊板块 ---
BYPASS_SECTIONS = {"成份", "药品名称"}

# --- 4. 辅助函数：带日志的 LLM 调用 ---

async def call_llm_with_log(stage_name: str, segment_id: str, prompt: str, model_key: str = 'model_phase1'):
    """统一记录 LLM 输入输出的辅助函数"""
    model_name = config['openai'].get(model_key, "default")
    
    # 记录输入
    logger.info(f"[{stage_name}][{segment_id}] 使用模型: {model_name}")
    logger.debug(f"[{stage_name}][{segment_id}] PROMPT内容: \n{prompt}") # Debug级别记录全量
    logger.info(f"[{stage_name}][{segment_id}] 发送 Prompt (前100字): {prompt[:100].replace(chr(10), ' ')}...")

    start_time = time.time()
    result = await asyncio.to_thread(
        llm.chat_completion_json,
        prompt=prompt,
        model=model_name,
        expected_type=Any, # 兼容 list 和 dict
        temperature=0.1
    )
    duration = time.time() - start_time

    # 记录输出
    logger.info(f"[{stage_name}][{segment_id}] LLM 响应耗时: {duration:.2f}s")
    logger.info(f"[{stage_name}][{segment_id}] LLM 返回结果: {json.dumps(result, ensure_ascii=False)}")
    
    return result

# --- 5. 各阶段逻辑封装 ---

async def run_phase1_0(title: str, text: str, drug_name: str) -> List[Dict]:
    title_clean = title.replace("【", "").replace("】", "")
    if title_clean == "适应症":
        logger.info(f"[Phase 1.0][{title_clean}] 触发特殊规则，跳过 LLM")
        return [{"原文内容": text, "标签预测": ["适应症"]}]

    prompt_path = PROMPT_DIR / "板块" / f"{title_clean}.txt"
    if not prompt_path.exists():
        logger.warning(f"[Phase 1.0][{title_clean}] 未找到 Prompt 文件: {prompt_path}")
        return []

    prompt_template = FileHandler.read_text(prompt_path)
    prompt = prompt_template.format(drug_name=drug_name, text=text)
    
    return await call_llm_with_log("Phase 1.0", title_clean, prompt, 'model_phase1')

async def run_phase1_2(item: dict, idx: int) -> Dict:
    labels = item.get("标签预测", [])
    text = item.get("原文内容", "")
    VALIDATION_REQUIRED_LABELS = {'相互作用', '特殊人群-年龄', '特殊人群-肾功能', '特殊人群-肝功能', '特殊人群-妊娠', '特殊人群-哺乳', '特殊人群-性别'}

    if not (set(labels) & VALIDATION_REQUIRED_LABELS):
        return {"keep": True, "reason": "无需校验的标签", "data": item}

    prompt_template = FileHandler.read_text(PROMPT_DIR / "无价值段落检测.txt")
    prompt = prompt_template.format(text=text)
    
    res = await call_llm_with_log("Phase 1.2", f"Segment_{idx}", prompt, 'model_phase1_1')
    
    should_discard = res.get("是否缺乏特殊指令", False) if isinstance(res, dict) else False
    return {
        "keep": not should_discard,
        "reason": res.get("理由") if should_discard else None,
        "data": item
    }

async def run_phase1_3(text: str, label: str, idx: int, definitions: Dict) -> Dict:
    if "不良反应" in label:
        return {"correct": True, "label": label}

    defn = definitions.get(label)
    if not defn:
        logger.warning(f"[Phase 1.3][{label}] 找不到定义，跳过验证")
        return {"correct": False, "label": label, "reason": "定义缺失"}

    prompt_template = FileHandler.read_text(PROMPT_DIR / "审核项判断.txt")
    prompt = prompt_template.format(text=text, label=label, definition=defn, examples="")

    res = await call_llm_with_log("Phase 1.3", f"Seg_{idx}_{label}", prompt, 'model_phase1_2')
    
    is_correct = res.get("判断") == "正确" if isinstance(res, dict) else False
    return {
        "correct": is_correct,
        "reason": res.get("理由") if not is_correct else None,
        "label": label
    }

# --- 6. Bypass 板块处理函数 ---

async def run_bypass_section(title: str, text: str, drug_name: str) -> List[Dict]:
    """处理 bypass 板块（成份、药品名称），直接调用 LLM 生成结构化数据"""
    title_clean = title.replace("【", "").replace("】", "")
    
    prompt_path = PROMPT_DIR / "板块" / f"{title_clean}.txt"
    if not prompt_path.exists():
        logger.warning(f"[Bypass][{title_clean}] 未找到 Prompt 文件: {prompt_path}")
        return []
    
    prompt_template = FileHandler.read_text(prompt_path)
    prompt = prompt_template.format(drug_name=drug_name, text=text)
    
    result = await call_llm_with_log("Bypass", title_clean, prompt, 'model_phase1')
    
    # 确保返回的是列表格式
    if isinstance(result, list):
        return result
    elif isinstance(result, dict):
        return [result]
    return []

# --- 7. 接口主入口 ---

@app.post("/extract_and_validate", response_model=APIResponse)
async def extract_instruction(payload: ProcessRequest, request: Request):
    current_definitions = request.app.state.definitions
    request_id = f"REQ_{int(time.time())}"
    logger.info(f"[{request_id}] 收到请求: 药品={payload.drug_name}, 内容长度={len(payload.md_content)}")

    try:
        # 1. 切分
        raw_segments = TextUtils.split_by_marker(payload.md_content)
        segments = [{"title": TextUtils.extract_title(seg), "text": seg[2:].strip()} 
                    for seg in raw_segments if seg.strip()]
        logger.info(f"[{request_id}] 文档切分完成，共 {len(segments)} 个板块")

        # 2. 分离 bypass 板块和普通板块
        bypass_segments = []
        normal_segments = []
        for seg in segments:
            title_clean = seg["title"].replace("【", "").replace("】", "")
            if title_clean in BYPASS_SECTIONS:
                bypass_segments.append(seg)
            else:
                normal_segments.append(seg)
        
        logger.info(f"[{request_id}] Bypass 板块: {len(bypass_segments)} 个, 普通板块: {len(normal_segments)} 个")

        # 3. 并行处理 bypass 板块
        bypass_results = {}
        if bypass_segments:
            bypass_tasks = [
                run_bypass_section(seg["title"], seg["text"], payload.drug_name) 
                for seg in bypass_segments
            ]
            bypass_raw_results = await asyncio.gather(*bypass_tasks)
            
            for seg, result in zip(bypass_segments, bypass_raw_results):
                title_clean = seg["title"].replace("【", "").replace("】", "")
                if result:
                    bypass_results[title_clean] = result
                    logger.info(f"[{request_id}] Bypass [{title_clean}] 提取完成，共 {len(result)} 条")

        # 4. Phase 1.0: 提取普通板块
        extract_tasks = [run_phase1_0(s["title"], s["text"], payload.drug_name) for s in normal_segments]
        extracted_results = await asyncio.gather(*extract_tasks)

        # 5. 数据平铺
        all_items = []
        for idx, (seg, res_list) in enumerate(zip(normal_segments, extracted_results)):
            if not res_list: continue
            title = seg['title'].replace('【','').replace('】','')
            for item in res_list:
                if item.get("标签预测"):
                    # 统一添加标题头
                    orig = item.get("原文内容", "")
                    item["原文内容"] = f"【{title}】\n\n{orig}" if not orig.startswith(f"【{title}】") else orig
                    all_items.append(item)
        
        logger.info(f"[{request_id}] 初始提取完成，共有 {len(all_items)} 条候选段落")

        # 6. Phase 1.2: 无价值检测 (并发)
        schema_tasks = [run_phase1_2(item, i) for i, item in enumerate(all_items)]
        schema_results = await asyncio.gather(*schema_tasks)

        # 7. Phase 1.3: 标签验证 (针对通过了 1.2 的项)
        handling_results = []
        
        for i, sr in enumerate(schema_results):
            item = sr["data"]
            if not sr["keep"]:
                logger.info(f"[{request_id}] 段落 {i} 被 Phase 1.2 丢弃，理由: {sr['reason']}")
                handling_results.append({
                    "原文内容": item["原文内容"],
                    "是否保留": False,
                    "不保留的原因": f"[结构校验未通过] {sr['reason']}",
                    "预测的标签": item.get("标签预测", [])
                })
                continue

            # 针对每个标签进行验证
            current_labels = item.get("标签预测", [])
            label_tasks = [
                run_phase1_3(item["原文内容"], lbl, i, current_definitions) 
                for lbl in current_labels
            ]
            label_results = await asyncio.gather(*label_tasks)

            valid_labels = [lr["label"] for lr in label_results if lr["correct"]]
            invalid_reasons = [f"{lr['label']}:{lr['reason']}" for lr in label_results if not lr["correct"]]

            if valid_labels:
                logger.info(f"[{request_id}] 段落 {i} 验证通过。标签: {valid_labels}")
                handling_results.append({
                    "原文内容": item["原文内容"],
                    "是否保留": True,
                    "不保留的原因": None,
                    "预测的标签": valid_labels
                })
            else:
                logger.warning(f"[{request_id}] 段落 {i} 所有标签验证均失败")
                handling_results.append({
                    "原文内容": item["原文内容"],
                    "是否保留": False,
                    "不保留的原因": f"[标签校验失败] {'; '.join(invalid_reasons)}",
                    "预测的标签": current_labels
                })

        logger.info(f"[{request_id}] 处理完成。handling_results: {len(handling_results)} 条, bypass_results: {len(bypass_results)} 个板块")
        
        # 8. 组装返回结果
        response_data = {
            "handling_results": handling_results,
            "bypass_results": bypass_results
        }
        logger.info(json.dumps(response_data, indent=2, ensure_ascii=False))
        
        return APIResponse(
            response="success",
            code=200,
            message="处理完成",
            data=response_data
        )
    
    except Exception as e:
        logger.error(f"[{request_id}] 处理失败: {e}", exc_info=True)
        return APIResponse(
            response="error",
            code=500,
            message=str(e),
            data=None
        )






# --- 8. Phase 2 常量与规则定义 ---
PHASE2_PROMPT_PATH = BASE_DIR / "prompts" / "phase2" / "前提条件.txt"
MODEL_KEY_PHASE2 = 'model_phase2'

from rules.incompatibility import INCOMPATIBLE_PAIRS, VALID_CONDITIONS

# --- 9. Phase 2 数据模型 ---
class Phase2InputItem(BaseModel):
    原文内容: str
    是否保留: bool
    预测的标签: List[str]

class ConditionResult(BaseModel):
    原文内容: str
    审核项: str
    前提条件: List[str]

# 尝试导入 Few-shot 加载器（如果你的项目中有这个模块）
try:
    # 优先尝试从 extract 子模块导入 (适用于 Docker /app 结构)
    from extract.PG_select import load_examples_for_prompt
except ImportError:
    try:
        # 尝试直接导入 (适用于本地直接运行或 PYTHONPATH 设置)
        from PG_select import load_examples_for_prompt
    except ImportError:
        logger.warning("PG_select 模块未找到，Phase 2 将不使用 Few-shot 示例")
        def load_examples_for_prompt(**kwargs): return ""

# --- 10. Phase 2 逻辑封装 ---

def apply_phase2_rules(audit_item: str, conditions: List[str]) -> List[str]:
    """Phase 2.1: 应用规则清理前提条件"""
    # 1. 过滤不在白名单中的条件
    conditions = [c for c in conditions if c in VALID_CONDITIONS]
    
    # 2. 构建冲突映射
    rules_map = defaultdict(set)
    for main_item, to_remove in INCOMPATIBLE_PAIRS:
        rules_map[main_item].add(to_remove)
    
    if audit_item not in rules_map:
        return conditions
        
    # 3. 移除不兼容项
    to_remove_set = rules_map[audit_item]
    cleaned = [c for c in conditions if c not in to_remove_set]
    
    if len(cleaned) != len(conditions):
        logger.info(f"[Phase 2.1] 规则过滤: {audit_item} 自动移除了冲突项: {set(conditions)-set(cleaned)}")
    
    return cleaned

async def run_phase2_extraction(text: str, label: str, idx: int) -> Optional[Dict[str, Any]]:
    """Phase 2.0: 提取前提条件并立即清洗"""
    try:
        # 特殊业务规则跳过
        if "不良反应" in label:
            return None
        if "适应症" in label:
            return {"原文内容": text, "审核项": label, "前提条件": []}

        # 读取 Prompt 模板
        if not PHASE2_PROMPT_PATH.exists():
            logger.error(f"Phase 2 Prompt 文件不存在: {PHASE2_PROMPT_PATH}")
            # 改为返回空列表，避免返回 "error" 字段导致 Pydantic 校验失败
            return {"原文内容": text, "审核项": label, "前提条件": []}

        prompt_template = FileHandler.read_text(PHASE2_PROMPT_PATH)
        try:
            example_block = load_examples_for_prompt(stage=2, label_tuples=[("审核项", label)])
        except Exception as db_err:
            logger.warning(f"无法加载 Few-shot 示例 (数据库连接失败?): {db_err}")
            example_block = ""

        examples = f"\n---\n【参考示例】\n{example_block}\n" if example_block else ""
        
        prompt = prompt_template.format(text=text, label=label, examples=examples)
        
        # 调用 LLM (复用 Phase 1 的 call_llm_with_log)
        res = await call_llm_with_log("Phase 2.0", f"Seg_{idx}_{label}", prompt, MODEL_KEY_PHASE2)
        
        # 解析结果
        raw_conditions = res.get("前提条件", []) if isinstance(res, dict) else []
        
        # 立即应用 Phase 2.1 规则清洗
        cleaned_conditions = apply_phase2_rules(label, raw_conditions)
        
        return {
            "原文内容": text,
            "审核项": label,
            "前提条件": cleaned_conditions
        }
    except Exception as e:
        logger.error(f"[Phase 2] 处理任务失败 (Seg_{idx}_{label}): {e}", exc_info=True)
        # 发生异常时返回 None，外层会过滤掉，避免整个请求 500
        return None

# --- 11. 第二个接口定义 ---

@app.post("/extract_conditions", response_model=List[ConditionResult])
async def extract_conditions_api(payload: List[Phase2InputItem]):
    """
    第二个接口：基于第一阶段的结果，并行提取并清洗前提条件
    """
    request_id = f"REQ_P2_{int(time.time())}"
    logger.info(f"[{request_id}] 收到 Phase 2 请求: 处理项数量={len(payload)}")

    tasks = []
    # 遍历第一阶段传来的结果
    for i, item in enumerate(payload):
        # 核心逻辑：只处理第一阶段验证为“正确/保留”的段落
        if not item.是否保留:
            continue
            
        for label in item.预测的标签:
            # 为每一个（文本+标签）组合创建一个并发任务
            tasks.append(run_phase2_extraction(item.原文内容, label, i))

    if not tasks:
        logger.warning(f"[{request_id}] 没有需要处理的有效段落（可能全部被 Phase 1 丢弃了）")
        return []

    # 并发执行所有 LLM 请求
    logger.info(f"[{request_id}] 正在并发调用 LLM 提取前提条件，共 {len(tasks)} 个任务...")
    raw_results = await asyncio.gather(*tasks)

    # 过滤掉 None (跳过的项)
    final_results = [r for r in raw_results if r is not None]
    
    logger.info(f"[{request_id}] Phase 2 处理完成，生成结构化数据: {len(final_results)} 条")
    logger.info(json.dumps(final_results, indent=2, ensure_ascii=False))
    return final_results


# =============================================================================
# Phase 3: 结构化字段提取与后处理
# =============================================================================

# --- 12. Phase 3 常量与资源定义 ---
STRUCTURE_FILE = BASE_DIR / "prompts" / "table_structure_updated.json"
PROMPT_WITH_COND = BASE_DIR / "prompts" / "phase3" / "结构化字段抽取_有前提.txt"
PROMPT_NO_COND = BASE_DIR / "prompts" / "phase3" / "结构化字段抽取_无前提.txt"
MODEL_KEY_PHASE3 = 'model_phase3'

# Phase 3.2 后处理白名单
MERGE_WHITELIST = {"re_adapt"}  # 需要合并的表名
PRECONDITION_WHITELIST = {"re_usage_once", "re_usage_day"}  # 移除冗余前提的白名单

# Phase 3.3 规则等级配置
DEFAULT_TARGET_TABLES = {
    "re_pw", "re_in", "re_sp_age", "re_sp_kidney", 
    "re_sp_lactation", "re_sp_liver", "re_sp_pregnancy", "re_taboo"
}

DEFAULT_RULE_LEVELS = {
    "拦截": {"keywords": r"严禁|禁用|禁服|忌用|禁忌|不可|不能|忌|避免", "priority": 4},
    "警告": {"keywords": r"", "priority": 3},
    "提示": {"keywords": r"慎用|不宜|谨慎|不推荐|不适用|慎重", "priority": 2},
    "监测": {"keywords": r"加强观察|加强监护", "priority": 1}
}

# --- 13. Phase 3 数据模型 ---
class Phase3InputItem(BaseModel):
    原文内容: str
    审核项: str
    前提条件: List[str] = []

class StructureField(BaseModel):
    类别: str
    表名: str
    字段: Dict[str, Any]

class Phase3OutputItem(BaseModel):
    原文内容: Optional[str] = None
    审核项: Optional[str] = None
    结构: List[Dict[str, Any]]
    规则: List[Dict[str, Any]] = []

class Phase3Response(BaseModel):
    response: str
    code: int = 200
    message: str = "success"
    data: Optional[List[Dict[str, Any]]] = None

# --- 14. Phase 3.0 结构化字段提取 ---

async def run_phase3_0_extraction(
    item: dict, 
    idx: int, 
    prompt_tpl_yes: str, 
    prompt_tpl_no: str,
    remark_to_table: dict,
    drug_name: str
) -> Optional[Dict[str, Any]]:
    """Phase 3.0: 提取单条数据的结构化字段"""
    try:
        text = item.get("原文内容", "")
        main_label = item.get("审核项", "")
        condition_labels = item.get("前提条件", [])

        if not text or not main_label:
            return None

        # 获取表定义
        main_table = remark_to_table.get(main_label)
        if not main_table:
            logger.warning(f"[Phase 3.0] 未知审核项 '{main_label}'，跳过")
            return None

        # 准备字段定义 JSON
        main_fields_def = json.dumps(
            {main_table["表名"]: main_table.get("字段", {})}, 
            ensure_ascii=False, indent=2
        )
        
        # 前提条件表定义
        condition_tables = [remark_to_table[cl] for cl in condition_labels if cl in remark_to_table]
        
        # 准备 Few-shot 示例
        try:
            label_tuples = [("审核项", main_label)] + [("前提条件", cl) for cl in condition_labels]
            examples = load_examples_for_prompt(stage=3, label_tuples=label_tuples)
            example_block = f"\n---\n【参考示例】\n{examples}\n" if examples else ""
        except Exception:
            example_block = ""

        # 选择提示词模板并填充
        if condition_tables:
            cond_fields_def = json.dumps(
                {t["表名"]: t.get("字段", {}) for t in condition_tables}, 
                ensure_ascii=False, indent=2
            )
            cond_labels_str = [t["备注"] for t in condition_tables]
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
        llm_resp = await call_llm_with_log("Phase 3.0", f"Seg_{idx}_{main_label}", prompt, MODEL_KEY_PHASE3)

        # 构造结果
        final_result = {
            "原文内容": text,
            "审核项": main_label,
            "前提条件": condition_labels,
            "结构化结果": llm_resp
        }

        return final_result
    except Exception as e:
        logger.error(f"[Phase 3.0] 处理任务失败 (Seg_{idx}): {e}", exc_info=True)
        return None

# --- 15. Phase 3.1 清理与验证 ---

def is_struct_valid(struct_item: dict) -> bool:
    """判断结构元素是否有效（字段中至少有一个非空值）"""
    fields = struct_item.get("字段", {})
    if not fields or not isinstance(fields, dict):
        return False
    return not all(v is None for v in fields.values())

def phase3_1_clean_data(data: list) -> list:
    """Phase 3.1: 清理无效数据"""
    cleaned = []
    for record in data:
        # 获取 LLM 返回的结构化部分
        struct_res = record.get("结构化结果", {})
        
        # 提取核心列表
        struct_list = struct_res.get("结构") if isinstance(struct_res, dict) else None
        
        if not isinstance(struct_list, list) or not struct_list:
            struct_list = record.get("结构")
            if not isinstance(struct_list, list):
                continue
        
        valid_items = []
        has_audit_item = False

        for item in struct_list:
            if not isinstance(item, dict): continue
            
            if is_struct_valid(item):
                valid_items.append(item)
                if item.get("类别") == "审核项":
                    has_audit_item = True
        
        # 规则：必须包含至少一个有效的审核项
        if has_audit_item:
            new_record = {
                "原文内容": record.get("原文内容"),
                "审核项": record.get("审核项"),
                "结构": valid_items
            }
            cleaned.append(new_record)
            
    return cleaned

# --- 16. Phase 3.2 后处理 ---

def merge_fields(fields_list: list) -> dict:
    """合并字段值 (Set去重 + 排序拼接)"""
    merged = defaultdict(set)
    for f in fields_list:
        if not isinstance(f, dict): continue
        for k, v in f.items():
            if v is None or v == "null": continue
            parts = str(v).split(',') if isinstance(v, str) else [v]
            for p in parts:
                p_str = str(p).strip()
                if p_str: merged[k].add(p_str)
    
    final = {}
    for k, v_set in merged.items():
        if not v_set: continue
        sorted_vals = sorted(list(v_set))
        final[k] = ",".join(sorted_vals) if len(sorted_vals) > 1 else sorted_vals[0]
    return final

def merge_structures(item: dict, whitelist: set) -> dict:
    """合并 Item 内重复的审核项 (仅限白名单表)"""
    if not whitelist: return item
    
    structs = item.get("结构", [])
    audit_items = sorted(
        [s for s in structs if s.get("类别") == "审核项"], 
        key=lambda x: x.get("表名", "")
    )
    others = [s for s in structs if s.get("类别") != "审核项"]
    
    new_audits = []
    for table, group in groupby(audit_items, key=lambda x: x.get("表名")):
        group_list = list(group)
        if len(group_list) > 1 and table in whitelist:
            new_audits.append({
                "类别": "审核项",
                "表名": table,
                "字段": merge_fields([s.get("字段") for s in group_list])
            })
        else:
            new_audits.extend(group_list)
            
    item["结构"] = new_audits + others
    return item

def remove_redundant_conditions(data: list, whitelist: set) -> list:
    """如果某表名在白名单且全局只出现一次，移除其前提条件"""
    if not whitelist: return data
    
    # 全局统计
    all_table_names = []
    for item in data:
        for s in item.get("结构", []):
            if s.get("类别") == "审核项" and s.get("表名"):
                all_table_names.append(s["表名"])
    
    global_counter = Counter(all_table_names)
    
    for item in data:
        structs = item.get("结构", [])
        tables_in_item = {s["表名"] for s in structs if s.get("类别") == "审核项" and s.get("表名")}
        
        should_remove = any(
            t in whitelist and global_counter[t] == 1 
            for t in tables_in_item
        )
        
        if should_remove:
            item["结构"] = [s for s in structs if s.get("类别") != "前提条件"]
            
    return data

def merge_identical_items(data: list) -> list:
    """合并结构完全相同的记录"""
    def get_sig(structs):
        norm = []
        for s in structs:
            s_copy = copy.deepcopy(s)
            if isinstance(s_copy.get("字段"), dict):
                s_copy["字段"] = dict(sorted(s_copy["字段"].items()))
            norm.append(s_copy)
        norm.sort(key=lambda x: (x.get("类别", ""), x.get("表名", "")))
        return json.dumps(norm, ensure_ascii=False)

    groups = defaultdict(list)
    for item in data:
        groups[get_sig(item.get("结构", []))].append(item)
        
    final = []
    for sig, items in groups.items():
        if len(items) == 1:
            final.append(items[0])
        else:
            merged = {"结构": items[0]["结构"]}
            idx = 1
            for it in items:
                content_keys = sorted([k for k in it.keys() if k.startswith("原文内容")])
                for k in content_keys:
                    merged[f"原文内容_{idx}"] = it[k]
                    idx += 1
            final.append(merged)
            
    return final

def phase3_2_postprocess(data: list) -> list:
    """Phase 3.2: 完整的后处理流程"""
    # 1. 内部合并
    data = [merge_structures(item, MERGE_WHITELIST) for item in data]
    # 2. 移除冗余前提
    data = remove_redundant_conditions(data, PRECONDITION_WHITELIST)
    # 3. 合并相同记录
    data = merge_identical_items(data)
    return data

# --- 17. Phase 3.3 规则等级判定 ---

def determine_rule_level(text: str) -> dict:
    """根据原文内容判定规则等级"""
    text = text.replace('\n', ' ')
    matches = []
    
    for level, info in DEFAULT_RULE_LEVELS.items():
        if level == "警告": continue  # 默认值
        kw = info.get("keywords")
        if kw and re.search(kw, text, re.IGNORECASE):
            matches.append((level, info["priority"]))
    
    if not matches:
        return {"等级": "警告", "值": 3}
    
    matches.sort(key=lambda x: x[1], reverse=True)
    top = matches[0]
    return {"等级": top[0], "值": top[1]}

def phase3_3_validate_rules(data: list) -> list:
    """Phase 3.3: 为每条数据判定规则等级"""
    processed = []
    for item in data:
        if "结构" not in item:
            continue
            
        # 提取原文 (支持多个原文内容字段)
        texts = []
        keys = sorted([k for k in item.keys() if k.startswith("原文内容")])
        for k in keys:
            val = item[k]
            if val: texts.append(str(val).strip())
        
        full_text = "\n".join(texts)
        
        # 检查是否涉及目标表
        structs = item.get("结构", [])
        is_target = any(
            s.get("表名", "").lower() in DEFAULT_TARGET_TABLES 
            for s in structs
        )

        rule_info = {"等级": "警告", "值": 3}
        if is_target and full_text:
            rule_info = determine_rule_level(full_text)
            
        item["规则"] = [rule_info]
        processed.append(item)
        
    return processed

# --- 18. Phase 3 接口定义 ---

class Phase3Request(BaseModel):
    """Phase 3 请求体"""
    payload: List[Phase3InputItem]
    drug_name: str = "未知药品"
    bypass_results: Optional[Dict[str, List[Dict]]] = None

@app.post("/extract_structure", response_model=Phase3Response)
async def extract_structure_api(request: Phase3Request):
    """
    第三个接口：基于第二阶段的结果，提取结构化字段并进行后处理
    
    参数:
    - payload: Phase 2 输出的结果列表
    - drug_name: 药品名称
    - bypass_results: Phase 1 的 bypass_results（成份、药品名称），会被追加到最终结果
    """
    payload = request.payload
    drug_name = request.drug_name
    bypass_results = request.bypass_results
    
    request_id = f"REQ_P3_{int(time.time())}"
    logger.info(f"[{request_id}] 收到 Phase 3 请求: 处理项数量={len(payload)}, 药品名称={drug_name}")

    try:
        # 1. 加载资源
        if not STRUCTURE_FILE.exists():
            return Phase3Response(
                response="error", code=500, 
                message=f"表结构定义文件不存在: {STRUCTURE_FILE}"
            )
        
        table_structures = FileHandler.load_json(STRUCTURE_FILE)
        remark_to_table = {entry["备注"]: entry for entry in table_structures}
        
        prompt_yes = FileHandler.read_text(PROMPT_WITH_COND) if PROMPT_WITH_COND.exists() else ""
        prompt_no = FileHandler.read_text(PROMPT_NO_COND) if PROMPT_NO_COND.exists() else ""
        
        if not prompt_yes or not prompt_no:
            return Phase3Response(
                response="error", code=500,
                message="Phase 3 Prompt 模板文件缺失"
            )

        # 2. Phase 3.0: 并发提取结构化字段
        tasks = []
        for i, item in enumerate(payload):
            item_dict = item.model_dump() if hasattr(item, 'model_dump') else item.dict()
            tasks.append(run_phase3_0_extraction(
                item_dict, i, prompt_yes, prompt_no, remark_to_table, drug_name
            ))

        logger.info(f"[{request_id}] Phase 3.0 开始并发提取，共 {len(tasks)} 个任务...")
        raw_results = await asyncio.gather(*tasks)
        
        # 过滤掉 None
        phase3_0_results = [r for r in raw_results if r is not None]
        logger.info(f"[{request_id}] Phase 3.0 完成，有效结果: {len(phase3_0_results)} 条")

        # 3. Phase 3.1: 清理与验证
        phase3_1_results = phase3_1_clean_data(phase3_0_results)
        logger.info(f"[{request_id}] Phase 3.1 清理完成，有效结果: {len(phase3_1_results)} 条")

        # 4. 追加 bypass_results（成份、药品名称）
        if bypass_results:
            for section_name, items in bypass_results.items():
                for item in items:
                    if isinstance(item, dict) and "结构" in item:
                        phase3_1_results.append({
                            "原文内容": item.get("原文内容", ""),
                            "审核项": section_name,
                            "结构": item["结构"]
                        })
            logger.info(f"[{request_id}] 已追加 bypass_results，当前总数: {len(phase3_1_results)} 条")

        # 5. Phase 3.2: 后处理
        phase3_2_results = phase3_2_postprocess(phase3_1_results)
        logger.info(f"[{request_id}] Phase 3.2 后处理完成，结果: {len(phase3_2_results)} 条")

        # 6. Phase 3.3: 规则等级判定
        final_results = phase3_3_validate_rules(phase3_2_results)
        logger.info(f"[{request_id}] Phase 3.3 规则判定完成，最终结果: {len(final_results)} 条")
        logger.info(json.dumps(final_results, indent=2, ensure_ascii=False))

        return Phase3Response(
            response="success",
            code=200,
            message="Phase 3 处理完成",
            data=final_results
        )

    except Exception as e:
        logger.error(f"[{request_id}] Phase 3 处理失败: {e}", exc_info=True)
        return Phase3Response(
            response="error",
            code=500,
            message=str(e),
            data=None
        )


# --- 19. 全流程接口（可选）---

class FullPipelineRequest(BaseModel):
    md_content: str
    drug_name: str

class FullPipelineResponse(BaseModel):
    response: str
    code: int = 200
    message: str = "success"
    phase1_results: Optional[Dict[str, Any]] = None
    phase2_results: Optional[List[Dict[str, Any]]] = None
    phase3_results: Optional[List[Dict[str, Any]]] = None

@app.post("/full_pipeline", response_model=FullPipelineResponse)
async def full_pipeline_api(payload: FullPipelineRequest, request: Request):
    """
    全流程接口：一次性完成 Phase 1 -> Phase 2 -> Phase 3
    """
    request_id = f"REQ_FULL_{int(time.time())}"
    logger.info(f"[{request_id}] 收到全流程请求: 药品={payload.drug_name}")

    try:
        # ===== Phase 1 =====
        current_definitions = request.app.state.definitions
        
        # 1.1 切分
        raw_segments = TextUtils.split_by_marker(payload.md_content)
        segments = [{"title": TextUtils.extract_title(seg), "text": seg[2:].strip()} 
                    for seg in raw_segments if seg.strip()]
        
        # 1.2 分离 bypass 板块和普通板块
        bypass_segments = []
        normal_segments = []
        for seg in segments:
            title_clean = seg["title"].replace("【", "").replace("】", "")
            if title_clean in BYPASS_SECTIONS:
                bypass_segments.append(seg)
            else:
                normal_segments.append(seg)

        # 1.3 处理 bypass 板块
        bypass_results = {}
        if bypass_segments:
            bypass_tasks = [
                run_bypass_section(seg["title"], seg["text"], payload.drug_name) 
                for seg in bypass_segments
            ]
            bypass_raw_results = await asyncio.gather(*bypass_tasks)
            for seg, result in zip(bypass_segments, bypass_raw_results):
                title_clean = seg["title"].replace("【", "").replace("】", "")
                if result:
                    bypass_results[title_clean] = result

        # 1.4 Phase 1.0-1.3 处理普通板块
        extract_tasks = [run_phase1_0(s["title"], s["text"], payload.drug_name) for s in normal_segments]
        extracted_results = await asyncio.gather(*extract_tasks)

        all_items = []
        for idx, (seg, res_list) in enumerate(zip(normal_segments, extracted_results)):
            if not res_list: continue
            title = seg['title'].replace('【','').replace('】','')
            for item in res_list:
                if item.get("标签预测"):
                    orig = item.get("原文内容", "")
                    item["原文内容"] = f"【{title}】\n\n{orig}" if not orig.startswith(f"【{title}】") else orig
                    all_items.append(item)

        schema_tasks = [run_phase1_2(item, i) for i, item in enumerate(all_items)]
        schema_results = await asyncio.gather(*schema_tasks)

        handling_results = []
        for i, sr in enumerate(schema_results):
            item = sr["data"]
            if not sr["keep"]:
                handling_results.append({
                    "原文内容": item["原文内容"],
                    "是否保留": False,
                    "不保留的原因": f"[结构校验未通过] {sr['reason']}",
                    "预测的标签": item.get("标签预测", [])
                })
                continue

            current_labels = item.get("标签预测", [])
            label_tasks = [
                run_phase1_3(item["原文内容"], lbl, i, current_definitions) 
                for lbl in current_labels
            ]
            label_results = await asyncio.gather(*label_tasks)

            valid_labels = [lr["label"] for lr in label_results if lr["correct"]]
            invalid_reasons = [f"{lr['label']}:{lr['reason']}" for lr in label_results if not lr["correct"]]

            if valid_labels:
                handling_results.append({
                    "原文内容": item["原文内容"],
                    "是否保留": True,
                    "不保留的原因": None,
                    "预测的标签": valid_labels
                })
            else:
                handling_results.append({
                    "原文内容": item["原文内容"],
                    "是否保留": False,
                    "不保留的原因": f"[标签校验失败] {'; '.join(invalid_reasons)}",
                    "预测的标签": current_labels
                })

        phase1_data = {
            "handling_results": handling_results,
            "bypass_results": bypass_results
        }
        logger.info(f"[{request_id}] Phase 1 完成")

        # ===== Phase 2 =====
        phase2_tasks = []
        for i, item in enumerate(handling_results):
            if not item.get("是否保留"):
                continue
            for label in item.get("预测的标签", []):
                phase2_tasks.append(run_phase2_extraction(item["原文内容"], label, i))

        phase2_results = []
        if phase2_tasks:
            raw_p2_results = await asyncio.gather(*phase2_tasks)
            phase2_results = [r for r in raw_p2_results if r is not None]
        
        logger.info(f"[{request_id}] Phase 2 完成，结果: {len(phase2_results)} 条")

        # ===== Phase 3 =====
        if not phase2_results and not bypass_results:
            logger.warning(f"[{request_id}] 无有效数据进入 Phase 3")
            return FullPipelineResponse(
                response="success",
                code=200,
                message="处理完成，但无有效结构化数据",
                phase1_results=phase1_data,
                phase2_results=phase2_results,
                phase3_results=[]
            )

        # 加载 Phase 3 资源
        table_structures = FileHandler.load_json(STRUCTURE_FILE)
        remark_to_table = {entry["备注"]: entry for entry in table_structures}
        prompt_yes = FileHandler.read_text(PROMPT_WITH_COND) if PROMPT_WITH_COND.exists() else ""
        prompt_no = FileHandler.read_text(PROMPT_NO_COND) if PROMPT_NO_COND.exists() else ""

        # Phase 3.0
        phase3_tasks = []
        for i, item in enumerate(phase2_results):
            phase3_tasks.append(run_phase3_0_extraction(
                item, i, prompt_yes, prompt_no, remark_to_table, payload.drug_name
            ))

        raw_p3_results = await asyncio.gather(*phase3_tasks)
        phase3_0_results = [r for r in raw_p3_results if r is not None]

        # Phase 3.1
        phase3_1_results = phase3_1_clean_data(phase3_0_results)

        # 追加 bypass_results
        if bypass_results:
            for section_name, items in bypass_results.items():
                for item in items:
                    if isinstance(item, dict) and "结构" in item:
                        phase3_1_results.append({
                            "原文内容": item.get("原文内容", ""),
                            "审核项": section_name,
                            "结构": item["结构"]
                        })

        # Phase 3.2
        phase3_2_results = phase3_2_postprocess(phase3_1_results)

        # Phase 3.3
        final_results = phase3_3_validate_rules(phase3_2_results)
        logger.info(f"[{request_id}] Phase 3 完成，最终结果: {len(final_results)} 条")
        logger.info(json.dumps(final_results, indent=2, ensure_ascii=False))

        return FullPipelineResponse(
            response="success",
            code=200,
            message="全流程处理完成",
            phase1_results=phase1_data,
            phase2_results=phase2_results,
            phase3_results=final_results
        )

    except Exception as e:
        logger.error(f"[{request_id}] 全流程处理失败: {e}", exc_info=True)
        return FullPipelineResponse(
            response="error",
            code=500,
            message=str(e)
        )


if __name__ == "__main__":
    import uvicorn
    # 建议生产环境调低 log_level
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")
