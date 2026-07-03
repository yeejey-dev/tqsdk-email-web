#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""期货实时价格邮件提醒 Web 服务 - 启动脚本

用法:
    python run.py                  # 默认 0.0.0.0:5000
    python run.py --port 8080      # 自定义端口
    python run.py --host 127.0.0.1 --port 5000
"""
import argparse
import sys

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="期货实时价格邮件提醒 Web 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=5000, help="监听端口，默认 5000")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()

    print(f"启动服务: http://{args.host}:{args.port}")
    print("按 Ctrl+C 停止")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
