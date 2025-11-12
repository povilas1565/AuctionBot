import os
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# Путь к вашим сервисным учетным данным Google
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SHEET_CREDENTIALS', 'path_to_credentials.json')

# ID вашего Google Sheet
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID', 'your_spreadsheet_id')

# Функция для обновления Google Sheet
def update_google_sheet(auction_data):
    # Подключаемся к Google Sheets API
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])

    service = build("sheets", "v4", credentials=creds)

    sheet = service.spreadsheets()

    # Данные для записи в таблицу
    values = [auction_data]
    body = {
        'values': values
    }

    # Записываем данные в таблицу
    sheet.values().append(spreadsheetId=SPREADSHEET_ID, range="Sheet1!A1", valueInputOption="RAW", body=body).execute()
