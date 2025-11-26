import time

import psycopg2
from flask import Flask, request
import hashlib

from psycopg2 import OperationalError

from config import DB_URI, FREEKASSA_SECRET_2
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


@app.route("/freekassa_webhook", methods=["POST"])
def freekassa_webhook():
    data = request.form.to_dict()
    amount = data.get("AMOUNT") or data.get("AMOUNT", "")
    order_id = data.get("MERCHANT_ORDER_ID") or data.get("MERCHANT_ORDER_ID", "")
    received_sign = data.get("SIGN")

    # order_id = "auctionId_userId"
    try:
        auction_id_str, user_id_str = order_id.split("_")
        auction_id = int(auction_id_str)
        user_id = int(user_id_str)
    except Exception:
        return "bad order id", 400

    sign_str = f"{amount}:{order_id}:{FREEKASSA_SECRET_2}"
    expected_sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    if received_sign != expected_sign:
        return "invalid sign", 400

    # помечаем платеж успешным
    db.update_payment_status(auction_id, user_id, "completed")

    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
