import asyncio
import datetime

# Функция для старта аукциона
from handlers import end_auction, publish_lot, db


async def start_auction(auction_id):
    # Получаем информацию о лоте по ID
    lot = db.fetchone("SELECT auction_id, name, start_price FROM lots WHERE auction_id = %s", (auction_id,))

    if lot:
        # Обновляем статус лота на 'active'
        db.update_lot_status(auction_id, 'active')

        # Публикуем лот в канал Telegram
        await publish_lot(auction_id)

        # Запуск таймера аукциона (например, на 12 часов)
        end_time = datetime.datetime.now() + datetime.timedelta(hours=12)

        # Это простой пример, вам может потребоваться более сложная логика для обработки таймеров
        while datetime.datetime.now() < end_time:
            await asyncio.sleep(1)

        # Завершаем аукцион и выбираем победителя
        await end_auction(auction_id)
