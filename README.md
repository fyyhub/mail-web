# ChatTempMail 邮件查询服务

封装 [chat-tempmail.com](https://chat-tempmail.com) 的网页端会话（通过账号密码登录），提供带密码保护的 Web 界面。不再使用 API Key（容易 429）。

当前界面已精简为「输入一个邮箱地址 -> 提取该收件箱全部邮件 -> 查看邮件详情」的单一流程，不再展示邮箱列表或新建邮箱入口。

## 功能

- 🔐 访问密码保护（环境变量配置）
- 📥 输入一个邮箱地址即可提取该收件箱的全部邮件
- 📨 查看邮件列表和详情（HTML / 纯文本 / 原始 JSON 三种视图）
- 🔄 邮件自动刷新（10 秒轮询）
- ♻️ 自动翻页拉取全部邮件，而不只是第一页
- 🛡️ 账号密码仅保存在服务端环境变量中，不暴露到前端

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填入：

```bash
TEMPMAIL_USERNAME=你在 chat-tempmail.com 的登录用户名
TEMPMAIL_PASSWORD=你在 chat-tempmail.com 的登录密码
ACCESS_PASSWORD=你想设置的本服务访问密码
PORT=8899
```

### 3. 启动服务

```bash
python server.py
```

浏览器打开 <http://localhost:8899>，输入密码即可使用。

## 目录结构

```
tempmail_service/
├── server.py              Flask 后端 + API 代理
├── requirements.txt       Python 依赖
├── .env.example           环境变量示例
├── README.md              本文档
├── templates/
│   └── index.html         前端 SPA
└── static/
    └── app.js             前端逻辑
```

## 接口列表

所有接口均需先通过 `POST /api/auth/login` 登录（session cookie）。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth/login` | 登录（body: `{password}`）|
| `POST` | `/api/auth/logout` | 退出登录 |
| `GET`  | `/api/auth/check` | 检查登录状态 |
| `GET`  | `/api/domains` | 获取可用邮箱域名列表 |
| `GET`  | `/api/inbox/messages?address=` | 根据邮箱地址提取该收件箱下全部邮件（前端主流程） |
| `GET`  | `/api/emails?cursor=` | 列出账户下所有邮箱 |
| `POST` | `/api/emails` | 创建邮箱（body: `{name, domain, expiryTime}`）|
| `DELETE` | `/api/emails/{id}` | 删除邮箱 |
| `GET`  | `/api/emails/{id}/messages?cursor=` | 列出邮箱中的邮件 |
| `GET`  | `/api/emails/{id}/messages/{msgId}` | 获取邮件详情 |
| `DELETE` | `/api/emails/{id}/messages/{msgId}` | 删除邮件 |

## 部署建议

- **生产环境** 请使用 Gunicorn / uWSGI 代替 Flask 内置开发服务器：

  ```bash
  pip install gunicorn
  gunicorn -w 2 -b 0.0.0.0:8899 server:app
  ```

- **反向代理** 建议挂在 Nginx 后，并启用 HTTPS。
- **Docker** 可直接基于 `python:3.11-slim` 镜像运行。

## 安全说明

- 网页端账号密码仅保存在服务端环境变量中，不会发送到前端。
- 访问密码对比使用 `secrets.compare_digest` 防止计时攻击。
- 登录后通过 Flask session（签名 cookie）维持会话，每次服务启动会重新生成 secret。
