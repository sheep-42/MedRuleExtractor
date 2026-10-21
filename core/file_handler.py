import os
import json
import re
import logging
from pathlib import Path
from typing import Any, List, Dict, Union, Set, Optional

logger = logging.getLogger(__name__)

class FileHandler:
    """负责通用文件I/O操作"""
    
    @staticmethod
    def read_text(path: Union[str, Path]) -> str:
        """读取文本文件内容 (对应原 read_md_as_string)"""
        path = Path(path)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.error(f"文件未找到: {path}")
            raise

    @staticmethod
    def load_json(path: Union[str, Path]) -> Any:
        """健壮地读取JSON文件"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"JSON文件未找到: {path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {path} - {e}")
            raise

    @staticmethod
    def save_json(data: Any, path: Union[str, Path], indent: int = 2):
        """保存数据为JSON文件，自动创建目录"""
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
            logger.info(f"数据已保存至: {path}")
        except Exception as e:
            logger.error(f"保存JSON文件失败: {path} - {e}")
            raise

class TextUtils:
    """负责文本清洗、切分和提取逻辑"""

    @staticmethod
    def extract_json_block(text: str) -> str:
        """从Markdown文本中提取 ```json ... ``` 内容"""
        pattern = r"```json\s*(.*?)\s*```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # 尝试匹配不带 json 标记的代码块
        pattern_plain = r"```\s*(.*?)\s*```"
        match_plain = re.search(pattern_plain, text, re.DOTALL)
        if match_plain:
            return match_plain.group(1).strip()
        return text.strip()

    @staticmethod
    def split_by_marker(text: str, marker: str = '# 【') -> List[str]:
        """
        根据特定标记切分Markdown文本 (对应原 split_by_marker)
        例如 marker='# 【' 会切分出各个板块
        """
        # 使用 re.escape 确保 marker 中的特殊字符被转义
        parts = re.split(f'(?={re.escape(marker)})', text)
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def extract_title(segment: str) -> str:
        """
        从文本段中提取标题 (对应原 extract_title)
        例如从 "# 【适应症】..." 中提取 "【适应症】"
        """
        # 优先匹配 # 【标题】 格式
        match = re.search(r'# 【([^】]+)】', segment)
        if match:
            return f"【{match.group(1)}】"
        
        # 备选策略：如果不是标准格式，取第一行并去除 #
        first_line = segment.strip().split('\n')[0]
        return first_line.replace("#", "").strip()[:50] # 限制长度防止错误

    @staticmethod
    def group_segments_by_length(
        segments: List[Dict[str, str]], 
        max_len: int = 5000, 
        excluded_titles: Optional[Set[str]] = None
    ) -> List[str]:
        """
        将多个小段落合并为大段落，以适应LLM上下文窗口 (对应原 group_segments_by_length)
        """
        if excluded_titles is None:
            excluded_titles = set()

        grouped = []
        current_group = []
        current_length = 0

        for seg in segments:
            seg_text = seg["text"]
            seg_title = seg.get("title", "")
            seg_len = len(seg_text)

            if seg_title in excluded_titles:
                continue

            # 如果单段本身就超过 max_len，直接作为独立一组
            if seg_len > max_len:
                if current_group:
                    grouped.append('\n\n'.join(current_group))
                    current_group = []
                    current_length = 0
                grouped.append(seg_text)
                continue

            # 尝试合并
            if current_length + seg_len <= max_len:
                current_group.append(seg_text)
                current_length += seg_len
            else:
                grouped.append('\n\n'.join(current_group))
                current_group = [seg_text]
                current_length = seg_len

        if current_group:
            grouped.append('\n\n'.join(current_group))

        return grouped

    @staticmethod
    def extract_drug_name(segments: List[Dict[str, str]]) -> Optional[str]:
        """
        从切分好的段落列表中查找【药品名称】段落并提取名称
        """
        for seg in segments:
            # 兼容带括号或不带括号的标题比较
            title = seg.get("title", "").replace("【", "").replace("】", "")
            if title == "药品名称":
                # 去除标题行，只保留内容
                text = seg["text"]
                # 简单清洗：移除标题行本身
                lines = text.split('\n')
                cleaned_lines = [line for line in lines if "【药品名称】" not in line and "#" not in line]
                return "\n".join(cleaned_lines).strip()
        return None