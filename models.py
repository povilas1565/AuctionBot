import psycopg2
import datetime


class Database:
    def __init__(self, db_uri):
        self.db_uri = db_uri
        self.connection = psycopg2.connect(self.db_uri)
        self.cursor = self.connection.cursor()

    def execute_query(self, query, params=None):
        if params:
            self.cursor.execute(query, params)
        else:
            self.cursor.execute(query)
        self.connection.commit()

    def fetchone(self, query, params=None):
        if params:
            self.cursor.execute(query, params)
        else:
            self.cursor.execute(query)
        return self.cursor.fetchone()

    def fetchall(self, query, params=None):
        if params:
            self.cursor.execute(query, params)
        else:
            self.cursor.execute(query)
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()
        self.connection.close()

    # Создание нового лота
    def create_lot(self, auction_id, name, article, start_price, images, video_url, description, start_time):
        query = """INSERT INTO lots (auction_id, name, article, start_price, images, video_url, description, start_time, status) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')"""
        self.execute_query(query, (auction_id, name, article, start_price, images, video_url, description, start_time))

    # Получение лотов, которые нужно запустить
    def get_lots_to_start(self):
        current_time = datetime.datetime.now()
        query = """SELECT * FROM lots WHERE start_time <= %s AND status = 'pending'"""
        return self.fetchall(query, (current_time,))

    # Обновление статуса лота
    def update_lot_status(self, auction_id, status):
        query = """UPDATE lots SET status = %s WHERE auction_id = %s"""
        self.execute_query(query, (status, auction_id))

    # Получение ставок по лоту
    def get_bids(self, auction_id):
        query = """SELECT * FROM bids WHERE auction_id = %s ORDER BY amount DESC"""
        return self.fetchall(query, (auction_id,))

    # Добавление ставки
    def add_bid(self, auction_id, user_id, amount):
        query = """INSERT INTO bids (auction_id, user_id, amount) VALUES (%s, %s, %s)"""
        self.execute_query(query, (auction_id, user_id, amount))

    # Обновление платежа
    def update_payment_status(self, auction_id, user_id, status):
        query = """UPDATE payments SET payment_status = %s WHERE auction_id = %s AND user_id = %s"""
        self.execute_query(query, (status, auction_id, user_id))
