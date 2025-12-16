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
    "cenolover-1-21eedf45d165.json",
)
GOOGLE_SHEET_ID = os.getenv(
    "GOOGLE_SHEET_ID",
    "1bG2Re3zEmuKQGZPPUQlIBJ5I2p6IHcfz_SfxJVH3c9E",
)
LOTS_SHEET_NAME = os.getenv("LOTS_SHEET_NAME", "LOTS_BASE")
REPORT_SHEET_NAME = os.getenv("REPORT_SHEET_NAME", "REPORT")

# ЮKassa (заменили Freekassa)
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "1209483")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "live_7cEvDkMWWqSDjp-j1qFF44_7815Mnet-E3LbuMiDYT8")
YOOKASSA_BASE_URL = "https://yoomoney.ru/checkout/payments/v2/contract"

# Webhook ЮKassa
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://yourdomain.com")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/yookassa_webhook")
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
    7529623175,
    196831832
]





