import datetime
import logging
from typing import List, Dict

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import pytz

from config import (
    GOOGLE_SHEET_CREDENTIALS,
    GOOGLE_SHEET_ID,
    LOTS_SHEET_NAME,
    REPORT_SHEET_NAME,
    TIMEZONE,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

logger = logging.getLogger(__name__)


def _get_service():
    """Получение сервиса Google Sheets"""
    try:
        creds = Credentials.from_service_account_file(
            GOOGLE_SHEET_CREDENTIALS,
            scopes=SCOPES,
        )
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        logger.error(f"❌ Ошибка получения сервиса Google Sheets: {e}")
        raise


def fetch_base_lots() -> List[Dict]:
    """Чтение лотов из Google Sheets"""
    try:
        service = _get_service()
        sheet = service.spreadsheets()
        range_str = f"{LOTS_SHEET_NAME}!A2:H1000"

        logger.info(f"📥 Чтение данных из Google Sheets: {range_str}")

        result = sheet.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=range_str,
        ).execute()

        rows = result.get("values", [])
        logger.info(f"📊 Получено {len(rows)} строк из Google Sheets")

        lots: List[Dict] = []
        tz = pytz.timezone(TIMEZONE)

        for idx, row in enumerate(rows, start=2):
            if len(row) < 8:
                logger.warning(f"⚠️ Строка {idx}: недостаточно данных ({len(row)} колонок)")
                continue

            try:
                # Проверяем обязательные поля
                if not row[0] or not row[1] or not row[3] or not row[7]:
                    logger.warning(f"⚠️ Строка {idx}: пропущены обязательные поля")
                    continue

                auction_id = int(row[0])
                name = row[1].strip()
                article = row[2].strip() if len(row) > 2 and row[2] else "Не указан"
                start_price = float(row[3])

                # Изображения (могут быть несколько через запятую)
                images_raw = row[4] if len(row) > 4 and row[4] else ""
                images = [url.strip() for url in images_raw.split(",") if url.strip()]

                video_url = row[5] if len(row) > 5 and row[5] else None
                description = row[6] if len(row) > 6 and row[6] else ""

                # Парсим время старта
                start_time_str = row[7].strip()
                try:
                    # Пробуем разные форматы времени
                    formats = [
                        "%Y-%m-%d %H:%M",
                        "%d.%m.%Y %H:%M",
                        "%Y/%m/%d %H:%M",
                        "%d/%m/%Y %H:%M"
                    ]

                    start_time = None
                    for fmt in formats:
                        try:
                            start_time = datetime.datetime.strptime(start_time_str, fmt)
                            break
                        except ValueError:
                            continue

                    if not start_time:
                        raise ValueError(f"Неизвестный формат времени: {start_time_str}")

                    # Устанавливаем часовой пояс
                    start_time = tz.localize(start_time)

                except ValueError as e:
                    logger.error(f"❌ Строка {idx}: ошибка парсинга времени '{start_time_str}': {e}")
                    continue

                lots.append({
                    "auction_id": auction_id,
                    "name": name,
                    "article": article,
                    "start_price": start_price,
                    "images": images,
                    "video_url": video_url,
                    "description": description,
                    "start_time": start_time,
                })

                logger.debug(f"✅ Строка {idx}: добавлен лот {auction_id} '{name}' на {start_time}")

            except ValueError as e:
                logger.error(f"❌ Строка {idx}: ошибка преобразования типов: {e}")
                continue
            except Exception as e:
                logger.error(f"❌ Строка {idx}: непредвиденная ошибка: {e}")
                continue

        logger.info(f"✅ Успешно обработано {len(lots)} лотов")
        return lots

    except Exception as e:
        logger.error(f"❌ Ошибка чтения Google Sheets: {e}")
        return []


def append_report_row(auction_id, name, article, start_price, final_price, status: str):
    """Добавление строки в отчетный лист"""
    try:
        service = _get_service()
        sheet = service.spreadsheets()

        # Форматируем данные
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if final_price is None:
            final_price_str = "—"
        else:
            final_price_str = f"{final_price:.2f}"

        values = [[
            timestamp,
            auction_id,
            name,
            article,
            f"{start_price:.2f}",
            final_price_str,
            status
        ]]

        body = {"values": values}
        range_str = f"{REPORT_SHEET_NAME}!A2"

        sheet.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=range_str,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()

        logger.info(f"📝 Запись в отчет: аукцион {auction_id}, статус '{status}'")

    except Exception as e:
        logger.error(f"❌ Ошибка записи в отчет Google Sheets: {e}")
        raise