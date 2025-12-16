import uuid
import qrcode
import json
import requests
import logging
from typing import Tuple

from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY

logger = logging.getLogger(__name__)


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
            "return_url": f"https://t.me/cenolover"
        },
        "description": f"Оплата аукциона №{auction_id}. Пользователь: {user_id}",
        "metadata": {
            "auction_id": auction_id,
            "user_id": user_id,
            "order_id": f"{auction_id}_{user_id}"
        }
    }

    try:
        logger.info(f"💳 Создание платежа ЮKassa: аукцион {auction_id}, сумма {amount}₽")

        response = requests.post(
            "https://api.yookassa.ru/v3/payments",
            headers=headers,
            data=json.dumps(payload),
            timeout=10
        )

        if response.status_code == 200:
            payment_data = response.json()
            payment_url = payment_data.get("confirmation", {}).get("confirmation_url", "")
            payment_id = payment_data.get("id", payment_id)

            logger.info(f"✅ Платеж ЮKassa создан: {payment_id}")
            logger.debug(f"🔗 Ссылка на оплату: {payment_url}")

            return payment_url, payment_id
        else:
            logger.error(f"❌ Ошибка API ЮKassa: {response.status_code} - {response.text}")
            # Fallback URL если API не работает
            return f"https://yoomoney.ru/transfer?to={YOOKASSA_SHOP_ID}&sum={amount}&label={auction_id}_{user_id}", payment_id

    except requests.exceptions.Timeout:
        logger.error(f"❌ Таймаут при создании платежа ЮKassa")
        return f"https://yoomoney.ru/transfer?to={YOOKASSA_SHOP_ID}&sum={amount}&label={auction_id}_{user_id}", payment_id
    except Exception as e:
        logger.error(f"❌ Ошибка создания платежа ЮKassa: {e}")
        return f"https://yoomoney.ru/transfer?to={YOOKASSA_SHOP_ID}&sum={amount}&label={auction_id}_{user_id}", payment_id


def generate_qr(payment_url: str) -> str:
    """Генерация QR-кода для оплаты"""
    try:
        logger.info(f"🖼 Генерация QR-кода для ссылки")
        img = qrcode.make(payment_url)
        path = f"qr_{uuid.uuid4().hex[:8]}.png"
        img.save(path)
        logger.info(f"✅ QR-код сохранен: {path}")
        return path
    except Exception as e:
        logger.error(f"❌ Ошибка генерации QR-кода: {e}")
        # Возвращаем дефолтный путь
        return f"qr_error.png"


def check_payment_status(payment_id: str) -> str:
    """Проверка статуса платежа в ЮKassa"""
    headers = {
        "Authorization": f"Bearer {YOOKASSA_SECRET_KEY}",
    }

    try:
        response = requests.get(
            f"https://api.yookassa.ru/v3/payments/{payment_id}",
            headers=headers,
            timeout=5
        )

        if response.status_code == 200:
            payment_data = response.json()
            status = payment_data.get("status", "pending")
            logger.debug(f"🔍 Статус платежа {payment_id}: {status}")
            return status
        else:
            logger.warning(f"⚠️ Не удалось проверить статус платежа {payment_id}: {response.status_code}")
            return "pending"
    except requests.exceptions.Timeout:
        logger.warning(f"⚠️ Таймаут при проверке статуса платежа {payment_id}")
        return "pending"
    except Exception as e:
        logger.error(f"❌ Ошибка проверки статуса платежа {payment_id}: {e}")
        return "pending"