"""WebSocket 连接管理器 - 线程安全桥接 TqSdk 后台线程与 asyncio 事件循环"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Set

from fastapi import WebSocket

logger = logging.getLogger("tqweb")


class WebSocketManager:
    """管理所有前端 WebSocket 连接，支持从任意线程安全广播。"""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """在 FastAPI 启动时由事件循环线程调用，捕获 loop 引用。"""
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("WebSocket 客户端已连接，当前连接数: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("WebSocket 客户端已断开，当前连接数: %d", len(self._connections))

    async def _broadcast(self, event: str, data: Any) -> None:
        """在事件循环中执行的实际广播（async）。"""
        if not self._connections:
            return
        message = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    def broadcast_from_thread(self, event: str, data: Any) -> None:
        """从后台线程安全调度广播到事件循环。"""
        if self._loop is None or not self._connections:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(event, data), self._loop)
        except Exception as e:
            logger.debug("广播调度失败: %s", e)


# 全局单例
ws_manager = WebSocketManager()
