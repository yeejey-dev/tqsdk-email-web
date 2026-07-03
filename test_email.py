"""
SMTP 邮件发送诊断脚本
同步执行，带详细日志，用于排查「邮件发送成功但收不到」的问题
"""
import smtplib
import ssl
import json
import os
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def load_config():
    """从 config_export.json 加载邮件配置"""
    config_path = os.path.join(os.path.dirname(__file__), "data", "config_export.json")
    if not os.path.exists(config_path):
        print(f"错误: 未找到配置文件 {config_path}")
        print("请先在 Web 界面点击「保存配置」生成该文件")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    email_config = config.get("email", {})
    if not email_config.get("sender_email") or not email_config.get("sender_password"):
        print("错误: 配置文件中缺少邮件发送信息")
        sys.exit(1)

    return email_config


# 从配置文件加载
_email_config = load_config()
SMTP_SERVER = _email_config.get("smtp_server", "smtp.qq.com")
SMTP_PORT = _email_config.get("smtp_port", 465)
SENDER_EMAIL = _email_config["sender_email"]
SENDER_PASSWORD = _email_config["sender_password"]
RECEIVER_EMAIL = _email_config.get("receiver_emails", [SENDER_EMAIL])[0]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def build_test_body():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<html><body>
<h2>SMTP 发送测试</h2>
<p>发送时间: {now}</p>
<p>这是一封测试邮件，用于验证 TqSdk 期货监控系统的邮件发送功能。</p>
<table style="border-collapse:collapse;">
<tr><th>合约</th><th>最新价</th><th>涨跌幅</th></tr>
<tr><td>SHFE.al2610</td><td>20500</td><td style="color:red;">+1.25%</td></tr>
<tr><td>CZCE.SR701</td><td>5800</td><td style="color:green;">-0.34%</td></tr>
</table>
<hr/><p style="color:#888;font-size:12px;">TqSdk SMTP 诊断测试邮件</p>
</body></html>"""


def test_smtp(mode, server, port, use_ssl=False):
    """单次 SMTP 测试"""
    log(f"{'='*50}")
    log(f"测试模式: {mode} | 服务器: {server}:{port}")
    try:
        # 1. 建立连接
        log(f"[1/5] 建立连接...")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        if use_ssl:
            server_obj = smtplib.SMTP_SSL(server, port, timeout=15, context=ctx)
            log(f"  → SSL 连接成功")
        else:
            server_obj = smtplib.SMTP(server, port, timeout=15)
            log(f"  → TCP 连接成功")
            log(f"[2/5] STARTTLS 升级...")
            server_obj.starttls(context=ctx)
            log(f"  → TLS 升级成功")

        # 2. EHLO
        log(f"[3/5] EHLO 握手...")
        ehlo_resp = server_obj.ehlo()
        log(f"  → 服务器响应: {ehlo_resp[0]}")

        # 3. 登录
        log(f"[4/5] SMTP 登录 (user={SENDER_EMAIL})...")
        server_obj.login(SENDER_EMAIL, SENDER_PASSWORD)
        log(f"  → 登录成功！")

        # 4. 构建并发送邮件
        log(f"[5/5] 发送邮件...")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"SMTP测试 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECEIVER_EMAIL
        msg.attach(MIMEText(build_test_body(), "html", "utf-8"))

        senders = server_obj.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        log(f"  → sendmail() 返回: {senders}")

        # 5. 退出
        server_obj.quit()
        log(f"  → 连接已关闭")
        log(f"✅ {mode} 模式测试成功！请检查收件箱和垃圾邮件文件夹。")
        return True

    except smtplib.SMTPAuthenticationError as e:
        log(f"❌ SMTP 认证失败: {e}")
        log(f"   原因: 授权码错误或 SMTP 服务未开启")
        return False
    except smtplib.SMTPRecipientsRefused as e:
        log(f"❌ 收件人被拒绝: {e}")
        return False
    except smtplib.SMTPException as e:
        log(f"❌ SMTP 错误: {e}")
        return False
    except ConnectionRefusedError as e:
        log(f"❌ 连接被拒绝: {e}")
        return False
    except TimeoutError as e:
        log(f"❌ 连接超时: {e}")
        return False
    except Exception as e:
        log(f"❌ 未知错误: {e} ({type(e).__name__})")
        import traceback
        traceback.print_exc()
        return False


def main():
    log("SMTP 邮件发送诊断")
    log(f"发件人: {SENDER_EMAIL}")
    log(f"收件人: {RECEIVER_EMAIL}")
    log(f"授权码: {SENDER_PASSWORD[:4]}{'*' * (len(SENDER_PASSWORD)-4)}")
    log("")

    results = []

    # 测试 1: SSL on 465
    results.append(("SSL@465", test_smtp("SSL", SMTP_SERVER, 465, use_ssl=True)))

    log("")

    # 测试 2: TLS on 587
    results.append(("TLS@587", test_smtp("TLS", SMTP_SERVER, 587, use_ssl=False)))

    log("")
    log("=" * 50)
    log("诊断结果汇总:")
    for name, ok in results:
        log(f"  {'✅' if ok else '❌'} {name}")

    # 提示
    log("")
    if any(ok for _, ok in results):
        log("至少一种方式发送成功。如果收不到邮件，请检查:")
        log("  1. 垃圾邮件/广告邮件文件夹")
        log("  2. QQ 邮箱设置 → 反垃圾 → 添加白名单")
        log("  3. 是否设置了邮件过滤规则")
    else:
        log("所有方式均失败。请检查:")
        log("  1. 授权码是否正确（16位字母）")
        log("  2. QQ 邮箱 SMTP 服务是否已开启")
        log("  3. 网络是否正常")


if __name__ == "__main__":
    main()
