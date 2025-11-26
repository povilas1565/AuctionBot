import psycopg2
from psycopg2.extras import register_default_json
import datetime


class Database:
    def __init__(self, db_uri: str):
        self.db_uri = db_uri
        self.connection = psycopg2.connect(self.db_uri)
        self.cursor = self.connection.cursor()
        # регистрируем json, если где-то будем его использовать
        register_default_json(loads=lambda x: x)

    def execute(self, query, params=None):
        self.cursor.execute(query, params or ())
        self.connection.commit()

    def fetchone(self, query, params=None):
        self.cursor.execute(query, params or ())
        return self.cursor.fetchone()

    def fetchall(self, query, params=None):
        self.cursor.execute(query, params or ())
        return self.cursor.fetchall()

    # --- Users ---

    def upsert_user(self, user_id: int, user_name: str):
        q = """
        INSERT INTO users (user_id, user_name)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET user_name = EXCLUDED.user_name
        """
        self.execute(q, (user_id, user_name))

    def get_user(self, user_id: int):
        q = "SELECT user_id, warnings, banned_until FROM users WHERE user_id = %s"
        return self.fetchone(q, (user_id,))

    def add_warning_auto_ban(self, user_id: int, ban_days: int):
        """Используется при неоплате — увеличивает warnings и при >=3 ставит бан."""
        user = self.get_user(user_id)
        if user is None:
            return
        _, warnings, _ = user
        warnings = (warnings or 0) + 1
        banned_until = None
        if warnings >= 3:
            banned_until = datetime.datetime.now() + datetime.timedelta(days=ban_days)
        q = "UPDATE users SET warnings = %s, banned_until = %s WHERE user_id = %s"
        self.execute(q, (warnings, banned_until, user_id))

    # Админские методы:

    def set_ban(self, user_id: int, until: datetime.datetime | None):
        q = "UPDATE users SET banned_until = %s WHERE user_id = %s"
        self.execute(q, (until, user_id))

    def increment_warning(self, user_id: int):
        user = self.get_user(user_id)
        if user is None:
            return
        _, warnings, _ = user
        warnings = (warnings or 0) + 1
        q = "UPDATE users SET warnings = %s WHERE user_id = %s"
        self.execute(q, (warnings, user_id))

    # --- Lots ---

    def lot_exists(self, auction_id: int) -> bool:
        q = "SELECT 1 FROM lots WHERE auction_id = %s"
        return self.fetchone(q, (auction_id,)) is not None

    def create_lot(self, auction_id, name, article, start_price, images, video_url, description, start_time):
        q = """
        INSERT INTO lots (auction_id, name, article, start_price, current_price,
                          images, video_url, description, start_time, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        """
        self.execute(
            q,
            (
                auction_id,
                name,
                article,
                start_price,
                start_price,
                images,
                video_url,
                description,
                start_time,
            ),
        )

    def get_lots_to_start(self):
        now = datetime.datetime.now()
        q = "SELECT auction_id FROM lots WHERE start_time <= %s AND status = 'pending'"
        return self.fetchall(q, (now,))

    def set_lot_status(self, auction_id: int, status: str):
        q = "UPDATE lots SET status = %s WHERE auction_id = %s"
        self.execute(q, (status, auction_id))

    def set_lot_end_time(self, auction_id: int, end_time: datetime.datetime):
        q = "UPDATE lots SET end_time = %s WHERE auction_id = %s"
        self.execute(q, (end_time, auction_id))

    def get_lot(self, auction_id: int):
        q = """
        SELECT auction_id, name, article, start_price, current_price,
               images, video_url, description, start_time, end_time, status, winner_user_id
        FROM lots WHERE auction_id = %s
        """
        return self.fetchone(q, (auction_id,))

    def update_current_price(self, auction_id: int, amount):
        q = "UPDATE lots SET current_price = %s WHERE auction_id = %s"
        self.execute(q, (amount, auction_id))

    def set_winner(self, auction_id: int, user_id: int | None):
        q = "UPDATE lots SET winner_user_id = %s WHERE auction_id = %s"
        self.execute(q, (user_id, auction_id))

    def get_active_or_pending_lots(self):
        q = """
        SELECT auction_id, name, current_price, status
        FROM lots
        WHERE status IN ('pending','active')
        ORDER BY start_time ASC
        """
        return self.fetchall(q)

    def get_finished_lots_to_close(self):
        now = datetime.datetime.now()
        q = """
        SELECT auction_id FROM lots
        WHERE status = 'active' AND end_time IS NOT NULL AND end_time <= %s
        """
        return self.fetchall(q, (now,))

    # --- Bids ---

    def add_bid(self, auction_id: int, user_id: int, amount):
        q = "INSERT INTO bids (auction_id, user_id, amount) VALUES (%s, %s, %s)"
        self.execute(q, (auction_id, user_id, amount))

    def get_bids_desc(self, auction_id: int):
        q = "SELECT user_id, amount FROM bids WHERE auction_id = %s ORDER BY amount DESC"
        return self.fetchall(q, (auction_id,))

    def get_participants(self, auction_id: int):
        q = "SELECT DISTINCT user_id FROM bids WHERE auction_id = %s"
        return self.fetchall(q, (auction_id,))

    # --- Payments ---

    def insert_payment(self, auction_id: int, user_id: int, amount, status: str):
        q = """
        INSERT INTO payments (auction_id, user_id, amount, payment_status)
        VALUES (%s, %s, %s, %s)
        """
        self.execute(q, (auction_id, user_id, amount, status))

    def update_payment_status(self, auction_id: int, user_id: int, status: str):
        q = """
        UPDATE payments
        SET payment_status = %s,
            paid_at = CASE WHEN %s = 'completed' THEN NOW() ELSE paid_at END
        WHERE auction_id = %s AND user_id = %s
        """
        self.execute(q, (status, status, auction_id, user_id))

    def get_latest_payment(self, auction_id: int, user_id: int):
        q = """
        SELECT payment_status FROM payments
        WHERE auction_id = %s AND user_id = %s
        ORDER BY id DESC LIMIT 1
        """
        return self.fetchone(q, (auction_id, user_id))
