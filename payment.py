import uuid
import qrcode
import base64
import json
import requests
from typing import Dict, Tuple

from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_BASE_URL


def generate_payment_url(auction_id: int, user_id: int, amount: float) -> Tuple[str, str]:
    """
    Создание платежа в ЮKassa и получение ссылки на оплату.
    Возвращает (payment_url, payment_id)
    """
    payment_id = str(uuid.uuid4())

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {YOOKASSA_SECRET_KEY}",
        "Idempotence-Key": payment_id
    }

    payload = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB"
        },
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/cenolover"  # URL для возврата после оплаты
        },
        "description": f"Оплата аукциона №{auction_id}. Пользователь: {user_id}",
        "metadata": {
            "auction_id": auction_id,
            "user_id": user_id,
            "order_id": f"{auction_id}_{user_id}"
        }
    }

    try:
        response = requests.post(
            f"https://api.yookassa.ru/v3/payments",
            headers=headers,
            data=json.dumps(payload)
        )

        if response.status_code == 200:
            payment_data = response.json()
            payment_url = payment_data.get("confirmation", {}).get("confirmation_url", "")
            payment_id = payment_data.get("id", payment_id)
            return payment_url, payment_id
        else:
            # Fallback URL если API не работает
            return f"https://yoomoney.ru/transfer?to={YOOKASSA_SHOP_ID}&sum={amount}&label={auction_id}_{user_id}", payment_id

    except Exception as e:
        # Fallback URL в случае ошибки
        print(f"Error creating YooKassa payment: {e}")
        return f"https://yoomoney.ru/transfer?to={YOOKASSA_SHOP_ID}&sum={amount}&label={auction_id}_{user_id}", payment_id


def generate_qr(payment_url: str) -> str:
    """Генерация QR-кода для оплаты"""
    img = qrcode.make(payment_url)
    path = f"qr_{uuid.uuid4().hex[:8]}.png"
    img.save(path)
    return path


def check_payment_status(payment_id: str) -> str:
    """Проверка статуса платежа в ЮKassa"""
    headers = {
        "Authorization": f"Bearer {YOOKASSA_SECRET_KEY}",
    }

    try:
        response = requests.get(
            f"https://api.yookassa.ru/v3/payments/{payment_id}",
            headers=headers
        )

        if response.status_code == 200:
            payment_data = response.json()
            return payment_data.get("status", "pending")
    except Exception as e:
        print(f"Error checking payment status: {e}")

    return "pending"

