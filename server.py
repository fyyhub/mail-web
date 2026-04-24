"""
ChatTempMail 邮件查询服务
封装 https://chat-tempmail.com API，提供带密码保护的 Web 界面。

环境变量：
  TEMPMAIL_API_KEY  - chat-tempmail.com API 密钥（必填）
  ACCESS_PASSWORD   - 访问密码（必填）
  PORT              - 服务端口（默认 8899）
"""

import os
import sys
import secrets
import functools

import requests as http_requests
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

# ─── 配置 ───────────────────────────────────────────────────────────────────────
TEMPMAIL_API_KEY = os.getenv("TEMPMAIL_API_KEY", "")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "")
PORT = int(os.getenv("PORT", "8899"))
TEMPMAIL_BASE = "https://chat-tempmail.com"

if not TEMPMAIL_API_KEY:
    print("[错误] 请设置环境变量 TEMPMAIL_API_KEY")
    sys.exit(1)
if not ACCESS_PASSWORD:
    print("[错误] 请设置环境变量 ACCESS_PASSWORD")
    sys.exit(1)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)


# ─── 通用请求头 ──────────────────────────────────────────────────────────────────
def _headers():
    return {
        "X-API-Key": TEMPMAIL_API_KEY,
        "Content-Type": "application/json",
    }


def _proxy_get(path, params=None):
    """GET 代理到 chat-tempmail.com"""
    resp = http_requests.get(
        f"{TEMPMAIL_BASE}{path}",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    return resp.json(), resp.status_code


def _proxy_post(path, json_data=None):
    """POST 代理到 chat-tempmail.com"""
    resp = http_requests.post(
        f"{TEMPMAIL_BASE}{path}",
        headers=_headers(),
        json=json_data,
        timeout=30,
    )
    return resp.json(), resp.status_code


def _proxy_delete(path):
    """DELETE 代理到 chat-tempmail.com"""
    resp = http_requests.delete(
        f"{TEMPMAIL_BASE}{path}",
        headers=_headers(),
        timeout=30,
    )
    return resp.json(), resp.status_code


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

    return {"error": "未找到该邮箱，请确认它属于当前 API Key 对应的账户"}, 404


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
