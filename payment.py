import qrcode
from io import BytesIO


# Функция для генерации URL для платежа через Freekassa
def generate_payment_url(auction_id, amount):
    # Здесь будет формироваться ссылка для Freekassa
    # Это просто пример, измените под свою логику.
    return f"https://www.freekassa.ru/merchant/redirect?merchant_id=your_merchant_id&amount={amount}&auction_id={auction_id}"


# Функция для генерации QR-кода
def generate_qr(payment_url):
    img = qrcode.make(payment_url)
    qr_image_path = f"qr_code.png"
    img.save(qr_image_path)
    return qr_image_path
