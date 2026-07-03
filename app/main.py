"""FastAPI 主应用 - 入口、生命周期、WebSocket 端点、静态文件挂载"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import database as db
from .routes import router
from .tracker import app_state, ws_log_handler
from .ws_manager import ws_manager

logger = logging.getLogger("tqweb")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC_DIR = os.path.join(_BASE_DIR, "static")


def setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    )
    ws_log_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 避免重复添加
    if ws_log_handler not in root.handlers:
        root.addHandler(ws_log_handler)
    # 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    if console not in root.handlers:
        root.addHandler(console)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    db.init_db()
    ws_manager.set_loop(asyncio.get_running_loop())
    logger.info("=== 期货价格监控 Web 服务启动 ===")
    logger.info("数据库: %s", db.DB_PATH)
    logger.info("静态目录: %s", _STATIC_DIR)
    yield
    if app_state.running:
        app_state.stop()
    logger.info("=== 服务已关闭 ===")


app = FastAPI(title="期货实时价格邮件提醒", version="1.0.0", lifespan=lifespan)
app.include_router(router)


# WebSocket 端点
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    # 连接时立即推送当前状态与行情快照
    status = app_state.get_status()
    await websocket.send_text(
        f'{{"event":"status_change","data":{{"running":{str(status["running"]).lower()},"message":"{status["message"]}"}}}}'
    )
    prices = app_state.get_current_prices()
    if prices:
        import json

        await websocket.send_text(
            json.dumps({"event": "price_update_all", "data": prices}, ensure_ascii=False, default=str)
        )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# 前端首页
@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


# 静态资源（css/js）
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
