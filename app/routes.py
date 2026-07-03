"""REST API 路由"""
from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import database as db
from .models import (
    ContractConfig,
    EmailConfig,
    FullConfig,
    ScheduleConfig,
    TqAuthConfig,
)
from .tracker import app_state, ws_log_handler

logger = logging.getLogger("tqweb")
router = APIRouter(prefix="/api")

_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------
@router.get("/status")
async def get_status():
    status = app_state.get_status()
    prices = app_state.get_current_prices()
    return {"running": status["running"], "message": status["message"], "prices": prices}


# ---------------------------------------------------------------------------
# 服务控制
# ---------------------------------------------------------------------------
class StartRequest(BaseModel):
    username: str = ""
    password: str = ""


@router.post("/start")
async def start_service(req: StartRequest):
    # 优先用请求体中的账号，其次用数据库已存的
    tq_auth = TqAuthConfig(username=req.username, password=req.password)
    if not tq_auth.username:
        tq_auth = db.get_tq_auth()
    else:
        db.set_tq_auth(tq_auth)
    ok, msg = app_state.start(tq_auth)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/stop")
async def stop_service():
    ok, msg = app_state.stop()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


# ---------------------------------------------------------------------------
# 快期认证
# ---------------------------------------------------------------------------
@router.get("/auth")
async def get_auth():
    auth = db.get_tq_auth()
    # 不返回密码明文，只返回是否已配置
    return {"username": auth.username, "has_password": bool(auth.password)}


@router.put("/auth")
async def set_auth(auth: TqAuthConfig):
    db.set_tq_auth(auth)
    return {"message": "快期账户已保存"}


# ---------------------------------------------------------------------------
# 合约 CRUD
# ---------------------------------------------------------------------------
@router.get("/contracts")
async def get_contracts():
    return db.get_contracts()


@router.post("/contracts")
async def add_contract(contract: ContractConfig):
    if not contract.symbol or "." not in contract.symbol:
        raise HTTPException(status_code=400, detail="合约代码格式错误，应为 EXCHANGE.code 如 SHFE.au2508")
    saved = db.add_contract(contract)
    logger.info("已添加合约: %s", saved.symbol)
    return saved


@router.delete("/contracts/{cid}")
async def delete_contract(cid: int):
    if not db.delete_contract(cid):
        raise HTTPException(status_code=404, detail="合约不存在")
    logger.info("已删除合约 id=%s", cid)
    return {"message": "已删除"}


# ---------------------------------------------------------------------------
# 邮件配置
# ---------------------------------------------------------------------------
@router.get("/email")
async def get_email():
    cfg = db.get_email_config()
    return cfg


@router.put("/email")
async def set_email(cfg: EmailConfig):
    db.set_email_config(cfg)
    logger.info("邮件配置已更新")
    return {"message": "邮件配置已保存"}


# ---------------------------------------------------------------------------
# 时间配置
# ---------------------------------------------------------------------------
@router.get("/schedule")
async def get_schedule():
    return db.get_schedule_config()


@router.put("/schedule")
async def set_schedule(cfg: ScheduleConfig):
    db.set_schedule_config(cfg)
    logger.info("时间配置已更新")
    return {"message": "时间配置已保存"}


# ---------------------------------------------------------------------------
# 配置导入/导出
# ---------------------------------------------------------------------------
@router.post("/save_config")
async def save_config(path: Optional[str] = None):
    full = FullConfig(
        tq_auth=db.get_tq_auth(),
        contracts=db.get_contracts(),
        email=db.get_email_config(),
        schedule=db.get_schedule_config(),
    )
    if not path:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        path = os.path.join(_CONFIG_DIR, "config_export.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(full.model_dump(), f, ensure_ascii=False, indent=2)
    logger.info("配置已导出到: %s", path)
    return {"message": "配置已保存", "path": path}


class LoadConfigRequest(BaseModel):
    path: Optional[str] = None


@router.post("/load_config")
async def load_config(req: LoadConfigRequest):
    path = req.path
    if not path:
        path = os.path.join(_CONFIG_DIR, "config_export.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    full = FullConfig(**data)
    if full.tq_auth.username:
        db.set_tq_auth(full.tq_auth)
    db.replace_contracts(full.contracts)
    db.set_email_config(full.email)
    db.set_schedule_config(full.schedule)
    logger.info("配置已从 %s 加载", path)
    return {"message": "配置已加载", "config": full.model_dump()}


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
@router.get("/logs")
async def get_logs(n: int = 200):
    return {"lines": ws_log_handler.get_recent(n)}


@router.delete("/logs")
async def clear_logs():
    ws_log_handler._buffer.clear()
    return {"message": "日志已清空"}
