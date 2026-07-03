"""Pydantic 数据模型 - API 请求/响应 schema"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ContractConfig(BaseModel):
    id: Optional[int] = None
    symbol: str = Field(..., description="合约代码，如 SHFE.au2508")
    alias: Optional[str] = Field(None, description="别名")
    price_high: Optional[float] = Field(None, description="价格上限")
    price_low: Optional[float] = Field(None, description="价格下限")
    change_pct_high: Optional[float] = Field(None, description="涨跌幅上限(%)")
    change_pct_low: Optional[float] = Field(None, description="涨跌幅下限(%)")

    def display_name(self) -> str:
        return self.alias if self.alias else self.symbol


class EmailConfig(BaseModel):
    smtp_server: str = ""
    smtp_port: int = 587
    sender_email: str = ""
    sender_password: str = ""
    receiver_emails: List[str] = []
    use_tls: bool = True


class ScheduleConfig(BaseModel):
    check_interval_seconds: int = 300
    send_on_interval_only: bool = True
    trading_hours_only: bool = True
    market_open_time: str = "09:00"
    market_close_time: str = "15:00"
    night_session_start: Optional[str] = None
    night_session_end: Optional[str] = None


class TqAuthConfig(BaseModel):
    username: str = ""
    password: str = ""


class FullConfig(BaseModel):
    """完整配置，用于导入/导出"""
    tq_auth: TqAuthConfig
    contracts: List[ContractConfig]
    email: EmailConfig
    schedule: ScheduleConfig


class PriceInfo(BaseModel):
    """单合约行情快照"""
    symbol: str
    display_name: str
    last_price: Optional[float] = None
    change_pct: Optional[float] = None
    change_pct_str: str = "--"
    volume: Optional[float] = None
    open_interest: Optional[float] = None
    datetime: str = ""
    alerts: List[str] = []


class ServiceStatus(BaseModel):
    running: bool
    message: str = ""
