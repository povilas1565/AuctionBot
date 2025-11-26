import hashlib

import qrcode

from config import FREEKASSA_MERCHANT_ID, FREEKASSA_SECRET_1, FREEKASSA_BASE_URL


def generate_payment_url(auction_id: int, user_id: int, amount) -> str:
    """
    Формирование ссылки Freekassa.
    Обязательно проверь с актуальной документацией Freekassa.
    """
    amount_str = f"{float(amount):.2f}"
    order_id = f"{auction_id}_{user_id}"

    sign_str = f"{FREEKASSA_MERCHANT_ID}:{amount_str}:{FREEKASSA_SECRET_1}:{order_id}"
    sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    url = (
        f"{FREEKASSA_BASE_URL}?"
        f"m={FREEKASSA_MERCHANT_ID}"
        f"&oa={amount_str}"
        f"&o={order_id}"
        f"&s={sign}"
    )
    return url


def generate_qr(payment_url: str) -> str:
    img = qrcode.make(payment_url)
    path = f"qr_{hashlib.md5(payment_url.encode()).hexdigest()}.png"
    img.save(path)
    return path


