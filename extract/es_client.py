import copy
import json
import os
import re
import time
from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.dsl import Index, Q, Search

# 重试次数
ATTEMPT_TIME = 5

# es 配置
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
with CONFIG_PATH.open(encoding="utf-8") as config_file:
    ES_CONFIG = yaml.safe_load(config_file)["es"]



def singleton(cls, *args, **kw):
    instances = {}# 存放已经创建过的实例
    def _singleton():
        key = str(cls) + str(os.getpid())# 用类名 + 进程id作为唯一key
        if key not in instances:
            instances[key] = cls(*args, **kw)# 第一次调用时，创建实例并存入字典
        return instances[key]# 以后再调用，直接返回之前存好的实例
    return _singleton


@singleton
class ESClient:

    def __init__(self):

        for _ in range(ATTEMPT_TIME):
            try:
                self.es = Elasticsearch(#使用Elasticsearch()方法创建了一个Elasticsearch 客户端对象，并赋值给 self.es
                    f"{ES_CONFIG.get('scheme', 'http')}://{ES_CONFIG['host']}:{ES_CONFIG['port']}",
                    basic_auth=(ES_CONFIG['username'], ES_CONFIG['password']),
                    verify_certs=True,#不验证ssl证书 便于测试
                    request_timeout=600#请求最多等待600秒
                )
                if self.es.ping():
                    self.info = self.es.info()
                    break
            except Exception:
                time.sleep(5)

    # -----------------------------------------------------DDL-----------------------------------------------------------

    def is_health(self) -> bool:#测试 ES 服务是否能连通
        return self.es.ping()
    
    def create_idx(self, index_name: str):#新建一个索引（index 相当于数据库中的“表”）
        '''新建 es index'''
        if self.index_exist(index_name):#先检查索引是否存在（index_exist）。如果存在，就直接返回 True
            return True
        try:
            from elasticsearch.client import IndicesClient
            return IndicesClient(self.es).create(index=index_name)#如果不存在，就用 IndicesClient(self.es).create(...) 去创建。
        except Exception:
            print("Failed to create index: " + index_name)

    def delete_idx(self, index_name: str):
        '''删除 es index'''
        try:
            self.es.indices.delete(index=index_name, allow_no_indices=True)#如果索引不存在也不报错
        except NotFoundError:
            pass
        except Exception:
            pass

    def index_exist(self, index_name: str) -> bool:
        '''检查索引是否存在'''
        s = Index(index_name, self.es)
        for i in range(ATTEMPT_TIME):
            try:
                return s.exists()
            except Exception as e:
                if str(e).find("Timeout") > 0 or str(e).find("Conflict") > 0:
                    continue# # 如果是超时或冲突，重试
                break
        return False
    
    # ------------------------------------------------------ CRUD 操作 --------------------------------------------------

    def insert(self, documents: list[dict], index_name: str) -> list[str]:
        '''新增数据'''
        # Refers to https://www.elastic.co/guide/en/elasticsearch/reference/current/docs-bulk.html
        operations = []
        for d in documents:#遍历要插入的文档（每个 d 是一个字典，来自 Excel 的一行）
            d_copy = copy.deepcopy(d)#做一份副本，避免原始数据被修改。
            operations.append({"index": {"_index": index_name}})#加入一条“操作说明”：我要往 index_name 这个索引插入。
            operations.append(d_copy)#紧接着加入一条数据，就是这份文档的内容。

        res = []
        for _ in range(ATTEMPT_TIME):
            try:
                r = self.es.bulk(index=index_name, operations=operations, refresh=False, timeout="60s")#不立即刷新索引，提高写入性能
                #这里的r是一个包含详细执行信息的字典，比如每条操作是否成功。
                if re.search(r"False", str(r["errors"]), re.IGNORECASE):
                    return res

                for item in r["items"]:
                    for action in ["create", "delete", "index", "update"]:
                        if action in item and "error" in item[action]:
                            res.append(str(item[action]["_id"]) + ":" + str(item[action]["error"]))
                return res
            except Exception as e:
                res.append(str(e))
                if re.search(r"(Timeout|time out)", str(e), re.IGNORECASE):
                    res.append(str(e))
                    time.sleep(3)
                    continue
        return res

    # def search(
    #         self,
    #         condition: dict,
    #         offset: int,
    #         limit: int,
    #         index_names: str | list[str],
    #         source: bool  = True
    # ):
    #     """
    #     搜索
    #     """
    #     # Refers to https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl.html
    #     if isinstance(index_names, str):#判断一个变量是否属于某种类型
    #         index_names = index_names.split(",")
    #     assert isinstance(index_names, list) and len(index_names) > 0

    #     bqry = Q("bool", must=[])
    #     for k, v in condition.items():#condition是用户传入的搜索条件
    #         if not v:
    #             continue
    #         if isinstance(v, list):
    #             # bqry.filter.append(Q("terms", **{k: v}))
    #             should_clauses = [Q("match", **{k: item}) for item in v if isinstance(item, str)]
    #             if should_clauses:
    #                 bqry.filter.append(Q("bool", should=should_clauses))#根据condition过滤出should的条件 放在filter下
    #         elif isinstance(v, str) or isinstance(v, int):
    #             bqry.filter.append(Q("match", **{k: v}))
    #         else:
    #             raise Exception(
    #                 f"Condition `{str(k)}={str(v)}` value type is {str(type(v))}, expected to be int, str or list.")

    #     s = Search()#s为空搜索对象 无查询条件
    #     if bqry:
    #         s = s.query(bqry)#返回一个“新的”带查询条件的对象
    #     if limit > 0:
    #         s = s[offset:offset + limit]#从offset到offset+limit
    #     q = s.to_dict()

    #     for i in range(ATTEMPT_TIME):
    #         try:
    #             #print(json.dumps(q, ensure_ascii=False))
    #             res = self.es.search(index=index_names,
    #                                  body=q,
    #                                  # search_type="dfs_query_then_fetch",
    #                                  _source=True)
    #             if str(res.get("timed_out", "")).lower() == "true":
    #                 raise Exception("Es Timeout.")
    #             if source:
    #                 return self.parse_source(res)
    #             return res
    #         except Exception as e:
    #             if str(e).find("Timeout") > 0:
    #                 continue
    #             raise e
    #     raise Exception("ESConnection.search timeout.")

    # 替换 es_client.py 中的整个 search 方法

    def search(
            self,
            condition: dict,
            offset: int,
            limit: int,
            index_names: str | list[str],
            source: bool = True
    ):
        """
        更健壮的搜索方法
        """
        if isinstance(index_names, str):
            index_names = index_names.split(",")
        assert isinstance(index_names, list) and len(index_names) > 0

        # 使用 must 子句进行全文搜索，使用 filter 子句进行精确过滤
        # 这里我们假设所有条件都是用于全文搜索的
        must_clauses = []
        
        for k, v in condition.items():
            if not v:
                continue
            
            # 如果值是列表，比如 ["A", "B"]，我们希望匹配包含 A 或 B 的文档
            # 这通常通过一个 bool 查询内的 should 子句实现
            if isinstance(v, list):
                should_clauses = [Q("match", **{k: item}) for item in v]
                if should_clauses:
                    must_clauses.append(Q("bool", should=should_clauses, minimum_should_match=1))
            
            # 如果值是字符串或数字，直接使用 match 查询
            elif isinstance(v, (str, int, float)):
                must_clauses.append(Q("match", **{k: v}))
                
            else:
                raise TypeError(f"Unsupported value type for condition '{k}': {type(v)}")

        # 构建最终的 bool 查询
        final_query = Q("bool", must=must_clauses)

        s = Search().query(final_query)
        
        if limit > 0:
            s = s[offset:offset + limit]
            
        q = s.to_dict()

        # print("执行的 ES 查询语句:")
        # print(json.dumps(q, ensure_ascii=False, indent=2))

        for i in range(ATTEMPT_TIME):
            try:
                res = self.es.search(index=index_names,
                                    body=q,
                                    _source=source) # _source 控制是否返回 _source 字段
                if res.get("timed_out"):
                    raise Exception("Es Timeout.")
                if source:
                    return self.parse_source(res)
                return res
            except Exception as e:
                if "Timeout" in str(e):
                    time.sleep(1) # 轻微延迟后重试
                    continue
                raise e
                
        raise Exception("ESClient.search failed after multiple retries.")

    def delete(self, condition: dict, index_name: str) -> int:
        '''根据条件删除数据'''
        qry = Q("bool")
        for k, v in condition.items():
            if not v:
                continue
            if k == "exists":
                qry.filter.append(Q("exists", field=v))
            elif k == "must_not":
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        if kk == "exists":
                            qry.must_not.append(Q("exists", field=vv))
            elif isinstance(v, list):
                qry.must.append(Q("terms", **{k: v}))
            elif isinstance(v, str) or isinstance(v, int):
                qry.must.append(Q("term", **{k: v}))
            else:
                raise Exception("Condition value must be int, str or list.")

        for _ in range(ATTEMPT_TIME):
            try:
                # print(Search().query(qry).to_dict(), flush=True)
                res = self.es.delete_by_query(
                    index=index_name,
                    body=Search().query(qry).to_dict(),
                    refresh=True)
                return res["deleted"]
            except Exception as e:
                if re.search(r"(timeout|connection)", str(e).lower()):
                    time.sleep(3)
                    continue
                if re.search(r"(not_found)", str(e), re.IGNORECASE):
                    return 0
        return 0


    # --------------------------------------------------辅助函数---------------------------------------------------------
    def parse_source(self, res) -> list:
        '''解析搜索结果数据'''
        rr = []
        for d in res["hits"]["hits"]:
            d["_source"]["id"] = d["_id"]
            # d["_source"]["_score"] = d["_score"]
            rr.append(d["_source"])
        return rr

    def get_chunk_ids(self, res) -> list:
        '''获取文档ID列表'''
        return [d["_id"] for d in res["hits"]["hits"]]



if __name__ == "__main__":
    es = ESClient()
    if(es.es.ping()):
        print("连接成功")
    INDEX_NAME = 'medical_route_dict'
    # # 查询
    # res1 = es.search(condition={"route_name_text": ["口腔咀嚼"]}, index_names=[INDEX_NAME], limit=25, offset=0)
    # for item in res1:
    #     item.pop('id', None)
    # standard_options_json = json.dumps(res1, ensure_ascii=False, indent=2)
    # print(standard_options_json)


    
    # ESClient().delete_idx("medical_drug_info")
    
    condition = {"药品名称": ["乌司奴单抗注射液", "乌司奴单抗注射液"]}#设置查询条件
    res2 = es.search(condition=condition,
      index_names="medical_drug_info",
      limit=5, offset=0)
    for item in res2:
        item.pop('id', None)
        if '药品ID' in item:
            item.pop('药品ID', None)
    standard_options_json = json.dumps(res2, ensure_ascii=False, indent=2)
    print(standard_options_json)
    
    indices = es.es.cat.indices(format="json")

    # 打印索引名字
    for idx in indices:
        print(idx["index"])

