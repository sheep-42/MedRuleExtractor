import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List
import re
import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import FileResponse, JSONResponse # 引入 FileResponse

# --- 配置 ---
# 假设此 web_app.py 文件位于 extract 目录中
APP_DIR = Path(__file__).parent
BASE_DIR = APP_DIR.parent
RESULTS_DIR = BASE_DIR / "results"
EDIT_LOGS_DIR = RESULTS_DIR / "edit_logs"
EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True) # 确保日志目录存在
ALLOWED_SCRIPTS = {
    "run_pipeline.py",
    "phase1_0_extract.py",
    "phase1_1_merge.py",
    "phase1_2_validate_schema.py",
    "phase1_3_validate_labels.py",
    "phase2_0_extract_conditions.py",
    "phase2_1_validate_rules.py",
    "phase3_0_extract_struct.py",
    "phase3_1_filter_clean.py",
    "phase3_2_postprocess.py",
    "phase4_0_normalize.py"
    # ... 其他脚本
}

# --- 定义白名单 ---
# 允许在根目录显示的顶级条目
ALLOWED_TOP_LEVEL_ENTRIES = {"instructions_MD", "results", "README.md"}
# 允许进入并浏览其子目录的顶级目录
ALLOWED_BROWSE_DIRS = set()
for entry in ALLOWED_TOP_LEVEL_ENTRIES:
    if '.' not in entry:
        ALLOWED_BROWSE_DIRS.add((BASE_DIR / entry).resolve())

# ==================== WEB APP 自身的日志配置 ====================
def setup_webapp_logging(log_dir):
    """配置 web_app 自身的日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(log_dir / "webapp.log", maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'),
            logging.StreamHandler() # 同时输出到控制台
        ]
    )
    logging.info("WebApp 日志系统初始化完成。")

# ================================================================

app = FastAPI(title="MedRuleExtractor Web Assistant")

# --- 允许跨域请求，方便前端开发 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8080", "http://127.0.0.1:8080"],  # 在生产环境中应设置为你的前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API 数据模型 ---
class FilePathRequest(BaseModel):
    path: str

class SaveFileRequest(BaseModel):
    path: str  # 相对于 results 目录的路径
    content: Any
    content_type: str = "json" # 默认为 json

class RunScriptRequest(BaseModel):
    script_path: str
    args: List[str]

class EditLogRequest(BaseModel):
    file_path: str      # 被修改的文件路径
    timestamp: str      # 修改时间戳 (由前端生成)
    diff: Dict[str, Any] # 修改前后的差异
# --- API 端点 ---

@app.get("/api/browse")
def browse_directory(path: str = "."):
    """
    安全地浏览指定的目录，只暴露白名单内的文件和文件夹。
    """
    # --- 1. 修改这里的判断条件 ---
    # 只在 path 是 '.' 或为空时，才返回根目录的白名单视图。
    if path == "." or not path:
        items = []
        for entry_name in sorted(list(ALLOWED_TOP_LEVEL_ENTRIES)):
            entry_path = BASE_DIR / entry_name
            if entry_path.exists():
                items.append({
                    "name": entry_name,
                    "path": entry_name,
                    "is_dir": entry_path.is_dir(),
                })
        return items

    # --- 2. 所有其他路径都进入子目录浏览逻辑 ---
    try:
        target_path = (BASE_DIR / path).resolve()
    except Exception:
        raise HTTPException(status_code=403, detail="无效的路径")

    # 安全性检查：确保目标路径是在允许的白名单目录之下
    is_allowed = False
    # 检查 target_path 是否是白名单目录本身，或者是其子目录
    for allowed_dir in ALLOWED_BROWSE_DIRS:
        if target_path == allowed_dir or target_path.is_relative_to(allowed_dir):
            is_allowed = True
            break
    
    if not is_allowed:
        raise HTTPException(status_code=403, detail="禁止访问此目录！")

    if not target_path.exists():
        raise HTTPException(status_code=404, detail="路径不存在")
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail="目标路径不是一个目录")

    # 遍历并返回内容
    entries = []
    for item in target_path.iterdir():
        if item.name.startswith('.'):
            continue
        entries.append(item)

    # results 目录按修改时间倒序，其余目录按名称排序
    if target_path == RESULTS_DIR:
        entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    else:
        entries.sort(key=lambda p: p.name)

    items = []
    for item in entries:
        items.append({
            "name": item.name,
            "path": str(item.relative_to(BASE_DIR)),
            "is_dir": item.is_dir(),
        })
    return items

def validate_document_path(file_path: Path, *, writable: bool = False) -> None:
    allowed = any(file_path.is_relative_to(root) for root in ALLOWED_BROWSE_DIRS)
    if not writable and file_path == (BASE_DIR / "README.md").resolve():
        allowed = True
    if not allowed:
        raise HTTPException(status_code=403, detail="只允许访问说明书与处理结果")

@app.post("/api/preview")
def preview_file(request: FilePathRequest):
    """预览指定文件的内容"""
    file_path = (BASE_DIR / request.path).resolve()
    validate_document_path(file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        content = file_path.read_text(encoding="utf-8")
        if file_path.suffix == ".json":
            return json.loads(content)
        else:
            # 对于 md, txt 等，直接返回文本内容
            return {"content": content, "type": file_path.suffix}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {e}")

@app.post("/api/save")
def save_file(request: SaveFileRequest):
    """保存修改后的文件内容 (目前主要针对JSON)"""
    file_path = (BASE_DIR / request.path).resolve()
    validate_document_path(file_path, writable=True)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            if request.content_type == "json":
                json.dump(request.content, f, ensure_ascii=False, indent=2)
            else: # 假设其他类型都是纯文本
                f.write(str(request.content)) # 前端需要确保 content 是字符串
        return {"status": "success", "message": f"文件已保存: {file_path}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

@app.websocket("/ws/run-script")
async def run_script_ws(websocket: WebSocket):
    """通过 WebSocket 运行脚本并实时流式传输日志"""
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        req = RunScriptRequest(**data)

        # 将相对脚本路径解析为绝对路径
        script_abs_path = (APP_DIR / req.script_path).resolve()
        if not script_abs_path.is_file():
            # 使用 FAILURE 前缀，并确保后面有关闭连接的逻辑
            await websocket.send_text(f"FAILURE: 脚本不存在: {script_abs_path}")
            await websocket.close()
            return
        
        # 在 run_script_ws 中检查
        script_name = Path(req.script_path).name
        if script_name not in ALLOWED_SCRIPTS or script_abs_path.parent != APP_DIR.resolve():
            await websocket.send_text(f"FAILURE: 不允许执行脚本: {script_name}")
            await websocket.close()
            return

        # 使用与 FastAPI 相同的 Python 解释器
        command = [sys.executable, str(script_abs_path)] + req.args # 注意：create_subprocess_exec 会自动处理带空格的参数，不需要手动加引号
        await websocket.send_text(f"INFO: 开始执行命令: {' '.join(command)}")

        # --- 设置环境变量 ---
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=BASE_DIR,
            env=env  # <--- 将修改后的环境变量传给子进程
        )

        # --- 智能解析日志 ---
        async def stream_and_parse_logs(stream, default_prefix):
            log_level_pattern = re.compile(r'\s-\s(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s-')
            
            while not stream.at_eof():
                line_bytes = await stream.readline()
                if line_bytes:
                    line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                    if not line_str:
                        continue

                    # 尝试从日志内容中匹配真实的日志级别
                    match = log_level_pattern.search(line_str)
                    if match:
                        # 如果匹配成功，使用真实的日志级别作为前缀
                        prefix = match.group(1)
                    else:
                        # 如果不匹配 (例如普通的 print 输出)，使用默认前缀
                        prefix = default_prefix
                    
                    await websocket.send_text(f"{prefix}: {line_str}")

        # --- 同时处理 stdout 和 stderr ---
        await asyncio.gather(
            stream_and_parse_logs(process.stdout, "LOG"),   # stdout 的默认前缀是 LOG
            stream_and_parse_logs(process.stderr, "INFO")   # stderr 的默认前缀是 INFO
        )

        await process.wait()
        if process.returncode == 0:
            logging.info(f"脚本 {req.script_path} 成功完成。")
            await websocket.send_text(f"SUCCESS: 任务成功完成，退出码: {process.returncode}")
        else:
            logging.warning(f"脚本 {req.script_path} 失败，退出码: {process.returncode}")
            await websocket.send_text(f"FAILURE: 任务失败，退出码: {process.returncode}")

    except WebSocketDisconnect:
        logging.info("客户端断开连接")
    except Exception as e:
        logging.error(f"WebSocket 发生错误: {e}")
        await websocket.send_text(f"FATAL_ERROR: {str(e)}")
    finally:
        if websocket.client_state.name == 'CONNECTED':
            await websocket.close()

@app.get("/api/download")
def download_file(path: str):
    """下载指定的文件 (用于PDF等二进制文件)"""
    file_path = (BASE_DIR / path).resolve()
    validate_document_path(file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(file_path)

@app.post("/api/log_edit")
async def log_edit(request: EditLogRequest):
    """记录一次人工编辑操作"""
    try:
        # 从文件路径中提取药品名
        parts = Path(request.file_path).parts
        drug_name = re.sub(r"[^\w.-]", "_", parts[0]) if parts else "unknown_drug"
        log_file_path = EDIT_LOGS_DIR / f"{drug_name}_edit_log.jsonl"

        log_entry = {
            "timestamp": request.timestamp,
            "file_path": request.file_path,
            "diff": request.diff
        }

        # 使用 .jsonl (JSON Lines) 格式，每次追加一行，对处理大量日志更友好
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        
        return JSONResponse(content={"status": "success", "message": "编辑日志已记录"}, status_code=200)

    except Exception as e:
        logging.error(f"记录编辑日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"记录编辑日志失败: {e}")

@app.get("/")
def read_root():
    return {"message": "欢迎使用 MedRuleExtractor Web 助手 API"}

if __name__ == "__main__":
    import uvicorn
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    setup_webapp_logging(log_dir)
    logging.info(f"项目根目录: {BASE_DIR}")
    logging.info(f"结果目录: {RESULTS_DIR}")
    uvicorn.run(app, host="127.0.0.1", port=5000)

