import time
import json
import psycopg2
from flask import Flask, request
from psycopg2 import OperationalError

from config import DB_URI, YOOKASSA_SECRET_KEY
from models import Database


def wait_for_db(db_uri, max_retries=30, delay=2):
    """Ждем пока база данных станет доступной"""
    for i in range(max_retries):
        try:
            conn = psycopg2.connect(db_uri)
            conn.close()
            print("✅ Database is ready!")
            return True
        except OperationalError as e:
            print(f"⏳ Database not ready yet (attempt {i + 1}/{max_retries}): {e}")
            if i < max_retries - 1:
                time.sleep(delay)
    return False


# Ожидаем готовности БД перед подключением
if not wait_for_db(DB_URI):
    print("❌ Failed to connect to database after multiple attempts")
    exit(1)

db = Database(DB_URI)
app = Flask(__name__)


@app.route("/yookassa_webhook", methods=["POST"])
def yookassa_webhook():
    try:
        # ЮKassa отправляет JSON
        data = request.get_json()

        if not data:
            return "No data", 400

        event = data.get("event")
        if event != "payment.succeeded":
            return "Ignored", 200

        payment_data = data.get("object", {})
        payment_id = payment_data.get("id")
        status = payment_data.get("status")
        metadata = payment_data.get("metadata", {})

        auction_id = metadata.get("auction_id")
        user_id = metadata.get("user_id")
        order_id = metadata.get("order_id")

        if not all([auction_id, user_id, order_id]):
            return "Missing metadata", 400

        # Проверяем подпись (опционально, но рекомендуется)
        # ЮKassa отправляет заголовок с подписью

        if status == "succeeded":
            # Помечаем платеж успешным
            db.update_payment_status(int(auction_id), int(user_id), "completed")
            print(f"Payment {payment_id} for auction {auction_id}, user {user_id} marked as completed")

        return "OK", 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return "Error", 500


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)