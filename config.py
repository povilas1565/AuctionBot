import os

# Telegram bot settings
API_TOKEN = os.getenv("API_TOKEN", "8596942368:AAGTSoOJhWYQsfjjImykiM1vqvDXRvZmNF0")

# Database settings (PostgreSQL)
DB_URI = os.getenv("DB_URI", "postgresql://postgres:root@localhost:5432/auction_db")

# Redis (если решишь использовать)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Google Sheets API settings
GOOGLE_SHEET_CREDENTIALS = os.getenv(
    "GOOGLE_SHEET_CREDENTIALS",
    "celenov-shop-bot-7e2c6e28ecb0.json",
)
GOOGLE_SHEET_ID = os.getenv(
    "GOOGLE_SHEET_ID",
    "1eXreh4wiN6ZDwjK2yVxQFBM8Oq5bTG_B4RXkOgr53a8",
)
LOTS_SHEET_NAME = os.getenv("LOTS_SHEET_NAME", "LOTS_BASE")
REPORT_SHEET_NAME = os.getenv("REPORT_SHEET_NAME", "REPORT")

# Freekassa
FREEKASSA_SECRET_1 = os.getenv("FREEKASSA_SECRET_1", "your_freekassa_secret_key_1")
FREEKASSA_SECRET_2 = os.getenv("FREEKASSA_SECRET_2", "your_freekassa_secret_key_2")
FREEKASSA_MERCHANT_ID = os.getenv("FREEKASSA_MERCHANT_ID", "your_freekassa_merchant_id")
FREEKASSA_BASE_URL = os.getenv("FREEKASSA_URL", "https://pay.freekassa.ru/")

# Webhook Freekassa
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://yourdomain.com")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/freekassa_webhook")
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# Канал аукционов (сюда бот публикует лоты)
AUCTION_CHANNEL = os.getenv("AUCTION_CHANNEL", "@cenolover")  # или -100...

TIMEZONE = "Europe/Moscow"

# --- Параметры аукциона ---
MIN_STEP = 50                 # мин. приращение ставки
AUCTION_DURATION_HOURS = 12   # изначальная длительность
EXTEND_THRESHOLD_MIN = 10     # правило 10 минут
EXTEND_TO_MIN = 10
PAYMENT_TIMEOUT_MIN = 15
MAX_UNPAID_WARNINGS = 3
BAN_DAYS = 30

ADMIN_IDS = [
    7529623175,  # твой id
]








