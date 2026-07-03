"""TqSdk 行情监控服务 - 后台线程运行 wait_update 循环"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .database import get_contracts, get_email_config, get_schedule_config
from .emailer import EmailSender
from .models import ContractConfig, EmailConfig, ScheduleConfig, TqAuthConfig
from .ws_manager import ws_manager

logger = logging.getLogger("tqweb")


class PriceCache:
    def __init__(self):
        self._data: Dict[str, dict] = {}
        self._last_send: Dict[str, datetime] = {}

    def update(self, symbol: str, price_info: dict):
        self._data[symbol] = price_info

    def get(self, symbol: str) -> Optional[dict]:
        return self._data.get(symbol)

    def all(self) -> Dict[str, dict]:
        return dict(self._data)

    def should_send(self, symbol: str, interval_seconds: int) -> bool:
        last = self._last_send.get(symbol)
        if not last:
            return True
        return (datetime.now() - last).total_seconds() >= interval_seconds

    def mark_sent(self, symbol: str):
        self._last_send[symbol] = datetime.now()


class WSLogHandler(logging.Handler):
    """将日志通过 WebSocket 实时推送到前端。"""

    def __init__(self):
        super().__init__()
        self._buffer: list[str] = []
        self._buffer_lock = threading.Lock()

    def emit(self, record):
        msg = self.format(record)
        with self._buffer_lock:
            self._buffer.append(msg)
            if len(self._buffer) > 500:
                self._buffer = self._buffer[-500:]
        ws_manager.broadcast_from_thread(
            "log_update", {"line": msg, "level": record.levelname}
        )

    def get_recent(self, n: int = 200) -> List[str]:
        with self._buffer_lock:
            return list(self._buffer[-n:])


ws_log_handler = WSLogHandler()


class FuturesPriceTracker:
    """行情监控服务，运行在后台 daemon 线程中。"""

    def __init__(self, tq_auth_config: TqAuthConfig):
        self.tq_auth_config = tq_auth_config
        self._api = None
        self._quotes: Dict[str, Any] = {}
        self._stop_requested = False
        self.cache = PriceCache()
        self._email_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email")

        # 配置缓存（线程安全刷新）
        self._config_lock = threading.Lock()
        self._cached_contracts: List[ContractConfig] = []
        self._cached_email: EmailConfig = EmailConfig()
        self._cached_schedule: ScheduleConfig = ScheduleConfig()
        self._last_config_refresh = 0.0
        self._subscribed_symbols: set[str] = set()

        self._on_started: Optional[Callable[[bool, str], None]] = None

    def set_on_started(self, cb: Callable[[bool, str], None]):
        self._on_started = cb

    def stop(self):
        self._stop_requested = True
        # api.close() 可能同步阻塞（等待后台任务结束），
        # 放到独立线程执行，避免卡死 FastAPI 事件循环。
        if self._api:
            def _safe_close():
                try:
                    self._api.close()
                except Exception as e:
                    logger.debug("api.close() 异常: %s", e)
            threading.Thread(target=_safe_close, daemon=True, name="tqsdk-close").start()

    def _refresh_config(self, force: bool = False):
        """从数据库刷新配置缓存（节流：最多每 3 秒一次，除非 force）。"""
        now = time.time()
        if not force and (now - self._last_config_refresh) < 3:
            return
        self._last_config_refresh = now
        with self._config_lock:
            self._cached_contracts = get_contracts()
            self._cached_email = get_email_config()
            self._cached_schedule = get_schedule_config()

    def _refresh_subscriptions(self):
        """动态订阅新增合约，移除已删除合约的追踪。"""
        with self._config_lock:
            contracts = list(self._cached_contracts)
        current_symbols = {c.symbol for c in contracts}
        # 新增订阅
        for c in contracts:
            if c.symbol not in self._subscribed_symbols and self._api is not None:
                try:
                    self._quotes[c.symbol] = self._api.get_quote(c.symbol)
                    self._subscribed_symbols.add(c.symbol)
                    logger.info("已订阅行情: %s", c.symbol)
                except Exception as e:
                    logger.error("订阅合约 %s 失败: %s", c.symbol, e)
        # 移除追踪（TqSdk 无法显式取消订阅，仅停止追踪）
        removed = self._subscribed_symbols - current_symbols
        for sym in removed:
            self._quotes.pop(sym, None)
            self._subscribed_symbols.discard(sym)
            logger.info("已停止追踪合约: %s", sym)

    @staticmethod
    def _is_trading_time(schedule: ScheduleConfig) -> bool:
        now = datetime.now().time()
        from datetime import datetime as _dt

        fmt = "%H:%M"
        try:
            day_start = _dt.strptime(schedule.market_open_time, fmt).time()
            day_end = _dt.strptime(schedule.market_close_time, fmt).time()
            if day_start <= now <= day_end:
                return True
        except Exception:
            pass
        if schedule.night_session_start and schedule.night_session_end:
            try:
                night_start = _dt.strptime(schedule.night_session_start, fmt).time()
                night_end = _dt.strptime(schedule.night_session_end, fmt).time()
                if night_start <= night_end:
                    if night_start <= now <= night_end:
                        return True
                else:
                    if now >= night_start or now <= night_end:
                        return True
            except Exception:
                pass
        return False

    @staticmethod
    def _check_alerts(info: dict, contract: ContractConfig) -> List[str]:
        alerts = []
        price = info.get("last_price")
        change_pct = info.get("change_pct")
        if (
            contract.price_high is not None
            and price is not None
            and price > contract.price_high
        ):
            alerts.append(f"价格预警：当前价 {price} 高于上限 {contract.price_high}")
        if (
            contract.price_low is not None
            and price is not None
            and price < contract.price_low
        ):
            alerts.append(f"价格预警：当前价 {price} 低于下限 {contract.price_low}")
        if (
            contract.change_pct_high is not None
            and change_pct is not None
            and change_pct > contract.change_pct_high
        ):
            alerts.append(
                f"涨跌幅预警：当前 {change_pct:.2f}% 高于上限 {contract.change_pct_high}%"
            )
        if (
            contract.change_pct_low is not None
            and change_pct is not None
            and change_pct < contract.change_pct_low
        ):
            alerts.append(
                f"涨跌幅预警：当前 {change_pct:.2f}% 低于下限 {contract.change_pct_low}%"
            )
        return alerts

    def _extract_price_info(
        self, symbol: str, quote, contract: ContractConfig
    ) -> dict:
        last_price = getattr(quote, "last_price", None)
        pre_close = getattr(quote, "pre_close", None)
        settlement = getattr(quote, "settlement", None)
        change_pct = None
        base_price = pre_close or settlement
        if last_price is not None and base_price is not None and base_price != 0:
            change_pct = (last_price - base_price) / base_price * 100
        change_pct_str = (
            f"{change_pct:+.2f}%" if change_pct is not None else "--"
        )
        return {
            "symbol": symbol,
            "display_name": contract.display_name(),
            "last_price": last_price,
            "change_pct": change_pct,
            "change_pct_str": change_pct_str,
            "volume": getattr(quote, "volume", None),
            "open_interest": getattr(quote, "open_interest", None),
            "datetime": str(getattr(quote, "datetime", "") or ""),
            "alerts": [],
        }

    def _send_batch_email(self, updates: List[dict], alerts_map: Dict[str, List[str]]):
        """同步执行邮件发送，返回是否成功。"""
        if not updates:
            return False
        with self._config_lock:
            email_cfg = self._cached_email
        if not email_cfg.smtp_server:
            logger.warning("邮件 SMTP 服务器未配置，跳过发送")
            return False
        sender = EmailSender(email_cfg)
        subject = f"期货实时价格推送 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        body = sender.build_email_body(updates, alerts_map)

        def _do_send():
            return sender.send(subject, body)

        future = self._email_executor.submit(_do_send)
        try:
            result = future.result(timeout=60)  # 等待最多60秒
            return result
        except Exception as e:
            logger.error("邮件发送超时或异常: %s", e)
            return False

    def run(self):
        from tqsdk import TqApi, TqAuth

        logger.info("正在连接快期行情服务器...")
        try:
            self._api = TqApi(
                auth=TqAuth(self.tq_auth_config.username, self.tq_auth_config.password)
            )
        except Exception as e:
            logger.error("快期账户连接失败: %s", e)
            if self._on_started:
                self._on_started(False, f"快期账户连接失败: {e}")
            return

        logger.info("快期账户连接成功")
        # 初始加载配置并订阅
        self._refresh_config(force=True)
        self._refresh_subscriptions()

        if self._on_started:
            self._on_started(True, "服务已启动")

        try:
            last_email_sent_ts = 0.0       # 全局上次发送邮件的时间戳
            pending_email = False          # 是否有待发送的变化（去抖动）
            debounce_deadline = 0.0        # 去抖动窗口结束时间戳
            DEBOUNCE_WINDOW = 3.0          # 去抖动窗口（秒）：3秒内的所有变化合并成一份邮件

            while not self._stop_requested:
                # 周期性刷新配置（支持运行时修改邮件/时间配置）
                self._refresh_config()
                # 动态订阅新增合约
                self._refresh_subscriptions()

                with self._config_lock:
                    schedule = self._cached_schedule
                    contracts = list(self._cached_contracts)

                # wait_update 即使超时返回 False，也继续走邮件定时检查
                self._api.wait_update(deadline=time.time() + 5)

                # 交易时段过滤（仅影响邮件发送，不影响行情推送）
                in_trading = not (
                    schedule.trading_hours_only
                    and not self._is_trading_time(schedule)
                )

                # ---- 1. 行情变化检测 + 前端实时推送 ----
                changed = False
                alerts_map: Dict[str, List[str]] = {}
                for contract in contracts:
                    symbol = contract.symbol
                    quote = self._quotes.get(symbol)
                    if quote is None:
                        continue
                    if self._api.is_changing(
                        quote, ["last_price", "volume", "open_interest"]
                    ):
                        changed = True
                        info = self._extract_price_info(symbol, quote, contract)
                        alerts = self._check_alerts(info, contract)
                        info["alerts"] = alerts
                        alerts_map[symbol] = alerts
                        self.cache.update(symbol, info)
                        # 实时推送到前端
                        ws_manager.broadcast_from_thread("price_update", info)

                # 预警实时推送（不依赖邮件）
                for sym, alts in alerts_map.items():
                    if alts:
                        ws_manager.broadcast_from_thread(
                            "alert", {"symbol": sym, "alerts": alts}
                        )

                # ---- 2. 邮件发送：去抖动合并，确保一个事件只发一份邮件 ----
                now_ts = time.time()
                should_send_email = False

                if schedule.send_on_interval_only:
                    # 模式A：仅按间隔发送
                    # 到间隔就发一封全量快照，不依赖变化检测
                    if in_trading and (
                        last_email_sent_ts == 0.0
                        or (now_ts - last_email_sent_ts)
                        >= schedule.check_interval_seconds
                    ):
                        should_send_email = True
                else:
                    # 模式B：变化触发 + 去抖动合并
                    # 检测到任一变化 → 标记 pending，开启去抖动窗口
                    # 窗口内的新变化持续累积（不重置窗口，避免无限延后）
                    # 窗口结束后发一份全量快照
                    if changed and in_trading:
                        if not pending_email:
                            pending_email = True
                            debounce_deadline = now_ts + DEBOUNCE_WINDOW
                            logger.debug(
                                "检测到行情变化，开启 %ss 去抖动窗口",
                                DEBOUNCE_WINDOW,
                            )
                    # 去抖动窗口结束 → 发送
                    if pending_email and now_ts >= debounce_deadline and in_trading:
                        should_send_email = True
                        pending_email = False

                if should_send_email:
                    # 收集所有合约当前快照（全量表格，不仅仅是本次变化的）
                    all_updates: List[dict] = []
                    all_alerts: Dict[str, List[str]] = {}
                    for contract in contracts:
                        symbol = contract.symbol
                        quote = self._quotes.get(symbol)
                        if quote is None:
                            continue
                        info = self._extract_price_info(symbol, quote, contract)
                        alerts = self._check_alerts(info, contract)
                        info["alerts"] = alerts
                        all_updates.append(info)
                        if alerts:
                            all_alerts[symbol] = alerts
                    if all_updates:
                        sent_ok = self._send_batch_email(all_updates, all_alerts)
                        last_email_sent_ts = now_ts
                        if sent_ok:
                            logger.info(
                                "✅ 邮件发送成功，包含 %d 个合约", len(all_updates)
                            )
                        else:
                            logger.error(
                                "❌ 邮件发送失败！包含 %d 个合约（检查上方 SMTP 详细日志）", len(all_updates)
                            )
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在退出...")
        except Exception as e:
            logger.error("行情服务异常: %s", e)
        finally:
            try:
                if self._api:
                    self._api.close()
            except Exception:
                pass
            self._email_executor.shutdown(wait=False)
            logger.info("行情监控服务已停止")


class AppState:
    """全局应用状态单例 - 管理监控服务的生命周期。"""

    def __init__(self):
        self.tracker: Optional[FuturesPriceTracker] = None
        self.tracker_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_error = ""
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._running

    def start(self, tq_auth_config: TqAuthConfig) -> tuple[bool, str]:
        with self._lock:
            if self._running:
                return False, "服务已在运行中"
            contracts = get_contracts()
            if not contracts:
                return False, "请至少添加一个期货合约"
            if not tq_auth_config.username or not tq_auth_config.password:
                return False, "请先填写快期账户用户名和密码"

            self.tracker = FuturesPriceTracker(tq_auth_config)
            started_event = threading.Event()
            start_result = {"ok": False, "msg": ""}

            def on_started(ok: bool, msg: str):
                start_result["ok"] = ok
                start_result["msg"] = msg
                started_event.set()

            self.tracker.set_on_started(on_started)
            self._running = True
            self._last_error = ""

            self.tracker_thread = threading.Thread(
                target=self._tracker_loop, daemon=True, name="tqsdk-tracker"
            )
            self.tracker_thread.start()

        # 等待连接结果（最多 30 秒）
        started_event.wait(timeout=30)
        if not start_result["ok"]:
            with self._lock:
                self._running = False
                self._last_error = start_result["msg"]
            ws_manager.broadcast_from_thread(
                "status_change",
                {"running": False, "message": start_result["msg"]},
            )
            return False, start_result["msg"]

        ws_manager.broadcast_from_thread(
            "status_change", {"running": True, "message": "服务运行中"}
        )
        return True, "服务已启动"

    def _tracker_loop(self):
        try:
            if self.tracker:
                self.tracker.run()
        except Exception as e:
            logger.error("tracker 线程异常: %s", e)
        finally:
            with self._lock:
                self._running = False
            ws_manager.broadcast_from_thread(
                "status_change", {"running": False, "message": "服务已停止"}
            )

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if not self._running or not self.tracker:
                return False, "服务未在运行"
            # 锁内仅标记状态，避免与 _tracker_loop 的 finally 块争锁
            self._running = False
            tracker = self.tracker
        # 锁外执行停止操作（tracker.stop 不阻塞，api.close 在独立线程）
        logger.info("正在停止监控服务...")
        tracker.stop()
        ws_manager.broadcast_from_thread(
            "status_change", {"running": False, "message": "服务已停止"}
        )
        return True, "服务已停止"

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "message": self._last_error if self._last_error else (
                "服务运行中" if self._running else "服务已停止"
            ),
        }

    def get_current_prices(self) -> Dict[str, dict]:
        if self.tracker:
            return self.tracker.cache.all()
        return {}


app_state = AppState()
