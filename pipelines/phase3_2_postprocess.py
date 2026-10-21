import sys
import argparse
import logging
import copy
import json
from pathlib import Path
from itertools import groupby
from collections import Counter, defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from core.log_mgr import setup_logging
from core.file_handler import FileHandler

logger = logging.getLogger(__name__)
LOG_DIR = BASE_DIR / "logs"

def merge_fields(fields_list: list) -> dict:
    """合并字段值 (Set去重 + 排序拼接)"""
    merged = defaultdict(set)
    for f in fields_list:
        if not isinstance(f, dict): continue
        for k, v in f.items():
            if v is None or v == "null": continue
            # 统一转为字符串处理分割
            parts = str(v).split(',') if isinstance(v, str) else [v]
            for p in parts:
                p_str = str(p).strip()
                if p_str: merged[k].add(p_str)
    
    final = {}
    for k, v_set in merged.items():
        if not v_set: continue
        # 排序保证确定性
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
            # 合并
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
    
    # 统计表名频率 (这里简单化为每个 item 内的频率，如果需要全局频率需要先遍历一次全量数据)
    # 原逻辑似乎是计算 item 内部的频率？不，原逻辑使用了 data 全局统计
    
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
        
        # 检查是否满足移除条件：在白名单且全局只出现1次
        should_remove = any(
            t in whitelist and global_counter[t] == 1 
            for t in tables_in_item
        )
        
        if should_remove:
            # 过滤掉前提条件
            item["结构"] = [s for s in structs if s.get("类别") != "前提条件"]
            
    return data

def merge_identical_items(data: list) -> list:
    """合并结构完全相同的记录"""
    
    def get_sig(structs):
        # 生成规范化签名：排序字段键 -> 排序结构列表 -> JSON字符串
        norm = []
        for s in structs:
            s_copy = copy.deepcopy(s)
            if isinstance(s_copy.get("字段"), dict):
                # 字典键排序
                s_copy["字段"] = dict(sorted(s_copy["字段"].items()))
            norm.append(s_copy)
        # 列表按(类别, 表名)排序
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
            # 合并原文内容
            merged = {"结构": items[0]["结构"]} # 结构相同，取第一个即可
            idx = 1
            for it in items:
                # 提取已有的原文内容字段
                content_keys = sorted([k for k in it.keys() if k.startswith("原文内容")])
                for k in content_keys:
                    merged[f"原文内容_{idx}"] = it[k]
                    idx += 1
            final.append(merged)
            
    return final

def main():
    parser = argparse.ArgumentParser(description="Phase 3.2: 后处理")
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--merge-whitelist", type=str, default="re_adapt")
    parser.add_argument("--precondition-whitelist", type=str, default="re_usage_once,re_usage_day")
    args = parser.parse_args()

    data = FileHandler.load_json(args.input_file)

    # 1. 内部合并
    mw = set(args.merge_whitelist.split(','))
    data = [merge_structures(item, mw) for item in data]

    # 2. 移除冗余前提
    pw = set(args.precondition_whitelist.split(','))
    data = remove_redundant_conditions(data, pw)

    # 3. 合并相同记录
    data = merge_identical_items(data)

    # 保存
    output_path = Path(args.input_file).with_name("struct_postprocessed.json")
    FileHandler.save_json(data, output_path)
    logger.info(f"Phase 3.2 完成。结果保存至: {output_path}")

if __name__ == "__main__":
    setup_logging(LOG_DIR / 'PHASE3.2.log')
    try:
        main()
    except Exception as e:
        logger.critical("Phase 3.2 崩溃", exc_info=True)
        sys.exit(1)