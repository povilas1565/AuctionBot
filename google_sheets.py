import datetime
from typing import List, Dict

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

from config import (
    GOOGLE_SHEET_CREDENTIALS,
    GOOGLE_SHEET_ID,
    LOTS_SHEET_NAME,
    REPORT_SHEET_NAME,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_service():
    creds = Credentials.from_service_account_file(
        GOOGLE_SHEET_CREDENTIALS,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


def fetch_base_lots() -> List[Dict]:
    service = _get_service()
    sheet = service.spreadsheets()
    range_str = f"{LOTS_SHEET_NAME}!A2:H1000"
    result = sheet.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=range_str,
    ).execute()
    rows = result.get("values", [])

    lots: List[Dict] = []
    for row in rows:
        if len(row) < 8:
            continue
        auction_id = int(row[0])
        name = row[1]
        article = row[2]
        start_price = float(row[3])
        images_raw = row[4] if len(row) > 4 else ""
        video_url = row[5] if len(row) > 5 else ""
        description = row[6] if len(row) > 6 else ""
        start_time_str = row[7]

        images = [url.strip() for url in images_raw.split(",") if url.strip()]
        start_time = datetime.datetime.strptime(start_time_str, "%Y-%m-%d %H:%M")

        lots.append(
            {
                "auction_id": auction_id,
                "name": name,
                "article": article,
                "start_price": start_price,
                "images": images,
                "video_url": video_url or None,
                "description": description,
                "start_time": start_time,
            }
        )
    return lots


def append_report_row(auction_id, name, article, start_price, final_price, status: str):
    service = _get_service()
    sheet = service.spreadsheets()
    values = [[auction_id, name, article, start_price, final_price, status]]
    body = {"values": values}
    range_str = f"{REPORT_SHEET_NAME}!A2"
    sheet.values().append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=range_str,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()
