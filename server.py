"""
ChatTempMail 邮件查询服务
封装 https://chat-tempmail.com 网页端会话，提供带密码保护的 Web 界面。
不再使用 API Key（容易 429），改为通过网页端账号密码登录获取 session cookie。

环境变量：
  TEMPMAIL_USERNAME - chat-tempmail.com 登录用户名（必填）
  TEMPMAIL_PASSWORD - chat-tempmail.com 登录密码（必填）
  ACCESS_PASSWORD   - 本服务访问密码（必填）
  PORT              - 服务端口（默认 8899）
"""

import os
import sys
import time
import secrets
import functools
import threading
import logging

import requests as http_requests
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── 配置 ───────────────────────────────────────────────────────────────────────
TEMPMAIL_USERNAME = os.getenv("TEMPMAIL_USERNAME", "")
TEMPMAIL_PASSWORD = os.getenv("TEMPMAIL_PASSWORD", "")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "")
PORT = int(os.getenv("PORT", "8899"))
TEMPMAIL_BASE = "https://chat-tempmail.com"

if not TEMPMAIL_USERNAME:
    print("[错误] 请设置环境变量 TEMPMAIL_USERNAME")
    sys.exit(1)
if not TEMPMAIL_PASSWORD:
    print("[错误] 请设置环境变量 TEMPMAIL_PASSWORD")
    sys.exit(1)
if not ACCESS_PASSWORD:
    print("[错误] 请设置环境变量 ACCESS_PASSWORD")
    sys.exit(1)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)


# ─── Web Session 管理 ────────────────────────────────────────────────────────────
class TempMailWebSession:
    """通过 chat-tempmail.com 网页端账号密码登录，维护 session cookie。"""

    SESSION_MAX_AGE = 3500  # 略小于 1 小时，提前刷新

    def __init__(self, username: str, password: str, base_url: str):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self._session = http_requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"{base_url}/zh/login",
            "Origin": base_url,
        })
        self._lock = threading.Lock()
        self._last_login_ts = 0.0
        self._logged_in = False

    def _fetch_csrf_token(self) -> str:
        """获取 NextAuth CSRF token。"""
        resp = self._session.get(f"{self.base_url}/api/auth/csrf", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("csrfToken", "")
        if not token:
            raise RuntimeError(f"无法获取 CSRF token: {data}")
        return token

    def _do_login(self):
        """执行 NextAuth credentials 登录。"""
        csrf = self._fetch_csrf_token()
        payload = {
            "username": self.username,
            "password": self.password,
            "redirect": "false",
            "callbackUrl": f"{self.base_url}/zh",
            "csrfToken": csrf,
            "json": "true",
        }
        resp = self._session.post(
            f"{self.base_url}/api/auth/callback/credentials",
            data=payload,
            timeout=15,
            allow_redirects=False,
        )
        # NextAuth returns 200 with {url} on success, or 401/200 with error
        if resp.status_code in (301, 302):
            # follow the redirect to set session cookie
            self._session.get(resp.headers.get("Location", self.base_url), timeout=15)
        elif resp.status_code == 200:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if body.get("error"):
                raise RuntimeError(f"登录失败: {body['error']}")
            # 获取 session 来验证登录成功
        else:
            raise RuntimeError(f"登录请求失败 HTTP {resp.status_code}: {resp.text[:300]}")

        # 验证 session 是否有效
        check = self._session.get(f"{self.base_url}/api/auth/session", timeout=15)
        check_data = check.json() if check.ok else {}
        if not check_data.get("user"):
            raise RuntimeError(f"登录后 session 无效: {check_data}")

        self._last_login_ts = time.time()
        self._logged_in = True
        log.info("chat-tempmail.com 网页端登录成功 (user=%s)", check_data["user"].get("name", "?"))

    def ensure_session(self):
        """确保 session 有效，过期则重新登录。"""
        with self._lock:
            if self._logged_in and (time.time() - self._last_login_ts < self.SESSION_MAX_AGE):
                return
            log.info("正在登录 chat-tempmail.com 网页端...")
            self._do_login()

    def _ensure_and_retry(self, method: str, path: str, **kwargs):
        """发送请求，遇到 401 自动重新登录重试一次。"""
        self.ensure_session()
        url = f"{self.base_url}{path}"
        resp = self._session.request(method, url, timeout=30, **kwargs)
        if resp.status_code == 401:
            log.warning("收到 401，尝试重新登录...")
            with self._lock:
                self._logged_in = False
            self.ensure_session()
            resp = self._session.request(method, url, timeout=30, **kwargs)
        return resp

    def get(self, path: str, params=None):
        resp = self._ensure_and_retry("GET", path, params=params)
        return resp.json(), resp.status_code

    def post(self, path: str, json_data=None):
        resp = self._ensure_and_retry("POST", path, json=json_data)
        return resp.json(), resp.status_code

    def delete(self, path: str):
        resp = self._ensure_and_retry("DELETE", path)
        return resp.json(), resp.status_code


web_session = TempMailWebSession(TEMPMAIL_USERNAME, TEMPMAIL_PASSWORD, TEMPMAIL_BASE)


def _proxy_get(path, params=None):
    """GET 代理到 chat-tempmail.com（网页端 session）"""
    return web_session.get(path, params=params)


def _proxy_post(path, json_data=None):
    """POST 代理到 chat-tempmail.com（网页端 session）"""
    return web_session.post(path, json_data=json_data)


def _proxy_delete(path):
    """DELETE 代理到 chat-tempmail.com（网页端 session）"""
    return web_session.delete(path)


def _normalize_email_address(address):
    return (address or "").strip().lower()


def _find_email_by_address(address):
    """根据邮箱地址在当前账号下查找邮箱对象。"""
    normalized = _normalize_email_address(address)
    cursor = None

    while True:
        params = {"cursor": cursor} if cursor else None
        data, status = _proxy_get("/api/emails", params=params)
        if status >= 400:
            return data, status

        for email in data.get("emails", []):
            if _normalize_email_address(email.get("address")) == normalized:
                return email, 200

        cursor = data.get("nextCursor")
        if not cursor:
            break

    return {"error": "未找到该邮箱，请确认它属于当前账户"}, 404


def _get_all_messages(email_id):
    """拉取指定邮箱下的全部邮件（自动翻页）。"""
    cursor = None
    messages = []

    while True:
        params = {"cursor": cursor} if cursor else None
        data, status = _proxy_get(f"/api/emails/{email_id}", params=params)
        if status >= 400:
            return data, status

        messages.extend(data.get("messages", []))

        cursor = data.get("nextCursor")
        if not cursor:
            break

    return {
        "messages": messages,
        "total": len(messages),
    }, 200


# ─── 登录验证 ────────────────────────────────────────────────────────────────────
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "未授权，请先登录"}), 401
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return wrapper


# ─── 页面路由 ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if secrets.compare_digest(password, ACCESS_PASSWORD):
        session["authenticated"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "密码错误"}), 403


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/check")
def auth_check():
    return jsonify({"authenticated": bool(session.get("authenticated"))})


# ─── 邮箱 API 代理 ──────────────────────────────────────────────────────────────
@app.route("/api/domains")
@login_required
def get_domains():
    data, status = _proxy_get("/api/email/domains")
    return jsonify(data), status


@app.route("/api/emails", methods=["GET"])
@login_required
def list_emails():
    cursor = request.args.get("cursor")
    params = {}
    if cursor:
        params["cursor"] = cursor
    data, status = _proxy_get("/api/emails", params=params)
    return jsonify(data), status


@app.route("/api/inbox/messages")
@login_required
def list_messages_by_address():
    address = (request.args.get("address") or "").strip()
    if not address:
        return jsonify({"error": "请先输入邮箱地址"}), 400

    email_data, status = _find_email_by_address(address)
    if status >= 400:
        return jsonify(email_data), status

    message_data, status = _get_all_messages(email_data["id"])
    if status >= 400:
        return jsonify(message_data), status

    return jsonify(
        {
            "emailId": email_data["id"],
            "address": email_data.get("address", address),
            **message_data,
        }
    ), 200


@app.route("/api/emails", methods=["POST"])
@login_required
def create_email():
    body = request.get_json(silent=True) or {}
    data, status = _proxy_post("/api/emails/generate", json_data=body)
    return jsonify(data), status


@app.route("/api/emails/<email_id>", methods=["DELETE"])
@login_required
def delete_email(email_id):
    data, status = _proxy_delete(f"/api/emails/{email_id}")
    return jsonify(data), status


# ─── 邮件 API 代理 ──────────────────────────────────────────────────────────────
@app.route("/api/emails/<email_id>/messages")
@login_required
def list_messages(email_id):
    cursor = request.args.get("cursor")
    params = {}
    if cursor:
        params["cursor"] = cursor
    data, status = _proxy_get(f"/api/emails/{email_id}", params=params)
    return jsonify(data), status


@app.route("/api/emails/<email_id>/messages/<message_id>")
@login_required
def get_message(email_id, message_id):
    data, status = _proxy_get(f"/api/emails/{email_id}/{message_id}")
    return jsonify(data), status


@app.route("/api/emails/<email_id>/messages/<message_id>", methods=["DELETE"])
@login_required
def delete_message(email_id, message_id):
    data, status = _proxy_delete(f"/api/emails/{email_id}/{message_id}")
    return jsonify(data), status


# ─── 启动 ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"ChatTempMail 邮件查询服务启动: http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
