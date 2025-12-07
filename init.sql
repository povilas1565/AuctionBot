-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
                                     user_id BIGINT PRIMARY KEY,
                                     user_name TEXT,
                                     warnings INTEGER DEFAULT 0,
                                     banned_until TIMESTAMP,
                                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица лотов
CREATE TABLE IF NOT EXISTS lots (
                                    auction_id INTEGER PRIMARY KEY,
                                    name TEXT NOT NULL,
                                    article TEXT,
                                    start_price DECIMAL(10,2) NOT NULL,
                                    current_price DECIMAL(10,2) NOT NULL,
                                    images TEXT, -- JSON массив URL
                                    video_url TEXT,
                                    description TEXT,
                                    start_time TIMESTAMP NOT NULL,
                                    end_time TIMESTAMP,
                                    status TEXT DEFAULT 'pending', -- pending / active / finished
                                    winner_user_id BIGINT,
                                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица ставок
CREATE TABLE IF NOT EXISTS bids (
                                    id SERIAL PRIMARY KEY,
                                    auction_id INTEGER NOT NULL REFERENCES lots(auction_id) ON DELETE CASCADE,
                                    user_id BIGINT NOT NULL,
                                    amount DECIMAL(10,2) NOT NULL,
                                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                    UNIQUE(auction_id, user_id, amount)
);

-- Таблица платежей (обновлена для ЮКассы)
CREATE TABLE IF NOT EXISTS payments (
                                        id SERIAL PRIMARY KEY,
                                        auction_id INTEGER NOT NULL,
                                        user_id BIGINT NOT NULL,
                                        amount DECIMAL(10,2) NOT NULL,
                                        payment_status TEXT DEFAULT 'pending', -- pending / completed / failed / canceled
                                        payment_id TEXT UNIQUE, -- ID платежа в ЮKassa
                                        payment_url TEXT, -- Ссылка на оплату
                                        description TEXT,
                                        paid_at TIMESTAMP,
                                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индексы для оптимизации
CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
CREATE INDEX IF NOT EXISTS idx_lots_auction_id ON lots(auction_id);
CREATE INDEX IF NOT EXISTS idx_lots_status ON lots(status);
CREATE INDEX IF NOT EXISTS idx_lots_end_time ON lots(end_time);
CREATE INDEX IF NOT EXISTS idx_bids_auction_id ON bids(auction_id);
CREATE INDEX IF NOT EXISTS idx_bids_user_id ON bids(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments(payment_id);
CREATE INDEX IF NOT EXISTS idx_payments_auction_user ON payments(auction_id, user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(payment_status);

-- Таблица для логов (опционально)
CREATE TABLE IF NOT EXISTS bot_logs (
                                        id SERIAL PRIMARY KEY,
                                        level VARCHAR(10),
                                        message TEXT,
                                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                        user_id BIGINT,
                                        auction_id INTEGER
);

-- Функция для автоматического обновления времени
CREATE OR REPLACE FUNCTION update_modified_column()
    RETURNS TRIGGER AS $$
BEGIN
    NEW.created_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Триггеры (опционально)
-- CREATE TRIGGER update_users_modtime BEFORE UPDATE ON users
-- FOR EACH ROW EXECUTE FUNCTION update_modified_column();