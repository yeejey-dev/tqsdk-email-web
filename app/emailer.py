"""邮件发送模块 - 复用 GUI 版 SSL/TLS 回退逻辑"""
from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import List, Dict

from .models import EmailConfig

logger = logging.getLogger("tqweb")


def _make_ssl_context() -> ssl.SSLContext:
    """创建宽松的 SSL context，避免证书验证导致的握手失败。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class EmailSender:
    def __init__(self, config: EmailConfig):
        self.config = config

    def _try_send(self, server: smtplib.SMTP, msg: MIMEMultipart) -> bool:
        logger.info("  [3/4] 正在登录 SMTP (user=%s, pwd_len=%d)...",
                     self.config.sender_email, len(self.config.sender_password))
        server.login(self.config.sender_email, self.config.sender_password)
        logger.info("  [3/4] 登录成功！")
        logger.info("  [4/4] 正在发送邮件 → %s ...", self.config.receiver_emails)
        server.sendmail(
            self.config.sender_email,
            self.config.receiver_emails,
            msg.as_string(),
        )
        logger.info("  [4/4] SMTP 服务器已接受邮件！")
        server.quit()
        return True

    def _attempt_once(self, mode: str, server_addr: str, port: int,
                      msg: MIMEMultipart, subject: str) -> bool:
        """单次连接尝试，带分阶段日志。"""
        try:
            ctx = _make_ssl_context()
            if mode == "SSL":
                logger.info("  [1/4] 尝试 SSL 连接 %s:%s ...", server_addr, port)
                server = smtplib.SMTP_SSL(server_addr, port, timeout=15, context=ctx)
            else:
                logger.info("  [1/4] 尝试 TCP 连接 %s:%s ...", server_addr, port)
                server = smtplib.SMTP(server_addr, port, timeout=15)
                logger.info("  [2/4] 尝试 STARTTLS 升级...")
                server.starttls(context=ctx)
            logger.info("  [2/4] 连接建立成功！")
            server.set_debuglevel(0)
            ok = self._try_send(server, msg)
            if ok:
                logger.info("✅ [%s@%s] 邮件发送成功 → %s", mode, port, self.config.receiver_emails)
                return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error("❌ [%s@%s] SMTP 认证失败: %s", mode, port, e)
        except smtplib.SMTPServerDisconnected as e:
            logger.warning("⚠️ [%s@%s] 服务器断开连接: %s", mode, port, e)
        except Exception as e:
            logger.warning("⚠️ [%s@%s] 连接错误: %s (%s)", mode, port, e, type(e).__name__)
        return False

    def send(self, subject: str, body_html: str) -> bool:
        if not self.config.smtp_server or not self.config.sender_email:
            logger.warning("邮件配置不完整（缺少 SMTP 服务器或发件人），跳过发送")
            return False
        if not self.config.receiver_emails:
            logger.warning("收件人列表为空，跳过发送")
            return False
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.sender_email
        msg["To"] = ", ".join(self.config.receiver_emails)
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        server_addr = self.config.smtp_server.strip()
        port = self.config.smtp_port

        # 根据配置选择优先连接方式
        use_ssl_first = port == 465 or not self.config.use_tls
        if use_ssl_first:
            order = [("SSL", port), ("TLS", 587)]
        else:
            order = [("TLS", port), ("SSL", 465)]

        logger.info("📧 开始发送邮件 [%s] → %s (收件人: %s)", subject[:30], server_addr, self.config.receiver_emails)

        # 每种方式重试 2 次（间隔 3 秒），应对 QQ 临时风控
        for mode, p in order:
            for attempt in range(2):
                if attempt > 0:
                    logger.info("  [%s@%s] 第 %d 次重试（等待 3 秒）...", mode, p, attempt + 1)
                    time.sleep(3)
                if self._attempt_once(mode, server_addr, p, msg, subject):
                    return True

        logger.error("❌ 所有 SMTP 连接方式均失败（已重试）")
        return False

    def build_email_body(self, updates: List[dict], alerts_map: Dict[str, List[str]]) -> str:
        rows = ""
        for u in updates:
            change_pct_str = (
                f"{u['change_pct']:+.2f}%" if u.get("change_pct") is not None else "--"
            )
            color = "#dc2626" if (u.get("change_pct") or 0) >= 0 else "#16a34a"
            rows += f"""
            <tr>
                <td style="padding:10px;border:1px solid #ddd;">{u['display_name']}</td>
                <td style="padding:10px;border:1px solid #ddd;">{u['symbol']}</td>
                <td style="padding:10px;border:1px solid #ddd;">{u['last_price']}</td>
                <td style="padding:10px;border:1px solid #ddd;color:{color};">{change_pct_str}</td>
                <td style="padding:10px;border:1px solid #ddd;">{u['volume']}</td>
                <td style="padding:10px;border:1px solid #ddd;">{u['open_interest']}</td>
                <td style="padding:10px;border:1px solid #ddd;">{u['datetime']}</td>
            </tr>"""
        alerts_html = ""
        has_alerts = False
        for symbol, alerts in alerts_map.items():
            if alerts:
                has_alerts = True
                display_name = next(
                    (u["display_name"] for u in updates if u["symbol"] == symbol), symbol
                )
                for alert in alerts:
                    alerts_html += f'<li style="margin:4px 0;"><strong>{display_name}</strong>: {alert}</li>'
        alerts_section = ""
        if has_alerts:
            alerts_section = f"""
            <div style="margin-top:20px;padding:16px;background:#fef2f2;border:1px solid #fecaca;border-radius:8px;">
                <h3 style="color:#dc2626;margin:0 0 10px 0;font-size:16px;">预警信息</h3>
                <ul style="color:#991b1b;margin:0;padding-left:20px;">{alerts_html}</ul>
            </div>"""
        return f"""<html><body>
            <h2>期货实时价格推送</h2>
            <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <table style="border-collapse:collapse;width:100%;max-width:800px;">
                <thead style="background:#f2f2f2;">
                    <tr><th style="padding:10px;border:1px solid #ddd;">名称</th>
                    <th style="padding:10px;border:1px solid #ddd;">合约</th>
                    <th style="padding:10px;border:1px solid #ddd;">最新价</th>
                    <th style="padding:10px;border:1px solid #ddd;">涨跌幅</th>
                    <th style="padding:10px;border:1px solid #ddd;">成交量</th>
                    <th style="padding:10px;border:1px solid #ddd;">持仓量</th>
                    <th style="padding:10px;border:1px solid #ddd;">时间</th></tr>
                </thead><tbody>{rows}</tbody>
            </table>{alerts_section}
            <hr/><p style="color:#888;font-size:12px;">本邮件由 TqSdk 期货价格监控 Web 服务自动发送</p>
        </body></html>"""
