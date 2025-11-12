import asyncio
import datetime
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from models import Database
from config import API_TOKEN, DB_URI
from payment import generate_qr, generate_payment_url
from google_sheets import update_google_sheet
from start_auction import start_auction

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и базы данных
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
db = Database(DB_URI)
scheduler = AsyncIOScheduler()


# Команда /start с меню
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name

    # Добавление пользователя в базу
    db.execute_query("INSERT INTO users (user_id, user_name) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING",
                     (user_id, user_name))

    # Создание кнопок меню
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("Участвовать в аукционе", callback_data="join_auction"),
        InlineKeyboardButton("Посмотреть аукционы", callback_data="view_auctions"),
    )
    await message.answer(f"Привет, {user_name}! Я бот для проведения аукционов. Выберите действие:",
                         reply_markup=keyboard)


# Обработчик кнопки "Участвовать в аукционе"
@dp.callback_query_handler(lambda c: c.data == 'join_auction')
async def join_auction(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    auction_id = 1  # Пример, будет динамическим

    # Добавление в аукцион
    db.execute_query(
        "INSERT INTO bids (auction_id, user_id, amount) VALUES (%s, %s, 0) ON CONFLICT (auction_id, user_id) DO NOTHING",
        (auction_id, user_id))

    # Ответ пользователю
    await bot.send_message(user_id, "Вы успешно зарегистрировались на аукцион! Следите за обновлениями.")


# Обработчик кнопки "Посмотреть аукционы"
@dp.callback_query_handler(lambda c: c.data == 'view_auctions')
async def view_auctions(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    # Получаем список доступных аукционов
    auctions = db.fetchall("SELECT auction_id, name FROM lots WHERE status = 'pending'")

    if auctions:
        auction_list = "\n".join([f"{auction[0]}. {auction[1]}" for auction in auctions])
        await bot.send_message(user_id, f"Доступные аукционы:\n{auction_list}")
    else:
        await bot.send_message(user_id, "Нет доступных аукционов.")


# Обработчик ставок
@dp.message_handler(commands=['bid'])
async def bid(message: types.Message):
    user_id = message.from_user.id
    auction_id = 1  # Пример
    bid_amount = float(message.text.split(" ")[1])

    # Проверка минимальной ставки
    max_bid = db.fetchone("SELECT MAX(amount) FROM bids WHERE auction_id = %s", (auction_id,))[0] or 0
    if bid_amount < max_bid + 50:
        await message.reply(f"Ставка должна быть больше {max_bid + 50}₽")
        return

    # Добавление ставки
    db.execute_query("INSERT INTO bids (auction_id, user_id, amount) VALUES (%s, %s, %s)",
                     (auction_id, user_id, bid_amount))
    await message.reply(f"Ваша ставка на аукцион {auction_id} принята: {bid_amount}₽")

    # Уведомление других участников
    await notify_other_participants(auction_id, user_id, bid_amount)


# Уведомление других участников о новой ставке
async def notify_other_participants(auction_id, user_id, bid_amount):
    participants = db.fetchall("SELECT user_id FROM bids WHERE auction_id = %s", (auction_id,))
    for participant in participants:
        if participant[0] != user_id:
            await bot.send_message(participant[0],
                                   f"Новая ставка на аукцион {auction_id}: {user_id} поставил {bid_amount}₽")


# Завершение аукциона и генерация QR-кода для Freekassa
async def end_auction(auction_id: int):
    winner = db.fetchone("SELECT user_id, amount FROM bids WHERE auction_id = %s ORDER BY amount DESC LIMIT 1",
                         (auction_id,))
    if winner:
        user_id, amount = winner
        await bot.send_message(user_id, f"Поздравляем, вы победили! Ваша ставка: {amount}₽")
        payment_url = generate_payment_url(auction_id, amount)
        qr_image = generate_qr(payment_url)
        await bot.send_photo(user_id, photo=open(qr_image, 'rb'))
        update_google_sheet([auction_id, "Item Name", "123", 100, amount, "completed"])
        await start_payment_timer(user_id, auction_id, amount)


# Таймер на оплату
async def start_payment_timer(user_id, auction_id, amount):
    await bot.send_message(user_id,
                           f"У вас есть 15 минут для оплаты. Ссылка для оплаты: {generate_payment_url(auction_id, amount)}")
    await asyncio.sleep(15 * 60)  # 15 минут
    payment = db.fetchone("SELECT * FROM payments WHERE auction_id = %s AND user_id = %s", (auction_id, user_id))
    if not payment or payment[4] == 'failed':
        await bot.send_message(user_id, "Время для оплаты истекло. Аукцион будет пересмотрен.")
        # Повторный выбор победителя


# Проверка новых лотов
async def check_new_lots():
    current_time = datetime.datetime.now()
    lots = db.fetchall("SELECT auction_id FROM lots WHERE start_time <= %s AND status = 'pending'", (current_time,))
    for lot in lots:
        await start_auction(lot[0])


# Публикация лота в канал
async def publish_lot(auction_id: int):
    lot = db.fetchone("SELECT * FROM lots WHERE auction_id = %s", (auction_id,))
    lot_info = f"🎉 Новый аукцион!\n\nТовар: {lot[1]}\nСтартовая цена: {lot[3]}₽"
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Участвовать", callback_data=f"join_auction"))
    await bot.send_message(chat_id="@auction_channel", text=lot_info, reply_markup=keyboard)


scheduler.add_job(check_new_lots, 'interval', minutes=1)

if __name__ == '__main__':
    scheduler.start()
    executor.start_polling(dp, skip_updates=True)
