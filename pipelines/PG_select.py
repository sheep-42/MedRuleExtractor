import logging
import json
import yaml
from pathlib import Path
import re  # 导入 re 模块用于密码屏蔽

from sqlalchemy import create_engine, Column, Integer, String, Text, JSON, TIMESTAMP, Boolean, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.sql import func

# --- 1. 获取 Logger ---
# 最佳实践：在模块顶部获取一个以当前模块名命名的 logger
logger = logging.getLogger(__name__)

# --- 2. 增强配置加载并添加日志 ---
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR.joinpath("config", "config.yaml")

def load_db_url(config_path=CONFIG_PATH):
    logger.info(f"开始从 {config_path} 加载数据库配置...")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            db = config['database']
            db_url = URL.create(
                drivername=f"{db['dialect']}+{db['driver']}",
                username=db['username'], password=db['password'],
                host=db['host'], port=int(db['port']), database=db['database'],
            )
            logger.info("数据库配置加载成功。")
            return db_url
    except FileNotFoundError:
        logger.error(f"数据库配置文件未找到: {config_path}")
        raise
    except (KeyError, TypeError) as e:
        logger.error(f"配置文件格式错误，缺少必要的键: {e}")
        raise
    except Exception as e:
        logger.error(f"加载数据库配置时发生未知错误: {e}", exc_info=True)
        raise

# --- 3. 在创建引擎时记录日志（并屏蔽密码） ---
DB_URL = load_db_url()

# 屏蔽 URL 中的密码，以便安全地记入日志
def mask_password_in_url(url: str) -> str:
    return url.render_as_string(hide_password=True) if isinstance(url, URL) else re.sub(r':([^@]+)@', r':<masked>@', url)

logger.info(f"创建数据库引擎，URL: {mask_password_in_url(DB_URL)}")
engine = create_engine(DB_URL)
Base = declarative_base()

class ReviewPromptExample(Base):
    # ... (类定义保持不变) ...
    __tablename__ = 'review_prompt_examples'#数据库表名
    id = Column(Integer, primary_key=True)
    stage = Column(Integer, nullable=False)
    type = Column(String(20), nullable=False)
    label = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)
    output = Column(JSON, nullable=False)
    comment = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())
    review = Column(Boolean, nullable=False, default=False)
    is_deleted = Column(Boolean, nullable=False, default=False)


def load_examples_for_prompt(stage: int, label_tuples: list, top_n: int = 10) -> str:
    """
    加载指定阶段、多个类型和标签的 prompt 示例，返回格式化文本片段可用于 few-shot prompting。
    """
    # --- 4. 在函数入口记录关键参数 ---
    logger.info(f"开始加载 prompt 示例。阶段: {stage}, Top N: {top_n}")
    logger.debug(f"查询条件 (类型, 标签): {label_tuples}")

    with Session(engine) as session:
        formatted_examples = ["以下是几个示例，用于指导你的判断："]
        global_idx = 1

        for example_type, label in label_tuples:
            # --- 5. 记录每次查询的详细信息 ---
            logger.debug(f"正在查询 stage={stage}, type='{example_type}', label='{label}'...")
            stmt = (
                select(ReviewPromptExample)
                .where(
                    ReviewPromptExample.stage == stage,
                    ReviewPromptExample.label == label,
                    ReviewPromptExample.type == example_type,
                    ReviewPromptExample.is_deleted == False
                )
                .limit(top_n)
            )
            results = session.execute(stmt).scalars().all()
            
            # --- 6. 记录查询结果 ---
            logger.debug(f"查询到 {len(results)} 条记录。")

            if results:
                for item in results:
                    try:
                        output_data = item.output
                        output_json = json.dumps(output_data, ensure_ascii=False, indent=2)
                    except Exception as e:
                        # --- 7. 对可预见的错误使用 warning 级别日志 ---
                        # 程序可以继续运行，但这仍然是一个值得注意的问题
                        logger.warning(f"无法解析示例 ID {item.id} 的 output 字段为 JSON。错误: {e}")
                        output_json = f"(⚠️ 无法解析 output 字段为 JSON)"
                    
                    formatted_examples.append(
                        f"【示例{global_idx}】\n原文内容：{item.text.strip()}\n标准回答：\n{output_json}\n解释说明：{item.comment.strip() if item.comment else '无'}"
                    )
                    global_idx += 1

        if global_idx == 1:
            # --- 8. 记录未找到任何数据的特殊情况 ---
            logger.warning(f"根据给定条件，未在数据库中找到任何可用示例。")
            return ""
        
        # --- 9. 在函数出口记录摘要信息 ---
        logger.info(f"成功格式化了 {global_idx - 1} 个示例。")
        return "\n\n".join(formatted_examples)

# ✅ 示例用法
if __name__ == "__main__":
    # --- 10. 在 __main__ 块中配置日志 ---
    # 这使得脚本可以独立运行并产生日志
    # 假设 logging_config.py 在父目录的 extract/ 中
    # 你可能需要调整路径
    import sys
    sys.path.append(str(Path(__file__).resolve().parent))
    from logging_config import setup_logging
    
    # 将日志输出到专门的文件，方便调试
    setup_logging(log_file='logs/db_examples.log', level=logging.DEBUG)

    logger.info("--- 脚本独立运行测试 ---")
    
    label_tuples = [("审核项", "用法用量-单次剂量"), ("前提条件", "频次")]
    prompt_examples = load_examples_for_prompt(stage=3, label_tuples=label_tuples)
    
    if prompt_examples:
        print("--- 生成的 Prompt 示例 ---")
        print(prompt_examples)
        logger.debug("已将生成的 prompt 打印到控制台。")
    else:
        print("未找到任何示例。")