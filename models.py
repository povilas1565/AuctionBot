import psycopg2
import json
import datetime
import logging
from psycopg2.extras import DictCursor

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_uri: str):
        self.db_uri = db_uri
        self.connection = psycopg2.connect(self.db_uri, cursor_factory=DictCursor)
        self.cursor = self.connection.cursor()
        self.init_tables()

    def init_tables(self):
        """Инициализация таблиц если их нет"""
        tables = [
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                user_name TEXT,
                warnings INTEGER DEFAULT 0,
                banned_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS lots (
                auction_id INTEGER PRIMARY KEY,
                name TEXT,
                article TEXT,
                start_price DECIMAL(10,2),
                current_price DECIMAL(10,2),
                images TEXT,
                video_url TEXT,
                description TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                status TEXT DEFAULT 'pending',
                winner_user_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bids (
                id SERIAL PRIMARY KEY,
                auction_id INTEGER REFERENCES lots(auction_id),
                user_id BIGINT,
                amount DECIMAL(10,2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(auction_id, user_id, amount)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                auction_id INTEGER,
                user_id BIGINT,
                amount DECIMAL(10,2),
                payment_status TEXT DEFAULT 'pending',
                payment_id TEXT,
                paid_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lots_auction_id ON lots(auction_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lots_status ON lots(status);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lots_end_time ON lots(end_time);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_bids_auction_id ON bids(auction_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_bids_user_id ON bids(user_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments(payment_id);
            """
        ]

        for table_sql in tables:
            try:
                self.execute(table_sql)
            except Exception as e:
                logger.error(f"❌ Error creating table/index: {e}")

    def execute(self, query, params=None):
        try:
            self.cursor.execute(query, params or ())
            self.connection.commit()
            return self.cursor
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения запроса: {e}")
            self.connection.rollback()
            raise

    def fetchone(self, query, params=None):
        try:
            self.cursor.execute(query, params or ())
            result = self.cursor.fetchone()
            return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Ошибка fetchone: {e}")
            return None

    def fetchall(self, query, params=None):
        try:
            self.cursor.execute(query, params or ())
            results = self.cursor.fetchall()
            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Ошибка fetchall: {e}")
            return []

    # --- Users ---

    def upsert_user(self, user_id: int, user_name: str):
        q = """
        INSERT INTO users (user_id, user_name)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET user_name = EXCLUDED.user_name
        """
        self.execute(q, (user_id, user_name))
        logger.debug(f"👤 User upserted: {user_id}")

    def get_user(self, user_id: int):
        q = "SELECT * FROM users WHERE user_id = %s"
        return self.fetchone(q, (user_id,))

    def add_warning_auto_ban(self, user_id: int, ban_days: int):
        """Используется при неоплате — увеличивает warnings и при >=3 ставит бан."""
        user = self.get_user(user_id)
        if user is None:
            return
        warnings = user.get('warnings', 0) + 1
        banned_until = None
        if warnings >= 3:
            banned_until = datetime.datetime.now() + datetime.timedelta(days=ban_days)
            logger.info(f"🔨 Автобан пользователя {user_id} на {ban_days} дней (warnings={warnings})")
        q = "UPDATE users SET warnings = %s, banned_until = %s WHERE user_id = %s"
        self.execute(q, (warnings, banned_until, user_id))

    def set_ban(self, user_id: int, until: datetime.datetime | None):
        q = "UPDATE users SET banned_until = %s WHERE user_id = %s"
        self.execute(q, (until, user_id))
        logger.info(f"🔨 Set ban for user {user_id}: {until}")

    def increment_warning(self, user_id: int):
        user = self.get_user(user_id)
        if user is None:
            return
        warnings = user.get('warnings', 0) + 1
        q = "UPDATE users SET warnings = %s WHERE user_id = %s"
        self.execute(q, (warnings, user_id))
        logger.info(f"⚠ Warning added for user {user_id} (total: {warnings})")

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
        images_json = json.dumps(images) if isinstance(images, list) else images
        self.execute(
            q,
            (
                auction_id,
                name,
                article,
                start_price,
                start_price,
                images_json,
                video_url,
                description,
                start_time,
            ),
        )
        logger.info(f"📦 Lot created: {auction_id} '{name}'")

    def get_lots_to_start(self):
        now = datetime.datetime.now()
        q = "SELECT auction_id FROM lots WHERE start_time <= %s AND status = 'pending'"
        return self.fetchall(q, (now,))

    def set_lot_status(self, auction_id: int, status: str):
        q = "UPDATE lots SET status = %s WHERE auction_id = %s"
        self.execute(q, (status, auction_id))
        logger.debug(f"📊 Lot {auction_id} status changed to {status}")

    def set_lot_end_time(self, auction_id: int, end_time: datetime.datetime):
        q = "UPDATE lots SET end_time = %s WHERE auction_id = %s"
        self.execute(q, (end_time, auction_id))
        logger.debug(f"⏰ Lot {auction_id} end_time set to {end_time}")

    def get_lot(self, auction_id: int):
        q = """
        SELECT * FROM lots WHERE auction_id = %s
        """
        return self.fetchone(q, (auction_id,))

    def update_current_price(self, auction_id: int, amount):
        q = "UPDATE lots SET current_price = %s WHERE auction_id = %s"
        self.execute(q, (amount, auction_id))
        logger.debug(f"💰 Lot {auction_id} price updated to {amount}")

    def set_winner(self, auction_id: int, user_id: int | None):
        q = "UPDATE lots SET winner_user_id = %s WHERE auction_id = %s"
        self.execute(q, (user_id, auction_id))
        logger.info(f"👑 Winner set for lot {auction_id}: {user_id}")

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
        # Удаляем старую ставку этого пользователя
        q_delete = "DELETE FROM bids WHERE auction_id = %s AND user_id = %s"
        self.execute(q_delete, (auction_id, user_id))

        # Добавляем новую ставку
        q = "INSERT INTO bids (auction_id, user_id, amount) VALUES (%s, %s, %s)"
        self.execute(q, (auction_id, user_id, amount))
        logger.debug(f"💰 Bid added: auction {auction_id}, user {user_id}, amount {amount}")

    def get_bids_desc(self, auction_id: int):
        q = "SELECT user_id, amount FROM bids WHERE auction_id = %s ORDER BY amount DESC"
        return self.fetchall(q, (auction_id,))

    def get_participants(self, auction_id: int):
        q = "SELECT DISTINCT user_id FROM bids WHERE auction_id = %s"
        return self.fetchall(q, (auction_id,))

    # --- Payments ---

    def insert_payment(self, auction_id: int, user_id: int, amount, payment_id: str, status: str = "pending"):
        q = """
        INSERT INTO payments (auction_id, user_id, amount, payment_status, payment_id)
        VALUES (%s, %s, %s, %s, %s)
        """
        self.execute(q, (auction_id, user_id, amount, status, payment_id))
        logger.info(f"💳 Payment created: auction {auction_id}, user {user_id}, amount {amount}, id {payment_id}")

    def update_payment_status(self, auction_id: int, user_id: int, status: str):
        q = """
        UPDATE payments
        SET payment_status = %s,
            paid_at = CASE WHEN %s = 'completed' THEN NOW() ELSE paid_at END
        WHERE auction_id = %s AND user_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """
        self.execute(q, (status, status, auction_id, user_id))
        logger.info(f"💳 Payment status updated: auction {auction_id}, user {user_id}, status {status}")

    def get_latest_payment(self, auction_id: int, user_id: int):
        q = """
        SELECT payment_status FROM payments
        WHERE auction_id = %s AND user_id = %s
        ORDER BY id DESC LIMIT 1
        """
        result = self.fetchone(q, (auction_id, user_id))
        return result.get('payment_status') if result else None