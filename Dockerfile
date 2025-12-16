FROM python:3.11-slim

WORKDIR /app

# зависимости системы
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# копируем всё приложение внутрь контейнера
COPY . .

# Создаем директорию для QR-кодов
RUN mkdir -p /app/qr_codes /app/logs

# Устанавливаем рабочую директорию для QR-кодов
ENV QR_PATH=/app/qr_codes

# Копируем файл с ключами Google (если есть)
RUN if [ -f "cenolover-1-21eedf45d165.json" ]; then \
    echo "✅ Google credentials found"; \
    else \
    echo "⚠️ Google credentials not found"; \
    fi

# По умолчанию запускаем бота
CMD ["python", "bot.py"]