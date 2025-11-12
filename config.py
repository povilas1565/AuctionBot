import os

# Telegram bot settings
API_TOKEN = os.getenv("API_TOKEN", "your_telegram_bot_token")

# Database settings (PostgreSQL)
DB_URI = os.getenv("DB_URI", "postgres://postgres:root@localhost/auction_db")

# Redis settings (для кеширования)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)

# Google Sheets API settings
GOOGLE_SHEET_CREDENTIALS = os.getenv("GOOGLE_SHEET_CREDENTIALS", "path_to_google_sheets_credentials.json")

# Freekassa payment system settings
FREEKASSA_SECRET = os.getenv("FREEKASSA_SECRET", "your_freekassa_secret_key")
FREEKASSA_MERCHANT_ID = os.getenv("FREEKASSA_MERCHANT_ID", "your_freekassa_merchant_id")
FREEKASSA_URL = os.getenv("FREEKASSA_URL", "https://www.freekassa.ru/")

# Logging settings
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO")

# Webhook settings (if applicable)
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://yourdomain.com")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/freekassa_webhook")
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# Deployment settings
DEPLOYMENT_ENV = os.getenv("DEPLOYMENT_ENV", "production")
