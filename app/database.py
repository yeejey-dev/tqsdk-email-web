"""SQLite 配置持久化模块"""
from __future__ import annotations

import base64
import os
import sqlite3
import threading
from typing import List, Optional

from .models import ContractConfig, EmailConfig, ScheduleConfig, TqAuthConfig

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE_DIR, "data", "config.db")

# 简单可逆混淆（非强加密，单用户本地工具够用；如需强加密请加装 cryptography）
_OBF_KEY = b"tqsdk-web-monitor-2026"


def _obfuscate(text: str) -> str:
    if not text:
        return ""
    raw = text.encode("utf-8")
    out = bytes(b ^ _OBF_KEY[i % len(_OBF_KEY)] for i, b in enumerate(raw))
    return base64.b64encode(out).decode("ascii")


def _deobfuscate(token: str) -> str:
    if not token:
        return ""
    try:
        raw = base64.b64decode(token.encode("ascii"))
        out = bytes(b ^ _OBF_KEY[i % len(_OBF_KEY)] for i, b in enumerate(raw))
        return out.decode("utf-8")
    except Exception:
        return ""


_lock = threading.Lock()


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock:
        conn = get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                alias TEXT,
                price_high REAL,
                price_low REAL,
                change_pct_high REAL,
                change_pct_low REAL
            );
            CREATE TABLE IF NOT EXISTS email_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                smtp_server TEXT,
                smtp_port INTEGER,
                sender_email TEXT,
                sender_password TEXT,
                receiver_emails TEXT,
                use_tls INTEGER
            );
            CREATE TABLE IF NOT EXISTS schedule_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                check_interval_seconds INTEGER,
                send_on_interval_only INTEGER,
                trading_hours_only INTEGER,
                market_open_time TEXT,
                market_close_time TEXT,
                night_session_start TEXT,
                night_session_end TEXT
            );
            CREATE TABLE IF NOT EXISTS tq_auth (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT,
                password TEXT
            );
            """
        )
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# 合约 CRUD
# ---------------------------------------------------------------------------
def get_contracts() -> List[ContractConfig]:
    with _lock:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM contracts ORDER BY id").fetchall()
        conn.close()
    return [
        ContractConfig(
            id=r["id"],
            symbol=r["symbol"],
            alias=r["alias"],
            price_high=r["price_high"],
            price_low=r["price_low"],
            change_pct_high=r["change_pct_high"],
            change_pct_low=r["change_pct_low"],
        )
        for r in rows
    ]


def add_contract(c: ContractConfig) -> ContractConfig:
    with _lock:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO contracts (symbol, alias, price_high, price_low, change_pct_high, change_pct_low) "
            "VALUES (?,?,?,?,?,?)",
            (c.symbol, c.alias, c.price_high, c.price_low, c.change_pct_high, c.change_pct_low),
        )
        conn.commit()
        c.id = cur.lastrowid
        conn.close()
    return c


def delete_contract(cid: int) -> bool:
    with _lock:
        conn = get_conn()
        cur = conn.execute("DELETE FROM contracts WHERE id=?", (cid,))
        conn.commit()
        deleted = cur.rowcount > 0
        conn.close()
    return deleted


def replace_contracts(contracts: List[ContractConfig]) -> None:
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM contracts")
        for c in contracts:
            conn.execute(
                "INSERT INTO contracts (symbol, alias, price_high, price_low, change_pct_high, change_pct_low) "
                "VALUES (?,?,?,?,?,?)",
                (c.symbol, c.alias, c.price_high, c.price_low, c.change_pct_high, c.change_pct_low),
            )
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# 邮件配置（单行）
# ---------------------------------------------------------------------------
def get_email_config() -> EmailConfig:
    with _lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM email_config WHERE id=1").fetchone()
        conn.close()
    if not row:
        return EmailConfig()
    return EmailConfig(
        smtp_server=row["smtp_server"] or "",
        smtp_port=row["smtp_port"] or 587,
        sender_email=row["sender_email"] or "",
        sender_password=_deobfuscate(row["sender_password"] or ""),
        receiver_emails=[r for r in (row["receiver_emails"] or "").split(",") if r.strip()],
        use_tls=bool(row["use_tls"]),
    )


def set_email_config(c: EmailConfig) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO email_config "
            "(id, smtp_server, smtp_port, sender_email, sender_password, receiver_emails, use_tls) "
            "VALUES (1,?,?,?,?,?,?)",
            (
                c.smtp_server,
                c.smtp_port,
                c.sender_email,
                _obfuscate(c.sender_password),
                ",".join(c.receiver_emails),
                int(c.use_tls),
            ),
        )
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# 时间配置（单行）
# ---------------------------------------------------------------------------
def get_schedule_config() -> ScheduleConfig:
    with _lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM schedule_config WHERE id=1").fetchone()
        conn.close()
    if not row:
        return ScheduleConfig()
    return ScheduleConfig(
        check_interval_seconds=row["check_interval_seconds"] or 300,
        send_on_interval_only=bool(row["send_on_interval_only"]),
        trading_hours_only=bool(row["trading_hours_only"]),
        market_open_time=row["market_open_time"] or "09:00",
        market_close_time=row["market_close_time"] or "15:00",
        night_session_start=row["night_session_start"],
        night_session_end=row["night_session_end"],
    )


def set_schedule_config(c: ScheduleConfig) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO schedule_config "
            "(id, check_interval_seconds, send_on_interval_only, trading_hours_only, "
            "market_open_time, market_close_time, night_session_start, night_session_end) "
            "VALUES (1,?,?,?,?,?,?,?)",
            (
                c.check_interval_seconds,
                int(c.send_on_interval_only),
                int(c.trading_hours_only),
                c.market_open_time,
                c.market_close_time,
                c.night_session_start,
                c.night_session_end,
            ),
        )
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# 快期认证（单行，密码混淆）
# ---------------------------------------------------------------------------
def get_tq_auth() -> TqAuthConfig:
    with _lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM tq_auth WHERE id=1").fetchone()
        conn.close()
    if not row:
        return TqAuthConfig()
    return TqAuthConfig(
        username=row["username"] or "",
        password=_deobfuscate(row["password"] or ""),
    )


def set_tq_auth(c: TqAuthConfig) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO tq_auth (id, username, password) VALUES (1,?,?)",
            (c.username, _obfuscate(c.password)),
        )
        conn.commit()
        conn.close()
