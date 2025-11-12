import hashlib
from flask import Flask, request
from models import Database
from config import FREEKASSA_SECRET, DB_URI

app = Flask(__name__)
db = Database(DB_URI)


@app.route('/freekassa_webhook', methods=['POST'])
def freekassa_webhook():
    data = request.form
    signature = data.get('SIGN', '')
    amount = data.get('AMOUNT', '')
    user_id = data.get('USER_ID', '')
    auction_id = data.get('AUCTION_ID', '')

    # Проверяем подпись для безопасности
    expected_signature = hashlib.md5(f"{user_id}:{amount}:{FREEKASSA_SECRET}".encode('utf-8')).hexdigest()

    if signature != expected_signature:
        return "Invalid signature", 400

    # Если подпись верна, обновляем статус платежа в базе данных
    db.execute_query(
        "INSERT INTO payments (auction_id, user_id, amount, payment_status) VALUES (%s, %s, %s, 'completed')",
        (auction_id, user_id, amount))

    return "OK", 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)
