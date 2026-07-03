# 期货实时价格邮件提醒 Web 应用

基于 TqSdk 的期货价格监控与邮件提醒 Web 服务，支持浏览器远程配置预警条件、查看实时行情、接收定时邮件推送，可部署在云服务器上 7×24 小时运行。

## 功能概览

- **快期账户登录**：使用 TqAuth 认证，登录后启动行情监控
- **合约管理**：添加/删除合约，配置价格上下限、涨跌幅阈值
- **邮件推送**：SMTP 发送，SSL/TLS 自动回退，支持多收件人
- **定时推送**：预设间隔或自定义秒数，支持仅交易时段过滤
- **实时行情**：WebSocket 推送最新价、涨跌幅、成交量、持仓量
- **预警触发**：价格/涨跌幅超阈值时邮件附带预警明细
- **运行日志**：实时终端日志，支持清空
- **配置持久化**：SQLite 存储，支持 JSON 导入导出

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + uvicorn |
| 前端 | Vue 3 + Element Plus（CDN，免构建） |
| 数据库 | SQLite（Python 标准库） |
| 实时推送 | FastAPI WebSocket |
| 行情 SDK | TqSdk（后台 daemon 线程） |
| 邮件 | smtplib（标准库） |

## 安装

```bash
# 1. 创建并激活虚拟环境（如已有 .venv 可跳过）
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt
```

## 启动

```bash
# 默认监听 0.0.0.0:5000
python run.py

# 自定义端口
python run.py --port 8080

# 开发模式（热重载）
python run.py --reload

# 仅本机访问
python run.py --host 127.0.0.1 --port 5000
```

启动后浏览器访问 `http://localhost:5000`（或对应端口）。

## 使用流程

1. **配置设置** → 填写快期账户用户名和密码
2. **配置设置** → 添加期货合约（如 `SHFE.au2508`），设置预警阈值
3. **配置设置** → 填写 SMTP 邮件配置（服务器、端口、发件人、授权码、收件人）
4. **配置设置** → 设置推送间隔和交易时段
5. 点击顶部 **启动服务** 按钮
6. 切换到 **行情监控** 标签查看实时数据
7. 切换到 **运行日志** 标签查看运行状态

## 项目结构

```
Tqsdk_Email_Web/
├── app/                    # 后端
│   ├── __init__.py
│   ├── main.py             # FastAPI 应用入口、WebSocket、生命周期
│   ├── models.py           # Pydantic 数据模型
│   ├── database.py         # SQLite 配置持久化
│   ├── tracker.py          # TqSdk 监控服务 + 应用状态管理
│   ├── emailer.py          # SMTP 邮件发送
│   ├── routes.py           # REST API 路由
│   └── ws_manager.py       # WebSocket 连接管理（线程安全桥接）
├── static/                 # 前端（免构建）
│   ├── index.html          # 主页面
│   ├── css/style.css       # 暗色交易终端主题
│   └── js/app.js           # Vue 3 应用逻辑
├── data/                   # 运行时自动创建
│   └── config.db           # SQLite 数据库
├── run.py                  # 启动脚本
├── requirements.txt        # 依赖清单
├── config.json             # 配置样例（可参考或手动导入）
└── README.md
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 服务状态 + 当前行情快照 |
| POST | `/api/start` | 启动监控服务（需先配置快期账户和合约） |
| POST | `/api/stop` | 停止监控服务 |
| GET/PUT | `/api/auth` | 获取/设置快期账户 |
| GET/POST/DELETE | `/api/contracts` | 合约增删查 |
| GET/PUT | `/api/email` | 邮件配置 |
| GET/PUT | `/api/schedule` | 时间配置 |
| POST | `/api/save_config` | 导出配置到 JSON |
| POST | `/api/load_config` | 从 JSON 导入配置 |
| GET/DELETE | `/api/logs` | 获取/清空日志 |
| WS | `/ws` | WebSocket 实时推送（行情/日志/状态） |

## WebSocket 事件

| 事件 | 数据 | 说明 |
|------|------|------|
| `price_update` | 单合约行情快照 | 价格变化时推送 |
| `price_update_all` | 全部合约快照 | 连接时推送当前状态 |
| `log_update` | `{line, level}` | 新日志行 |
| `status_change` | `{running, message}` | 服务状态变化 |
| `alert` | `{symbol, alerts}` | 预警触发 |

## 部署（云服务器）

```bash
# 克隆项目到服务器
git clone <repo> && cd Tqsdk_Email_Web

# 安装依赖
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 使用 nohup 后台运行
nohup python run.py --host 0.0.0.0 --port 5000 &

# 或使用 systemd 服务（推荐生产环境）
# 创建 /etc/systemd/system/tqweb.service
```

systemd 服务示例：

```ini
[Unit]
Description=TqSdk Futures Price Monitor Web
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/Tqsdk_Email_Web
ExecStart=/path/to/.venv/bin/python run.py --host 0.0.0.0 --port 5000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tqweb
sudo systemctl start tqweb
```

## 注意事项

1. **TqSdk 主循环**：行情监控在独立 daemon 线程中运行 `wait_update()`，不阻塞 Web 服务
2. **邮件发送**：在独立线程池中执行，不影响行情接收
3. **配置热更新**：邮件配置和时间配置支持运行时修改（3 秒内生效），合约新增支持动态订阅
4. **合约代码格式**：必须为 `交易所.代码` 格式，如 `SHFE.au2508`、`DCE.m2509`
5. **免费版行情**：TqSdk 免费账户提供 15 分钟延时行情，专业版支持实时数据
6. **涨跌颜色**：遵循中国股市惯例，红色涨、绿色跌
7. **密码存储**：快期密码和邮箱授权码在 SQLite 中做混淆存储（非强加密），请保护数据库文件访问权限

## 配置导入导出

- 点击顶部 **保存配置** 按钮，将当前所有设置导出为 `data/config_export.json`
- 点击 **加载配置** 按钮，从该文件恢复配置
- 也可手动编辑 `config.json` 样例文件后通过 API 导入：
  ```bash
  curl -X POST http://localhost:5000/api/load_config \
    -H "Content-Type: application/json" \
    -d '{"path": "config.json"}'
  ```

## 依赖清单

```
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
tqsdk>=3.7.0
python-multipart>=0.0.9
```

其余（sqlite3、smtplib、threading、asyncio、json、logging）均为 Python 标准库。

## 许可证

本项目采用 [MIT 许可证](LICENSE) 开源。

### 依赖声明

本项目使用了以下开源项目，特此感谢：

| 项目 | 许可证 | 说明 |
|------|--------|------|
| [TqSdk](https://github.com/shinnytech/tqsdk-python) | Apache 2.0 | 天勤量化交易 SDK |
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT | 高性能 Python Web 框架 |
| [Vue.js](https://github.com/vuejs/vue) | MIT | 渐进式 JavaScript 框架 |
| [Element Plus](https://github.com/element-plus/element-plus) | MIT | Vue 3 组件库 |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | ASGI Web 服务器 |

## 免责声明

**本项目仅供个人学习和研究使用。**

1. 期货交易涉及高风险，本软件提供的价格监控和邮件提醒功能**不构成投资建议**
2. 使用者需自行承担使用本软件所产生的一切风险和后果
3. 本软件不保证行情数据的准确性、完整性或及时性
4. 本软件不承担因使用本软件而导致的任何直接或间接损失
5. 请遵守当地法律法规，合规使用本软件

**数据安全提醒：**
- 快期密码和邮箱授权码在本地 SQLite 中做混淆存储（非强加密）
- 请保护数据库文件（`data/config.db`）的访问权限
- 切勿将包含真实凭证的配置文件上传到公开仓库

