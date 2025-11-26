import asyncio
import datetime
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

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
# db.add_warning_auto_ban, set_ban, increment_warning и т.д. уже есть
from google_sheets import fetch_base_lots, append_report_row
from payment import generate_payment_url, generate_qr

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
db = Database(DB_URI)
scheduler = AsyncIOScheduler(timezone=pytz.timezone(TIMEZONE))


# ========== ХЕЛПЕРЫ ==========

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def sync_lots_from_sheets():
    lots = fetch_base_lots()
    for lot in lots:
        if not db.lot_exists(lot["auction_id"]):
            db.create_lot(
                auction_id=lot["auction_id"],
                name=lot["name"],
                article=lot["article"],
                start_price=lot["start_price"],
                images=lot["images"],
                video_url=lot["video_url"],
                description=lot["description"],
                start_time=lot["start_time"],
            )
            logging.info(f"Создан лот {lot['auction_id']} из Google Sheets")


async def start_auction(auction_id: int):
    lot = db.get_lot(auction_id)
    if not lot:
        return
    if lot[10] == "active":
        return

    start_time = lot[8]
    end_time = start_time + datetime.timedelta(hours=AUCTION_DURATION_HOURS)
    db.set_lot_end_time(auction_id, end_time)
    db.set_lot_status(auction_id, "active")

    await publish_lot_to_channel(auction_id, lot)


async def publish_lot_to_channel(auction_id: int, lot_row):
    (
        auction_id_db,
        name,
        article,
        start_price,
        current_price,
        images,
        video_url,
        description,
        start_time,
        end_time,
        status,
        winner_user_id,
    ) = lot_row

    text = (
        f"🧾 Аукцион №{auction_id}\n\n"
        f"Товар: {name}\n"
        f"Артикул: {article}\n"
        f"Стартовая цена: {start_price}₽\n"
        f"Текущее предложение: {current_price}₽\n"
        f"Описание: {description}\n"
        f"Старт: {start_time}\n"
        f"Окончание (текущее): {end_time}\n"
    )

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Участвовать", callback_data=f"join:{auction_id}"))

    await bot.send_message(AUCTION_CHANNEL, text, reply_markup=kb)


async def notify_participants_new_bid(auction_id: int, bidder_id: int, amount):
    participants = db.get_participants(auction_id)
    for (uid,) in participants:
        if uid == bidder_id:
            continue
        try:
            await bot.send_message(
                uid,
                f"🔔 Новая ставка по аукциону №{auction_id}: {amount}₽",
            )
        except Exception:
            pass


async def send_personal_lot_card(user_id: int, auction_id: int):
    """Карточка лота в ЛС пользователя с кнопками +50/+100/+200 и вводом своей суммы."""
    lot = db.get_lot(auction_id)
    if not lot:
        await bot.send_message(user_id, "Такого аукциона не существует.")
        return

    (
        auction_id_db,
        name,
        article,
        start_price,
        current_price,
        images,
        video_url,
        description,
        start_time,
        end_time,
        status,
        winner_user_id,
    ) = lot

    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("+50₽", callback_data=f"bidquick:{auction_id}:50"),
        InlineKeyboardButton("+100₽", callback_data=f"bidquick:{auction_id}:100"),
        InlineKeyboardButton("+200₽", callback_data=f"bidquick:{auction_id}:200"),
    )
    kb.add(InlineKeyboardButton("Ввести свою сумму", callback_data=f"bidcustom:{auction_id}"))

    text = (
        f"💼 Ваш личный лот №{auction_id}\n"
        f"Товар: {name}\n"
        f"Артикул: {article}\n"
        f"Текущая цена: {current_price}₽\n"
        f"Описание: {description}\n"
        f"Окончание: {end_time}\n\n"
        "Выберите быстрый шаг или введите свою сумму."
    )

    await bot.send_message(user_id, text, reply_markup=kb)


async def finish_auction(auction_id: int):
    bids = db.get_bids_desc(auction_id)
    lot = db.get_lot(auction_id)
    if not lot:
        return

    name = lot[1]
    article = lot[2]
    start_price = float(lot[3])

    if not bids:
        db.set_lot_status(auction_id, "finished")
        append_report_row(auction_id, name, article, start_price, None, "Ставок не было")
        return

    db.set_lot_status(auction_id, "finished")

    for (user_id, final_price) in bids:
        ok = await process_winner_payment_cycle(
            auction_id, user_id, name, article, start_price, final_price
        )
        if ok:
            break


async def process_winner_payment_cycle(
        auction_id: int,
        user_id: int,
        name: str,
        article: str,
        start_price: float,
        final_price: float,
) -> bool:
    db.set_winner(auction_id, user_id)
    db.insert_payment(auction_id, user_id, final_price, "pending")

    payment_url = generate_payment_url(auction_id, user_id, final_price)
    qr_path = generate_qr(payment_url)

    text = (
        f"🎉 Вы стали победителем аукциона №{auction_id}!\n"
        f"Товар: {name}\n"
        f"Ваша ставка: {final_price}₽\n\n"
        f"На оплату даётся {PAYMENT_TIMEOUT_MIN} минут.\n"
        f"Ссылка для оплаты:\n{payment_url}"
    )
    try:
        await bot.send_photo(user_id, open(qr_path, "rb"), caption=text)
    except Exception:
        await bot.send_message(user_id, text)

    await asyncio.sleep(PAYMENT_TIMEOUT_MIN * 60)

    pay = db.get_latest_payment(auction_id, user_id)
    if pay and pay[0] == "completed":
        append_report_row(auction_id, name, article, start_price, final_price, "Оплата совершена")
        return True

    # не оплатил
    db.add_warning_auto_ban(user_id, BAN_DAYS)
    try:
        await bot.send_message(
            user_id,
            "⏰ Время оплаты истекло. Результат аукциона пересмотрен, вы можете получить предупреждение/бан.",
        )
    except Exception:
        pass

    return False


# ========== HANDLERS: ПОЛЬЗОВАТЕЛИ ==========

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    db.upsert_user(user_id, user_name)

    user = db.get_user(user_id)
    banned_text = ""
    if user and user[2]:
        if user[2] > datetime.datetime.now():
            banned_text = f"\n\n⚠ Вы заблокированы для участия до {user[2]}"

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📦 Актуальные аукционы", callback_data="view_auctions"),
        InlineKeyboardButton("💼 Мои аукционы", callback_data="my_auctions"),
    )
    kb.add(
        InlineKeyboardButton("📜 Правила", callback_data="help"),
    )

    # кнопка админки тоже можно добавить (видна всем, но проверка прав в /admin)
    kb.add(
        InlineKeyboardButton("⚙ Админ-панель", callback_data="admin_menu"),
    )

    await message.answer(
        f"Привет, {user_name}! Это бот-аукцион.{banned_text}\nВыбирай действие:",
        reply_markup=kb,
    )


@dp.callback_query_handler(lambda c: c.data == "help")
async def cb_help(callback: types.CallbackQuery):
    await callback.message.answer(
        "Правила аукциона:\n"
        f"- Минимальный шаг ставки: {MIN_STEP}₽.\n"
        "- Если до конца аукциона < 10 минут и приходит новая ставка, время продлевается до 10 минут.\n"
        "- Победитель получает ссылку и QR для оплаты.\n"
        "- На оплату даётся 15 минут, при неоплате шанс переходит следующему по ставке.\n"
        "- Многократная неоплата ведёт к блокировке."
    )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "view_auctions")
async def cb_view_auctions(callback: types.CallbackQuery):
    rows = db.get_active_or_pending_lots()
    if not rows:
        await callback.message.answer("Сейчас нет активных аукционов.")
        await callback.answer()
        return

    text_lines = []
    for auction_id, name, cur_price, status in rows:
        text_lines.append(f"№{auction_id} — {name} — {cur_price}₽ — {status}")
    await callback.message.answer("Актуальные аукционы:\n" + "\n".join(text_lines))
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "my_auctions")
async def cb_my_auctions(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    rows = db.fetchall(
        """
        SELECT b.auction_id, l.start_time
        FROM bids b
        JOIN lots l ON b.auction_id = l.auction_id
        WHERE b.user_id = %s
        GROUP BY b.auction_id, l.start_time
        ORDER BY l.start_time DESC
        """,
        (user_id,),
    )
    if not rows:
        await callback.message.answer("Вы ещё не участвовали в аукционах.")
        await callback.answer()
        return

    await callback.message.answer("Ваши аукционы (карточки будут отправлены отдельными сообщениями):")

    sent = set()
    for auction_id, _ in rows:
        if auction_id in sent:
            continue
        sent.add(auction_id)
        await send_personal_lot_card(user_id, auction_id)

    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("join:"))
async def cb_join(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_name = callback.from_user.full_name
    db.upsert_user(user_id, user_name)

    user = db.get_user(user_id)
    if user and user[2] and user[2] > datetime.datetime.now():
        await callback.message.answer("Вы временно заблокированы для участия в аукционах.")
        await callback.answer()
        return

    _, auction_id_str = callback.data.split(":")
    auction_id = int(auction_id_str)

    await callback.message.answer("Вы были добавлены в личный чат этого аукциона.")
    await send_personal_lot_card(user_id, auction_id)

    await callback.answer("Вы участвуете в аукционе")


@dp.callback_query_handler(lambda c: c.data.startswith("bidquick:"))
async def cb_bidquick(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    _, auction_id_str, delta_str = callback.data.split(":")
    auction_id = int(auction_id_str)
    delta = int(delta_str)

    lot = db.get_lot(auction_id)
    if not lot or lot[10] != "active":
        await callback.message.answer("Этот аукцион не активен.")
        await callback.answer()
        return

    current_price = float(lot[4])
    amount = current_price + delta
    await process_bid(callback.message, user_id, auction_id, amount)
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("bidcustom:"))
async def cb_bidcustom(callback: types.CallbackQuery):
    _, auction_id_str = callback.data.split(":")
    auction_id = int(auction_id_str)

    await callback.message.answer(
        f"Введите вашу ставку для аукциона №{auction_id} в формате:\n"
        f"`/bid {auction_id} СУММА`",
        parse_mode="Markdown",
    )
    await callback.answer()


@dp.message_handler(commands=["bid"])
async def cmd_bid(message: types.Message):
    try:
        _, auction_id_str, amount_str = message.text.split()
        auction_id = int(auction_id_str)
        amount = float(amount_str)
    except ValueError:
        await message.reply("Формат команды: /bid <auction_id> <сумма>")
        return

    user_id = message.from_user.id
    await process_bid(message, user_id, auction_id, amount)


async def process_bid(message_or_msg: types.Message, user_id: int, auction_id: int, bid_amount: float):
    lot = db.get_lot(auction_id)
    if not lot:
        await message_or_msg.reply("Такого аукциона не существует.")
        return

    status = lot[10]
    if status != "active":
        await message_or_msg.reply("Этот аукцион сейчас не активен.")
        return

    current_price = float(lot[4])
    if bid_amount < current_price + MIN_STEP:
        await message_or_msg.reply(f"Минимальная ставка: не менее {current_price + MIN_STEP}₽")
        return

    db.add_bid(auction_id, user_id, bid_amount)
    db.update_current_price(auction_id, bid_amount)

    end_time = lot[9]
    now = datetime.datetime.now()
    if end_time:
        remaining = (end_time - now).total_seconds()
        if remaining < EXTEND_THRESHOLD_MIN * 60:
            new_end = now + datetime.timedelta(minutes=EXTEND_TO_MIN)
            db.set_lot_end_time(auction_id, new_end)

    await notify_participants_new_bid(auction_id, user_id, bid_amount)
    await message_or_msg.reply(f"Ваша ставка {bid_amount}₽ принята для аукциона №{auction_id}.")


# ========== HANDLERS: АДМИНКА ==========

@dp.message_handler(commands=["admin"])
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("У вас нет прав администратора.")
        return

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📦 Список аукционов", callback_data="admin_lots"),
    )
    kb.add(
        InlineKeyboardButton("🚫 Бан / ✅ Разбан", callback_data="admin_ban_menu"),
    )

    await message.reply("Админ-панель:", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "admin_menu")
async def cb_admin_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📦 Список аукционов", callback_data="admin_lots"),
    )
    kb.add(
        InlineKeyboardButton("🚫 Бан / ✅ Разбан", callback_data="admin_ban_menu"),
    )
    await callback.message.answer("Админ-панель:", reply_markup=kb)
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_lots")
async def cb_admin_lots(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    rows = db.get_active_or_pending_lots()
    if not rows:
        await callback.message.answer("Аукционов (pending/active) нет.")
    else:
        for (auction_id, name, cur, status) in rows:
            kb = InlineKeyboardMarkup()
            kb.add(
                InlineKeyboardButton("▶️ Старт", callback_data=f"admin_start:{auction_id}"),
                InlineKeyboardButton("⏹ Финиш", callback_data=f"admin_finish:{auction_id}"),
            )
            await callback.message.answer(
                f"№{auction_id} — {name} — {cur}₽ — {status}",
                reply_markup=kb,
            )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_start:"))
async def cb_admin_start(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    _, auction_id_str = callback.data.split(":")
    auction_id = int(auction_id_str)
    await start_auction(auction_id)
    await callback.message.answer(f"Форс-старт аукциона №{auction_id} выполнен.")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_finish:"))
async def cb_admin_finish(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    _, auction_id_str = callback.data.split(":")
    auction_id = int(auction_id_str)
    await finish_auction(auction_id)
    await callback.message.answer(f"Аукцион №{auction_id} принудительно завершён.")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_ban_menu")
async def cb_admin_ban_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("🚫 Бан командой", callback_data="admin_ban_cmd"),
        InlineKeyboardButton("✅ Разбан командой", callback_data="admin_unban_cmd"),
    )
    kb.add(
        InlineKeyboardButton("⚠ Warn командой", callback_data="admin_warn_cmd"),
    )
    await callback.message.answer(
        "Управление блокировками пока через команды:\n"
        "/ban <user_id> <days>\n/unban <user_id>\n/warn <user_id>",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data in ("admin_ban_cmd", "admin_unban_cmd", "admin_warn_cmd"))
async def cb_admin_ban_help(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    if callback.data == "admin_ban_cmd":
        text = "Команда бана: `/ban <user_id> <days>`"
    elif callback.data == "admin_unban_cmd":
        text = "Команда разбана: `/unban <user_id>`"
    else:
        text = "Команда предупреждения: `/warn <user_id>`"

    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@dp.message_handler(commands=["ban"])
async def cmd_ban(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("Нет прав.")
        return
    try:
        _, user_id_str, days_str = message.text.split()
        user_id = int(user_id_str)
        days = int(days_str)
    except ValueError:
        await message.reply("Формат: /ban <user_id> <days>")
        return

    until = datetime.datetime.now() + datetime.timedelta(days=days)
    db.set_ban(user_id, until)
    await message.reply(f"Пользователь {user_id} забанен до {until}.")


@dp.message_handler(commands=["unban"])
async def cmd_unban(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("Нет прав.")
        return
    try:
        _, user_id_str = message.text.split()
        user_id = int(user_id_str)
    except ValueError:
        await message.reply("Формат: /unban <user_id>")
        return

    db.set_ban(user_id, None)
    await message.reply(f"Бан с пользователя {user_id} снят.")


@dp.message_handler(commands=["warn"])
async def cmd_warn(message: types.Message):
    """Ручное добавление предупреждения админом."""
    if not is_admin(message.from_user.id):
        await message.reply("Нет прав.")
        return
    try:
        _, user_id_str = message.text.split()
        user_id = int(user_id_str)
    except ValueError:
        await message.reply("Формат: /warn <user_id>")
        return

    db.increment_warning(user_id)
    await message.reply(f"Пользователю {user_id} добавлено предупреждение.")


# ========== SCHEDULER ==========

async def job_sync_and_start():
    await sync_lots_from_sheets()

    to_start = db.get_lots_to_start()
    for (auction_id,) in to_start:
        await start_auction(auction_id)

    to_finish = db.get_finished_lots_to_close()
    for (auction_id,) in to_finish:
        await finish_auction(auction_id)


def scheduler_setup():
    # передаём корутину прямо, AsyncIOScheduler сам её исполнит в event loop
    scheduler.add_job(job_sync_and_start, "interval", minutes=1)
    scheduler.start()


async def on_startup(dp: Dispatcher):
    scheduler_setup()


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
