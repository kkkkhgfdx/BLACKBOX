
import os
import time
from datetime import datetime, timezone
from collections import defaultdict, deque

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------- НАСТРОЙКИ ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

MAX_MESSAGE_LENGTH = 4000
MAX_MESSAGES = 20
DAILY_LIMIT_PER_IP = 20

# Временная защита до появления регистрации и базы данных.
daily_usage = defaultdict(int)
daily_usage_date = datetime.now(timezone.utc).date()
minute_requests = defaultdict(deque)


# ---------- CORS ----------
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/api/chat", methods=["OPTIONS"])
def chat_options():
    return "", 204


# ---------- ПРОВЕРКА СЕРВЕРА ----------
@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "name": "BLACKBOX",
        "status": "online",
        "ai_configured": bool(DEEPSEEK_API_KEY)
    })


# ---------- ЛИМИТЫ ----------
def check_limits(ip):
    global daily_usage_date

    today = datetime.now(timezone.utc).date()

    if today != daily_usage_date:
        daily_usage.clear()
        daily_usage_date = today

    now = time.time()
    requests_for_ip = minute_requests[ip]

    while requests_for_ip and now - requests_for_ip[0] > 60:
        requests_for_ip.popleft()

    if len(requests_for_ip) >= 10:
        return False, "Слишком много запросов. Подожди минуту."

    if daily_usage[ip] >= DAILY_LIMIT_PER_IP:
        return False, "Дневной лимит запросов исчерпан."

    requests_for_ip.append(now)
    return True, None


# ---------- AI ----------
@app.route("/api/chat", methods=["POST"])
def chat():
    if not DEEPSEEK_API_KEY:
        return jsonify({
            "error": "AI пока не подключён. Сервер ожидает ключ DeepSeek."
        }), 503

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Отправь JSON с сообщениями."}), 400

    messages = data.get("messages")

    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "Сообщения не найдены."}), 400

    if len(messages) > MAX_MESSAGES:
        return jsonify({"error": "Слишком длинная история чата."}), 400

    safe_messages = [{
        "role": "system",
        "content": (
            "Ты BLACKBOX AI — полезный, дружелюбный и точный "
            "ИИ-помощник. Отвечай на языке пользователя. "
            "Если не знаешь ответа, честно скажи об этом."
        )
    }]

    for message in messages:
        if not isinstance(message, dict):
            return jsonify({"error": "Неверный формат сообщения."}), 400

        role = message.get("role")
        content = message.get("content")

        if role not in ("user", "assistant"):
            return jsonify({"error": "Недопустимая роль сообщения."}), 400

        if not isinstance(content, str) or not content.strip():
            return jsonify({"error": "Пустое сообщение."}), 400

        if len(content) > MAX_MESSAGE_LENGTH:
            return jsonify({"error": "Сообщение слишком длинное."}), 400

        safe_messages.append({
            "role": role,
            "content": content.strip()
        })

    ip = request.remote_addr or "unknown"
    allowed, error = check_limits(ip)

    if not allowed:
        return jsonify({"error": error}), 429

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": safe_messages,
        "stream": False,
        "max_tokens": 1500,
        "temperature": 0.7
    }

    try:
        response = requests.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )

        if response.status_code != 200:
            return jsonify({
                "error": "AI временно не смог ответить. Попробуй позже."
            }), 502

        result = response.json()
        answer = result["choices"][0]["message"]["content"]

        daily_usage[ip] += 1

        return jsonify({
            "answer": answer,
            "model": DEEPSEEK_MODEL,
            "status": "success"
        })

    except requests.Timeout:
        return jsonify({"error": "AI не ответил вовремя. Попробуй ещё раз."}), 504

    except Exception:
        app.logger.exception("BLACKBOX AI error")
        return jsonify({"error": "Внутренняя ошибка сервера."}), 500


# ---------- ЗАПУСК ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
