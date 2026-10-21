import argparse
import os
import re
from typing import List, Optional

import pandas as pd


BASE_COLS: List[str] = [
    "药品ID", "药品编码", "药品名称", "通用名编码", "通用名名称", "成分编码", "药理编码", "国药准字"
]


def normalize_string(value: str) -> str:
    """基本清洗：去除首尾空白、統一分隔符、移除連續分隔符與首尾分隔符。"""
    s = value.replace("\n", " ").replace("\t", " ")
    # 統一中英文逗號/分號為逗號
    s = s.replace("，", ",").replace("；", ",").replace(";", ",")
    # 去掉全形空白
    s = s.replace("\u3000", " ")
    # 壓縮多個逗號
    s = re.sub(r",+", ",", s)
    # 去除逗號兩側空白
    s = re.sub(r"\s*,\s*", ",", s)
    # 去除首尾逗號與首尾空白
    s = s.strip().strip(",").strip()
    return s


def split_multi(value: Optional[object]) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        flat: List[str] = []
        for x in value:
            sx = split_multi(x)
            if isinstance(sx, list):
                flat.extend(sx)
            elif sx:
                flat.append(sx)
        # 去重並過濾空
        seen = set()
        dedup = []
        for t in flat:
            if t and t not in seen:
                dedup.append(t)
                seen.add(t)
        return dedup or None
    # 轉字串後規範化
    s = normalize_string(str(value))
    if not s:
        return None
    # 以逗號拆分多值
    tokens = [t for t in (tok.strip() for tok in s.split(",")) if t]
    # 去重保序
    seen = set()
    result: List[str] = []
    for t in tokens:
        if t not in seen:
            result.append(t)
            seen.add(t)
    return result or None


def join_multi(values: Optional[List[str]]) -> str:
    if not values:
        return ""
    return ",".join(values)


def clean_dataframe(df: pd.DataFrame, add_search_text: bool) -> pd.DataFrame:
    # 僅保留既定八列（存在者）
    cols = [c for c in BASE_COLS if c in df.columns]
    df = df[cols].copy()

    # 去除全空行
    df = df.where(pd.notnull(df), None).dropna(how="all")

    # 去空白 + 規範分隔符（僅字符串）
    df = df.applymap(lambda v: normalize_string(v) if isinstance(v, str) else v)

    # 1) 校驗藥品ID：必須嚴格為 6 位數字；否則刪除整行
    if "药品ID" in df.columns:
        def is_valid_id(val: object) -> bool:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return False
            s = str(val).strip()
            return bool(re.fullmatch(r"\d{6}", s))

        mask = df["药品ID"].apply(is_valid_id)
        df = df[mask].copy()

    # 2) 多值處理與去重（僅針對指定可多值列）
    multi_cols = [c for c in ["成分编码", "通用名编码", "药理编码", "国药准字"] if c in df.columns]
    for col in multi_cols:
        lists = df[col].apply(split_multi)
        df[col] = lists.apply(join_multi)

    # 3) 可選：組建 search_text（藥品名稱 + 通用名名稱）
    if add_search_text:
        def build_search_text(row: pd.Series) -> str:
            parts: List[str] = []
            for name_col in ("药品名称", "通用名名称"):
                if name_col in row and row[name_col]:
                    parts.extend([str(x) for x in split_multi(row[name_col]) or []])
            # 去重保序
            seen = set()
            uniq: List[str] = []
            for p in parts:
                if p not in seen:
                    uniq.append(p)
                    seen.add(p)
            return ",".join(uniq)

        df["search_text"] = df.apply(build_search_text, axis=1)

    # 最終再次去除全空行
    df = df.replace({None: ""}).dropna(how="all")
    return df


def main():
    parser = argparse.ArgumentParser(description="清洗药品目录.xlsx：規範分隔符、拆分多值、去重並輸出")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    default_in = os.path.join(base_dir, "..", "药品目录.xlsx")
    parser.add_argument("--input", type=str, default=default_in, help="輸入 Excel 路徑（預設為倉庫內药品目录.xlsx）")
    parser.add_argument("--sheet", type=str, default="药品目录", help="工作表名，預設 '药品目录'")
    parser.add_argument("--csv", type=str, default="", help="同時輸出 CSV 的路徑（可選）")
    parser.add_argument("--add-search-text", action="store_true", help="額外生成 search_text 欄位（藥品名稱+通用名名稱）")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(f"未找到 Excel：{args.input}")

    print(f"讀取：{args.input} (sheet={args.sheet})")
    df = pd.read_excel(args.input, sheet_name=args.sheet)
    cleaned = clean_dataframe(df, add_search_text=args.add_search_text)

    # 直接覆蓋原檔指定位工作表，不生成新文件
    with pd.ExcelWriter(args.input, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        cleaned.to_excel(writer, sheet_name=args.sheet, index=False)
    print(f"已覆蓋寫回：{args.input} 中的工作表 {args.sheet}，行數：{len(cleaned)}")

    # 可選輸出 CSV
    if args.csv:
        csv_dir = os.path.dirname(args.csv)
        if csv_dir and not os.path.exists(csv_dir):
            os.makedirs(csv_dir, exist_ok=True)
        cleaned.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"已輸出 CSV：{args.csv}")


if __name__ == "__main__":
    main()


