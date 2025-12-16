import asyncio
import datetime
import logging
import time
import json
import pytz

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import psycopg2
from psycopg2 import OperationalError

from config import (
    API_TOKEN,
    DB_URI,
    AUCTION_CHANNEL,
    TIMEZONE,
    MIN_STEP,
    AUCTION_DURATION_HOURS,
    EXTEND_THRESHOLD_MIN,
    EXTEND_TO_MIN,
    PAYMENT_TIMEOUT_MIN,
    BAN_DAYS,
    ADMIN_IDS,
)
from models import Database
from google_sheets import fetch_base_lots, append_report_row
from payment import generate_payment_url, generate_qr, check_payment_status

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('auction_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def wait_for_db(db_uri, max_retries=30, delay=2):
    """Ждем пока база данных станет доступной"""
    for i in range(max_retries):
        try:
            conn = psycopg2.connect(db_uri)
            conn.close()
            logger.info("✅ Database is ready!")
            return True
        except OperationalError as e:
            logger.warning(f"⏳ Database not ready yet (attempt {i + 1}/{max_retries}): {e}")
            if i < max_retries - 1:
                time.sleep(delay)
    return False


# Ожидаем готовности БД перед подключениями
if not wait_for_db(DB_URI):
    logger.error("❌ Failed to connect to database after multiple attempts")
    exit(1)

# Теперь можно инициализировать базу данных
db = Database(DB_URI)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
scheduler = AsyncIOScheduler(timezone=pytz.timezone(TIMEZONE))


# ========== ХЕЛПЕРЫ ==========

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def format_dt(dt: datetime.datetime | None) -> str:
    if not dt:
        return "не задано"
    return dt.strftime("%Y-%m-%d %H:%M")


def format_remaining(end_time: datetime.datetime | None) -> str:
    if not end_time:
        return "—"
    now = datetime.datetime.now(pytz.timezone(TIMEZONE))
    delta = end_time - now
    if delta.total_seconds() <= 0:
        return "завершается"
    minutes = int(delta.total_seconds() // 60)
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours} ч {minutes} мин"


async def sync_lots_from_sheets():
    """Читает базу лотов из Google Sheets и создаёт новые в БД."""
    try:
        logger.info("🔄 Начинаю синхронизацию с Google Sheets...")
        lots = fetch_base_lots()
        logger.info(f"📥 Получено {len(lots)} лотов из Google Sheets")

        for lot in lots:
            auction_id = lot["auction_id"]
            if not db.lot_exists(auction_id):
                db.create_lot(
                    auction_id=auction_id,
                    name=lot["name"],
                    article=lot["article"],
                    start_price=lot["start_price"],
                    images=lot["images"],
                    video_url=lot["video_url"],
                    description=lot["description"],
                    start_time=lot["start_time"],
                )
                logger.info(f"✅ Создан лот {auction_id} из Google Sheets")
            else:
                logger.debug(f"Лот {auction_id} уже существует в БД")

    except Exception as e:
        logger.error(f"❌ Ошибка синхронизации с Google Sheets: {e}")


async def start_auction(auction_id: int):
    """Перевод лота в active, установка end_time и публикация в канал."""
    try:
        logger.info(f"🚀 Запуск аукциона {auction_id}")
        lot = db.get_lot(auction_id)
        if not lot:
            logger.warning(f"❌ Попытка стартовать несуществующий аукцион {auction_id}")
            return

        status = lot.get('status')
        if status == "active":
            logger.info(f"ℹ️ Аукцион {auction_id} уже активен")
            return

        start_time = lot.get('start_time')
        if isinstance(start_time, str):
            start_time = datetime.datetime.fromisoformat(start_time)

        end_time = start_time + datetime.timedelta(hours=AUCTION_DURATION_HOURS)
        db.set_lot_end_time(auction_id, end_time)
        db.set_lot_status(auction_id, "active")

        await publish_lot_to_channel(auction_id, lot)
        logger.info(f"✅ Аукцион {auction_id} успешно запущен и опубликован в канале")

    except Exception as e:
        logger.error(f"❌ Ошибка запуска аукциона {auction_id}: {e}")


async def publish_lot_to_channel(auction_id: int, lot):
    """Публикация карточки лота в канал AUCTION_CHANNEL"""
    try:
        name = lot.get('name', 'Неизвестно')
        article = lot.get('article', 'Не указан')
        start_price = float(lot.get('start_price', 0))
        current_price = float(lot.get('current_price', start_price))
        description = lot.get('description', '')

        end_time = lot.get('end_time')
        if end_time and isinstance(end_time, str):
            end_time = datetime.datetime.fromisoformat(end_time)

        remaining = format_remaining(end_time)

        caption = (
            f"🧾 Аукцион №{auction_id}\n\n"
            f"🛒 Товар: {name}\n"
            f"📋 Артикул: {article}\n"
            f"💰 Стартовая цена: {start_price}₽\n"
            f"💎 Текущее предложение: {current_price}₽\n"
            f"⏳ До окончания: {remaining}\n\n"
            f"📝 Описание: {description}\n\n"
            f"👇 Нажмите кнопку ниже, чтобы участвовать в аукционе"
        )

        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🎯 Участвовать в аукционе", callback_data=f"join:{auction_id}"))

        # Если есть картинки
        images_raw = lot.get('images')
        images = []
        if images_raw:
            try:
                images = json.loads(images_raw) if isinstance(images_raw, str) else images_raw
            except:
                images = [images_raw] if isinstance(images_raw, str) else []

        if images and len(images) > 0:
            main_image = images[0]
            try:
                await bot.send_photo(
                    AUCTION_CHANNEL,
                    photo=main_image,
                    caption=caption,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                logger.info(f"✅ Лот {auction_id} опубликован в канал с фото")
                return
            except Exception as e:
                logger.error(f"❌ Ошибка отправки фото в канал: {e}")

        # Если нет фото или ошибка - отправляем текстом
        await bot.send_message(AUCTION_CHANNEL, caption, reply_markup=kb, parse_mode="HTML")
        logger.info(f"✅ Лот {auction_id} опубликован в канал (текст)")

    except Exception as e:
        logger.error(f"❌ Ошибка публикации лота {auction_id} в канал: {e}")


async def notify_participants_new_bid(auction_id: int, bidder_id: int, amount):
    """Уведомление всех участников о новой ставке"""
    try:
        participants = db.get_participants(auction_id)
        for participant in participants:
            uid = participant.get('user_id')
            if uid == bidder_id:
                continue
            try:
                await bot.send_message(
                    uid,
                    f"🔔 Новая ставка по аукциону №{auction_id}!\n"
                    f"💰 Сумма: {amount}₽\n\n"
                    f"Проверьте свою карточку лота, чтобы сделать ставку!",
                )
            except Exception as e:
                logger.debug(f"Не удалось отправить уведомление пользователю {uid}: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка уведомления участников: {e}")


async def send_personal_lot_card(user_id: int, auction_id: int):
    """Карточка лота в ЛС пользователя"""
    try:
        lot = db.get_lot(auction_id)
        if not lot:
            await bot.send_message(user_id, "Такого аукциона не существует.")
            return

        name = lot.get('name', 'Неизвестно')
        article = lot.get('article', 'Не указан')
        current_price = float(lot.get('current_price', 0))
        description = lot.get('description', '')

        end_time = lot.get('end_time')
        if end_time and isinstance(end_time, str):
            end_time = datetime.datetime.fromisoformat(end_time)

        remaining = format_remaining(end_time)

        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("+50₽", callback_data=f"bidquick:{auction_id}:50"),
            InlineKeyboardButton("+100₽", callback_data=f"bidquick:{auction_id}:100"),
            InlineKeyboardButton("+200₽", callback_data=f"bidquick:{auction_id}:200"),
        )
        kb.add(InlineKeyboardButton("✏️ Ввести свою сумму", callback_data=f"bidcustom:{auction_id}"))

        text = (
            f"💼 Ваш лот №{auction_id}\n\n"
            f"🛒 Товар: {name}\n"
            f"📋 Артикул: {article}\n"
            f"💰 Текущая цена: {current_price}₽\n"
            f"⏳ До окончания: {remaining}\n\n"
            f"📝 Описание: {description}\n\n"
            f"👇 Выберите быстрый шаг или введите свою сумму через /bid."
        )

        # Если есть фото
        images_raw = lot.get('images')
        images = []
        if images_raw:
            try:
                images = json.loads(images_raw) if isinstance(images_raw, str) else images_raw
            except:
                images = [images_raw] if isinstance(images_raw, str) else []

        if images and len(images) > 0:
            main_image = images[0]
            try:
                await bot.send_photo(user_id, photo=main_image, caption=text, reply_markup=kb, parse_mode="HTML")
                return
            except Exception as e:
                logger.error(f"❌ Ошибка отправки фото в ЛС: {e}")

        await bot.send_message(user_id, text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки карточки лота {auction_id}: {e}")
        await bot.send_message(user_id, f"Ошибка загрузки лота №{auction_id}")


async def finish_auction(auction_id: int):
    """Завершение аукциона"""
    try:
        logger.info(f"🏁 Завершение аукциона {auction_id}")
        bids = db.get_bids_desc(auction_id)
        lot = db.get_lot(auction_id)
        if not lot:
            return

        name = lot.get('name')
        article = lot.get('article')
        start_price = float(lot.get('start_price', 0))

        if not bids:
            db.set_lot_status(auction_id, "finished")
            try:
                append_report_row(auction_id, name, article, start_price, None, "Ставок не было")
            except Exception as e:
                logger.error(f"❌ Ошибка записи в отчет: {e}")
            logger.info(f"📝 Аукцион {auction_id} завершен без ставок")
            return

        db.set_lot_status(auction_id, "finished")

        for bid in bids:
            user_id = bid.get('user_id')
            final_price = float(bid.get('amount', 0))

            logger.info(f"👑 Победитель аукциона {auction_id}: пользователь {user_id}, цена {final_price}₽")

            ok = await process_winner_payment_cycle(
                auction_id, user_id, name, article, start_price, final_price
            )
            if ok:
                break

    except Exception as e:
        logger.error(f"❌ Ошибка завершения аукциона {auction_id}: {e}")


async def process_winner_payment_cycle(
        auction_id: int,
        user_id: int,
        name: str,
        article: str,
        start_price: float,
        final_price: float,
) -> bool:
    """Цикл оплаты для победителя с ЮKassa"""
    try:
        db.set_winner(auction_id, user_id)

        # Генерируем платежную ссылку
        payment_url, payment_id = generate_payment_url(auction_id, user_id, final_price)
        db.insert_payment(auction_id, user_id, final_price, payment_id, "pending")

        # Генерируем QR-код
        qr_path = generate_qr(payment_url)

        text = (
            f"🎉 ПОЗДРАВЛЯЕМ! Вы стали победителем аукциона №{auction_id}!\n\n"
            f"🛒 Товар: {name}\n"
            f"💰 Ваша ставка: {final_price}₽\n\n"
            f"⏳ На оплату даётся {PAYMENT_TIMEOUT_MIN} минут.\n\n"
            f"💳 Оплатите по ссылке ниже или отсканируйте QR-код:\n"
            f"🔗 {payment_url}"
        )

        try:
            with open(qr_path, "rb") as f:
                await bot.send_photo(user_id, f, caption=text, parse_mode="HTML")
            logger.info(f"✅ QR-код отправлен победителю {user_id} аукциона {auction_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки QR-кода: {e}")
            await bot.send_message(user_id, text, parse_mode="HTML")

        # Ждем оплаты
        logger.info(f"⏳ Ожидание оплаты от пользователя {user_id} для аукциона {auction_id}")
        for i in range(PAYMENT_TIMEOUT_MIN * 2):  # Проверяем каждые 30 секунд
            await asyncio.sleep(30)

            # Проверяем статус платежа
            status = check_payment_status(payment_id)
            if status == "succeeded":
                db.update_payment_status(auction_id, user_id, "completed")
                try:
                    append_report_row(auction_id, name, article, start_price, final_price, "Оплата совершена")
                except Exception as e:
                    logger.error(f"❌ Ошибка записи в отчет: {e}")
                logger.info(f"✅ Оплата подтверждена для аукциона {auction_id}")
                return True

            logger.debug(f"Проверка оплаты {i+1}/{PAYMENT_TIMEOUT_MIN*2}: статус {status}")

        # Время вышло, не оплатил
        db.add_warning_auto_ban(user_id, BAN_DAYS)
        try:
            await bot.send_message(
                user_id,
                "⏰ Время оплаты истекло. Результат аукциона пересмотрен, вы можете получить предупреждение/бан.",
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки сообщения о таймауте: {e}")

        logger.warning(f"⏰ Таймаут оплаты для пользователя {user_id} (аукцион {auction_id})")
        return False

    except Exception as e:
        logger.error(f"❌ Ошибка в цикле оплаты для аукциона {auction_id}: {e}")
        return False


# ========== HANDLERS ==========

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    try:
        user_id = message.from_user.id
        user_name = message.from_user.full_name
        db.upsert_user(user_id, user_name)

        user = db.get_user(user_id)
        banned_text = ""
        if user and user.get('banned_until'):
            banned_until = user.get('banned_until')
            if isinstance(banned_until, str):
                banned_until = datetime.datetime.fromisoformat(banned_until)
            if banned_until > datetime.datetime.now():
                banned_text = f"\n\n⚠ Вы заблокированы для участия до {format_dt(banned_until)}"

        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("📦 Актуальные аукционы", callback_data="view_auctions"),
            InlineKeyboardButton("💼 Мои аукционы", callback_data="my_auctions"),
        )
        kb.row(
            InlineKeyboardButton("📜 Правила", callback_data="help"),
            InlineKeyboardButton("⚙ Админ-панель", callback_data="admin_menu"),
        )

        await message.answer(
            f"👋 Привет, {user_name}!\n\n"
            f"Это бот-аукцион, где вы можете участвовать в торгах за интересные товары.{banned_text}\n\n"
            f"👇 Выбирай действие:",
            reply_markup=kb,
            parse_mode="HTML"
        )
        logger.info(f"👤 Новый пользователь: {user_id} ({user_name})")

    except Exception as e:
        logger.error(f"❌ Ошибка в /start: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")


@dp.callback_query_handler(lambda c: c.data == "help")
async def cb_help(callback: types.CallbackQuery):
    await callback.message.answer(
        "📋 <b>Правила аукциона:</b>\n\n"
        f"• Минимальный шаг ставки: <b>{MIN_STEP}₽</b>.\n"
        f"• Изначальная длительность аукциона: <b>{AUCTION_DURATION_HOURS} часов</b>.\n"
        f"• Если до конца аукциона < {EXTEND_THRESHOLD_MIN} минут и приходит новая ставка,\n"
        f"  время продлевается до {EXTEND_TO_MIN} минут.\n"
        f"• Победитель получает ссылку и QR для оплаты.\n"
        f"• На оплату даётся {PAYMENT_TIMEOUT_MIN} минут, при неоплате шанс переходит следующему.\n"
        f"• Многократная неоплата ведёт к блокировке.\n\n"
        f"<i>Удачи в торгах! 🍀</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "view_auctions")
async def cb_view_auctions(callback: types.CallbackQuery):
    try:
        rows = db.get_active_or_pending_lots()
        if not rows:
            await callback.message.answer("📭 Сейчас нет активных аукционов.\n\nЗагляните позже!")
            await callback.answer()
            return

        lines = []
        for row in rows:
            status_emoji = "🟢" if row.get('status') == 'active' else "🟡"
            lines.append(f"{status_emoji} №{row.get('auction_id')} — {row.get('name')} — {row.get('current_price')}₽")

        await callback.message.answer(
            "📋 <b>Актуальные аукционы:</b>\n\n" + "\n".join(lines[:10]),
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка просмотра аукционов: {e}")
        await callback.message.answer("Ошибка загрузки аукционов.")
        await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "my_auctions")
async def cb_my_auctions(callback: types.CallbackQuery):
    try:
        user_id = callback.from_user.id
        rows = db.fetchall(
            """
            SELECT DISTINCT b.auction_id, l.start_time, l.status
            FROM bids b
            JOIN lots l ON b.auction_id = l.auction_id
            WHERE b.user_id = %s
            ORDER BY l.start_time DESC
            LIMIT 10
            """,
            (user_id,),
        )

        if not rows:
            await callback.message.answer("📭 Вы ещё не участвовали в аукционах.\n\nВыберите активный аукцион и сделайте свою первую ставку!")
            await callback.answer()
            return

        await callback.message.answer("💼 <b>Ваши аукционы:</b>", parse_mode="HTML")

        sent = set()
        for row in rows:
            auction_id = row.get('auction_id')
            if auction_id not in sent:
                sent.add(auction_id)
                await send_personal_lot_card(user_id, auction_id)
                await asyncio.sleep(0.3)  # Пауза между отправками

        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки моих аукционов: {e}")
        await callback.message.answer("Ошибка загрузки ваших аукционов.")
        await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("join:"))
async def cb_join(callback: types.CallbackQuery):
    try:
        user_id = callback.from_user.id
        user_name = callback.from_user.full_name
        db.upsert_user(user_id, user_name)

        user = db.get_user(user_id)
        if user and user.get('banned_until'):
            banned_until = user.get('banned_until')
            if isinstance(banned_until, str):
                banned_until = datetime.datetime.fromisoformat(banned_until)
            if banned_until > datetime.datetime.now():
                await callback.message.answer("🚫 Вы временно заблокированы для участия в аукционах.")
                await callback.answer()
                return

        _, auction_id_str = callback.data.split(":")
        auction_id = int(auction_id_str)

        await callback.message.answer(
            "✅ Вы были добавлены в личный чат этого аукциона!\n\n"
            "👇 Теперь вы можете делать ставки через кнопки ниже."
        )
        await send_personal_lot_card(user_id, auction_id)

        logger.info(f"👤 Пользователь {user_id} присоединился к аукциону {auction_id}")
        await callback.answer("Вы участвуете в аукционе 🎯")

    except Exception as e:
        logger.error(f"❌ Ошибка присоединения к аукциону: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@dp.callback_query_handler(lambda c: c.data.startswith("bidquick:"))
async def cb_bidquick(callback: types.CallbackQuery):
    try:
        user_id = callback.from_user.id
        _, auction_id_str, delta_str = callback.data.split(":")
        auction_id = int(auction_id_str)
        delta = int(delta_str)

        lot = db.get_lot(auction_id)
        if not lot or lot.get('status') != "active":
            await callback.message.answer("❌ Этот аукцион не активен.")
            await callback.answer()
            return

        current_price = float(lot.get('current_price', 0))
        amount = current_price + delta
        await process_bid(callback.message, user_id, auction_id, amount)
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка быстрой ставки: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@dp.callback_query_handler(lambda c: c.data.startswith("bidcustom:"))
async def cb_bidcustom(callback: types.CallbackQuery):
    try:
        _, auction_id_str = callback.data.split(":")
        auction_id = int(auction_id_str)

        await callback.message.answer(
            f"✏️ <b>Введите вашу ставку для аукциона №{auction_id}</b>\n\n"
            f"Формат команды:\n"
            f"<code>/bid {auction_id} СУММА</code>\n\n"
            f"Например: <code>/bid {auction_id} 1500</code>",
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка кастомной ставки: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@dp.message_handler(commands=["bid"])
async def cmd_bid(message: types.Message):
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.reply(
                "❌ <b>Неверный формат команды!</b>\n\n"
                "Правильный формат:\n"
                "<code>/bid &lt;номер_аукциона&gt; &lt;сумма&gt;</code>\n\n"
                "Пример: <code>/bid 1 1500</code>",
                parse_mode="HTML"
            )
            return

        _, auction_id_str, amount_str = parts
        auction_id = int(auction_id_str)
        amount = float(amount_str)

        user_id = message.from_user.id
        await process_bid(message, user_id, auction_id, amount)
    except ValueError:
        await message.reply(
            "❌ <b>Неверный формат суммы!</b>\n\n"
            "Используйте числа, например: 1500, 1999.99",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка команды /bid: {e}")
        await message.reply("❌ Ошибка обработки ставки.")


async def process_bid(
        message_or_msg: types.Message,
        user_id: int,
        auction_id: int,
        bid_amount: float,
):
    try:
        lot = db.get_lot(auction_id)
        if not lot:
            await message_or_msg.reply("❌ Такого аукциона не существует.")
            return

        status = lot.get('status')
        if status != "active":
            await message_or_msg.reply("❌ Этот аукцион сейчас не активен.")
            return

        current_price = float(lot.get('current_price', 0))
        if bid_amount < current_price + MIN_STEP:
            await message_or_msg.reply(
                f"❌ <b>Минимальная ставка:</b> не менее {current_price + MIN_STEP}₽\n\n"
                f"Текущая цена: {current_price}₽\n"
                f"Минимальный шаг: {MIN_STEP}₽",
                parse_mode="HTML"
            )
            return

        # Проверяем бан пользователя
        user = db.get_user(user_id)
        if user and user.get('banned_until'):
            banned_until = user.get('banned_until')
            if isinstance(banned_until, str):
                banned_until = datetime.datetime.fromisoformat(banned_until)
            if banned_until > datetime.datetime.now():
                await message_or_msg.reply("🚫 Вы заблокированы для участия в аукционах.")
                return

        # Делаем ставку
        db.add_bid(auction_id, user_id, bid_amount)
        db.update_current_price(auction_id, bid_amount)

        logger.info(f"💰 Ставка на аукцион {auction_id}: пользователь {user_id}, сумма {bid_amount}₽")

        # Правило 10 минут
        end_time = lot.get('end_time')
        if end_time:
            if isinstance(end_time, str):
                end_time = datetime.datetime.fromisoformat(end_time)

            now = datetime.datetime.now(pytz.timezone(TIMEZONE))
            remaining = (end_time - now).total_seconds()
            if remaining < EXTEND_THRESHOLD_MIN * 60:
                new_end = now + datetime.timedelta(minutes=EXTEND_TO_MIN)
                db.set_lot_end_time(auction_id, new_end)
                logger.info(f"⏰ Аукцион {auction_id} продлен до {new_end}")

        # Уведомляем других участников
        await notify_participants_new_bid(auction_id, user_id, bid_amount)

        await message_or_msg.reply(
            f"✅ <b>Ваша ставка принята!</b>\n\n"
            f"💰 Сумма: {bid_amount}₽\n"
            f"🎯 Аукцион №{auction_id}\n\n"
            f"👇 Обновленная карточка лота:",
            parse_mode="HTML"
        )

        # Обновляем карточку у пользователя
        await send_personal_lot_card(user_id, auction_id)

    except Exception as e:
        logger.error(f"❌ Ошибка обработки ставки: {e}")
        await message_or_msg.reply("❌ Ошибка обработки ставки.")


# ========== ТЕСТОВЫЕ КОМАНДЫ ==========

@dp.message_handler(commands=["test_publish"])
async def cmd_test_publish(message: types.Message):
    """Тест публикации лота в канал (для разработчика)"""
    try:
        if not is_admin(message.from_user.id):
            await message.reply("🚫 Нет прав")
            return

        parts = message.text.split()
        if len(parts) != 2:
            await message.reply("❌ Формат: <code>/test_publish &lt;auction_id&gt;</code>", parse_mode="HTML")
            return

        auction_id = int(parts[1])
        lot = db.get_lot(auction_id)

        if not lot:
            await message.reply(f"❌ Лот {auction_id} не найден")
            return

        # Тест публикации
        await publish_lot_to_channel(auction_id, lot)
        await message.reply(f"✅ Тестовая публикация лота {auction_id} отправлена в канал")

        # Тест отправки в ЛС
        await send_personal_lot_card(message.from_user.id, auction_id)
        await message.reply(f"✅ Тестовая карточка отправлена в ЛС")

        logger.info(f"🧪 Тест публикации лота {auction_id} выполнен")

    except Exception as e:
        logger.error(f"❌ Ошибка теста публикации: {e}")
        await message.reply(f"❌ Ошибка: {str(e)[:100]}")

@dp.message_handler(commands=["test_bid"])
async def cmd_test_bid(message: types.Message):
    """Тест ставки (для разработчика)"""
    try:
        if not is_admin(message.from_user.id):
            await message.reply("🚫 Нет прав")
            return

        parts = message.text.split()
        if len(parts) != 3:
            await message.reply("❌ Формат: <code>/test_bid &lt;auction_id&gt; &lt;сумма&gt;</code>", parse_mode="HTML")
            return

        auction_id = int(parts[1])
        amount = float(parts[2])

        await process_bid(message, message.from_user.id, auction_id, amount)
        logger.info(f"🧪 Тест ставки на аукцион {auction_id}: {amount}₽")

    except Exception as e:
        logger.error(f"❌ Ошибка теста ставки: {e}")
        await message.reply(f"❌ Ошибка: {str(e)[:100]}")

@dp.message_handler(commands=["test_sync"])
async def cmd_test_sync(message: types.Message):
    """Тест синхронизации (для разработчика)"""
    try:
        if not is_admin(message.from_user.id):
            await message.reply("🚫 Нет прав")
            return

        await message.reply("🔄 Тест синхронизации с Google Sheets...")
        await sync_lots_from_sheets()
        await message.reply("✅ Синхронизация завершена")

        # Показываем что синхронизировалось
        rows = db.get_active_or_pending_lots()
        if rows:
            await message.reply(f"📊 Синхронизировано лотов: {len(rows)}")
        else:
            await message.reply("📭 Нет лотов для синхронизации")

        logger.info("🧪 Тест синхронизации выполнен")

    except Exception as e:
        logger.error(f"❌ Ошибка теста синхронизации: {e}")
        await message.reply(f"❌ Ошибка: {str(e)[:100]}")


# ========== АДМИН-ХЕНДЛЕРЫ ==========

@dp.message_handler(commands=["admin"])
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 У вас нет прав администратора.")
        return

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📦 Список аукционов", callback_data="admin_lots"),
    )
    kb.add(
        InlineKeyboardButton("🚫 Бан / ✅ Разбан", callback_data="admin_ban_menu"),
    )
    kb.add(
        InlineKeyboardButton("🔄 Синхронизация", callback_data="admin_sync"),
    )

    await message.reply("⚙ <b>Админ-панель:</b>", reply_markup=kb, parse_mode="HTML")


@dp.callback_query_handler(lambda c: c.data == "admin_menu")
async def cb_admin_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Нет прав", show_alert=True)
        return

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📦 Список аукционов", callback_data="admin_lots"),
    )
    kb.add(
        InlineKeyboardButton("🚫 Бан / ✅ Разбан", callback_data="admin_ban_menu"),
    )
    kb.add(
        InlineKeyboardButton("🔄 Синхронизация", callback_data="admin_sync"),
    )

    await callback.message.answer("⚙ <b>Админ-панель:</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_lots")
async def cb_admin_lots(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Нет прав", show_alert=True)
        return

    rows = db.get_active_or_pending_lots()
    if not rows:
        await callback.message.answer("📭 Аукционов (pending/active) нет.")
    else:
        await callback.message.answer(f"📊 <b>Всего лотов:</b> {len(rows)}", parse_mode="HTML")
        for row in rows:
            kb = InlineKeyboardMarkup()
            kb.row(
                InlineKeyboardButton("▶️ Старт", callback_data=f"admin_start:{row.get('auction_id')}"),
                InlineKeyboardButton("⏹ Финиш", callback_data=f"admin_finish:{row.get('auction_id')}"),
            )
            status_emoji = "🟢" if row.get('status') == 'active' else "🟡"
            await callback.message.answer(
                f"{status_emoji} <b>№{row.get('auction_id')}</b> — {row.get('name')}\n"
                f"💰 Цена: {row.get('current_price')}₽\n"
                f"📊 Статус: {row.get('status')}",
                reply_markup=kb,
                parse_mode="HTML"
            )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_start:"))
async def cb_admin_start(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Нет прав", show_alert=True)
        return
    _, auction_id_str = callback.data.split(":")
    auction_id = int(auction_id_str)
    await start_auction(auction_id)
    await callback.message.answer(f"✅ Форс-старт аукциона №{auction_id} выполнен.")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_finish:"))
async def cb_admin_finish(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Нет прав", show_alert=True)
        return
    _, auction_id_str = callback.data.split(":")
    auction_id = int(auction_id_str)
    await finish_auction(auction_id)
    await callback.message.answer(f"✅ Аукцион №{auction_id} принудительно завершён.")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_sync")
async def cb_admin_sync(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Нет прав", show_alert=True)
        return

    await callback.message.answer("🔄 Начинаю синхронизацию с Google Sheets...")
    await sync_lots_from_sheets()
    await callback.message.answer("✅ Синхронизация завершена.")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_ban_menu")
async def cb_admin_ban_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Нет прав", show_alert=True)
        return

    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🚫 Бан командой", callback_data="admin_ban_cmd"),
        InlineKeyboardButton("✅ Разбан командой", callback_data="admin_unban_cmd"),
    )
    kb.row(
        InlineKeyboardButton("⚠ Warn командой", callback_data="admin_warn_cmd"),
    )

    await callback.message.answer(
        "🛡 <b>Управление блокировками через команды:</b>\n\n"
        "/ban &lt;user_id&gt; &lt;days&gt;\n"
        "/unban &lt;user_id&gt;\n"
        "/warn &lt;user_id&gt;",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data in ("admin_ban_cmd", "admin_unban_cmd", "admin_warn_cmd"))
async def cb_admin_ban_help(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Нет прав", show_alert=True)
        return

    if callback.data == "admin_ban_cmd":
        text = "🚫 <b>Команда бана:</b> <code>/ban &lt;user_id&gt; &lt;days&gt;</code>"
    elif callback.data == "admin_unban_cmd":
        text = "✅ <b>Команда разбана:</b> <code>/unban &lt;user_id&gt;</code>"
    else:
        text = "⚠ <b>Команда предупреждения:</b> <code>/warn &lt;user_id&gt;</code>"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@dp.message_handler(commands=["ban"])
async def cmd_ban(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 Нет прав.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.reply("❌ Формат: <code>/ban &lt;user_id&gt; &lt;days&gt;</code>", parse_mode="HTML")
            return

        _, user_id_str, days_str = parts
        user_id = int(user_id_str)
        days = int(days_str)

        until = datetime.datetime.now() + datetime.timedelta(days=days)
        db.set_ban(user_id, until)
        await message.reply(f"✅ Пользователь {user_id} забанен до {format_dt(until)}.")
        logger.info(f"🔨 Бан пользователя {user_id} на {days} дней")

    except ValueError:
        await message.reply("❌ Формат: <code>/ban &lt;user_id&gt; &lt;days&gt;</code>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Ошибка бана: {e}")
        await message.reply("❌ Ошибка выполнения команды.")


@dp.message_handler(commands=["unban"])
async def cmd_unban(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 Нет прав.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.reply("❌ Формат: <code>/unban &lt;user_id&gt;</code>", parse_mode="HTML")
            return

        _, user_id_str = parts
        user_id = int(user_id_str)

        db.set_ban(user_id, None)
        await message.reply(f"✅ Бан с пользователя {user_id} снят.")
        logger.info(f"🔓 Разбан пользователя {user_id}")

    except ValueError:
        await message.reply("❌ Формат: <code>/unban &lt;user_id&gt;</code>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Ошибка разбана: {e}")
        await message.reply("❌ Ошибка выполнения команды.")


@dp.message_handler(commands=["warn"])
async def cmd_warn(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 Нет прав.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.reply("❌ Формат: <code>/warn &lt;user_id&gt;</code>", parse_mode="HTML")
            return

        _, user_id_str = parts
        user_id = int(user_id_str)

        db.increment_warning(user_id)
        await message.reply(f"⚠ Пользователю {user_id} добавлено предупреждение.")
        logger.info(f"⚠ Предупреждение пользователю {user_id}")

    except ValueError:
        await message.reply("❌ Формат: <code>/warn &lt;user_id&gt;</code>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Ошибка warn: {e}")
        await message.reply("❌ Ошибка выполнения команды.")


# ========== SCHEDULER ==========

async def job_sync_and_start():
    """Задача для планировщика - автоматический запуск и завершение аукционов"""
    try:
        logger.debug("🔄 Запуск scheduled job...")

        # 1. Синхронизация с Google Sheets
        await sync_lots_from_sheets()

        # 2. Запуск лотов, у которых наступило время старта
        now = datetime.datetime.now(pytz.timezone(TIMEZONE))

        # Получаем лоты, у которых время старта наступило, но статус ещё pending
        pending_lots = db.fetchall("""
            SELECT auction_id, start_time 
            FROM lots 
            WHERE status = 'pending' 
            AND start_time <= %s
            ORDER BY start_time ASC
        """, (now,))

        logger.info(f"⏰ Найдено {len(pending_lots)} лотов для запуска")

        for lot in pending_lots:
            auction_id = lot.get('auction_id')
            start_time = lot.get('start_time')

            # Преобразуем строку в datetime если нужно
            if isinstance(start_time, str):
                start_time = datetime.datetime.fromisoformat(start_time)

            # Проверяем, что время действительно наступило
            if start_time <= now:
                await start_auction(auction_id)
                await asyncio.sleep(1)  # Небольшая пауза между запусками

        # 3. Завершение лотов, у которых истекло время
        to_finish = db.get_finished_lots_to_close()

        if to_finish:
            logger.info(f"🏁 Найдено {len(to_finish)} лотов для завершения")

        for row in to_finish:
            auction_id = row.get('auction_id')
            await finish_auction(auction_id)
            await asyncio.sleep(1)  # Небольшая пауза между завершениями

        logger.debug("✅ Scheduled job выполнен")

    except Exception as e:
        logger.error(f"❌ Ошибка в scheduled job: {e}")


def scheduler_setup():
    scheduler.add_job(job_sync_and_start, "interval", minutes=1)
    scheduler.start()


async def on_startup(dispatcher: Dispatcher):
    """Действия при запуске бота"""
    scheduler_setup()
    logger.info("✅ Scheduler started, bot is up.")

    # Синхронизация при старте
    await sync_lots_from_sheets()

    # Тестовое сообщение админам
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "🤖 <b>Бот аукционов запущен!</b>\n\n"
                f"🕐 Время: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📊 Канал: {AUCTION_CHANNEL}\n"
                f"🔧 Версия: с исправленной автоматической публикацией\n\n"
                f"<i>Используйте /test_publish для проверки</i>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {e}")


if __name__ == "__main__":
    # Проверяем подключение к каналу
    logger.info(f"🚀 Бот запускается...")
    logger.info(f"📢 Канал для публикации: {AUCTION_CHANNEL}")
    logger.info(f"👑 Админы: {ADMIN_IDS}")
    logger.info(f"🌍 Часовой пояс: {TIMEZONE}")

    try:
        executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")