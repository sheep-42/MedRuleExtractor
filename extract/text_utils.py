# === 文件1：text_utils.py ===
import re

def read_md_as_string(md_file_path):
    with open(md_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return content

def split_by_marker(text, marker='# 【'):
    parts = re.split(f'(?={re.escape(marker)})', text)
    return [part.strip() for part in parts if part.strip()]

def extract_title(segment):
    match = re.search(r'# 【([^】]+)】', segment)
    if match:
        return f"【{match.group(1)}】"
    else:
        return segment.strip()[:20]

def group_segments_by_length(segments, max_len=5000, excluded_titles=None):
    if excluded_titles is None:
        excluded_titles = set()

    grouped = []
    current_group = []
    current_length = 0

    for seg in segments:
        seg_text = seg["text"]
        seg_title = seg["title"]
        seg_len = len(seg_text)

        if seg_title in excluded_titles:
            continue

        if seg_len > max_len:
            if current_group:
                grouped.append('\n\n'.join(current_group))
                current_group = []
                current_length = 0
            grouped.append(seg_text)
            continue

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

def extract_drug_name(segments):
    for seg in segments:
        if seg["title"] == "【药品名称】":
            return seg["text"].replace("【药品名称】", "").strip()
    return None