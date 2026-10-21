import pandas as pd
import os
from elasticsearch import Elasticsearch, NotFoundError
from es_client import ESClient

base_dir = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(base_dir, "..", "药品目录.xlsx")

print("读取文件：", file_path)
if not os.path.exists(file_path):
    raise FileNotFoundError(f"未找到 Excel：{file_path}")

df = pd.read_excel(file_path, sheet_name="药品目录")

df = df.where(pd.notnull(df), None).dropna(how="all")

base_cols = ["药品ID", "药品编码", "药品名称"]
selected_cols = [c for c in base_cols if c in df.columns]
df = df[selected_cols]

df = df.applymap(lambda v: v.strip() if isinstance(v, str) else v)

def split_multi(value):
    if value is None: return None
    if isinstance(value, list):
        flat = []
        for x in value:
            sx = split_multi(x)
            if isinstance(sx, list): flat.extend(sx)
            elif sx: flat.append(sx)
        return [t for i, t in enumerate(flat) if t and t not in flat[:i]] or None
    if isinstance(value, (int, float)):
        s = str(value).strip()
        return [s] if s else None
    raw = str(value).replace('，', ',').replace('；', ',').replace(';', ',')
    tokens = [t.strip() for t in raw.split(',') if t and t.strip()]
    return tokens or None

multi_value_cols = ["药品ID", "药品编码", "药品名称"]
for col in multi_value_cols:
    if col in df.columns:
        df[col] = df[col].apply(split_multi)

documents = df.to_dict(orient="records")
print(type(documents), len(documents))
for i in range(min(3, len(documents))):
    print(documents[i])

# ---------- 写入 Elasticsearch ----------
index_name = "medical_drug_info"
client = ESClient()

if client.index_exist(index_name):
    try:
        client.delete_idx(index_name)
        print(f"已删除旧索引：{index_name}")
    except Exception as e:
        print(f"删除旧索引失败：{e}")

if not client.index_exist(index_name):
    settings = {
        "settings": {
            "index": {"max_ngram_diff": 10},
            "analysis": {
                "tokenizer": {
                    "ngram_tokenizer": {
                        "type": "ngram",
                        "min_gram": 2,
                        "max_gram": 7,
                        "token_chars": ["letter", "digit"]
                    }
                },
                "analyzer": {
                    "cn_ngram_analyzer": {
                        "type": "custom",
                        "tokenizer": "ngram_tokenizer",
                        "filter": ["lowercase"]
                    }
                }
            }
        },
        "mappings": {
            "dynamic": True,
            "properties": {
                "药品ID": {"type": "keyword"},
                "药品编码": {"type": "keyword"},
                "药品名称": {
                    "type": "text",
                    "analyzer": "cn_ngram_analyzer",
                    "search_analyzer": "cn_ngram_analyzer", 
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}
                }
            }
        }
    }
    try:
        client.es.indices.create(index=index_name, **settings)
        print(f"索引 {index_name} 已创建（search_analyzer 已修正）")
    except Exception as e:
        print(f"创建索引失败：{e}")
        exit()

BATCH = 2000
all_errors = []
for i in range(0, len(documents), BATCH):
    batch = documents[i:i + BATCH]
    errs = client.insert(batch, index_name)
    if errs:
        print(f"第 {i // BATCH + 1} 批有 {len(errs)} 条错误，示例：{errs[:3]}")
        all_errors.extend(errs)
    else:
        print(f"第 {i // BATCH + 1} 批成功写入 {len(batch)} 条")

if all_errors:
    print(f"总共有 {len(all_errors)} 条错误，前 5 条示例：")
    for err in all_errors[:5]:
        print(err)
else:
    print(f"全部成功写入 {len(documents)} 条数据！")