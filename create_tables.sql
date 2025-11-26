CREATE TABLE IF NOT EXISTS users (
                                     id SERIAL PRIMARY KEY,
                                     user_id BIGINT UNIQUE NOT NULL,
                                     user_name TEXT,
                                     warnings INT DEFAULT 0,
                                     banned_until TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS lots (
                                    id SERIAL PRIMARY KEY,
                                    auction_id INT UNIQUE NOT NULL,
                                    name TEXT NOT NULL,
                                    article TEXT,
                                    start_price NUMERIC NOT NULL,
                                    current_price NUMERIC NOT NULL,
                                    images TEXT[],
                                    video_url TEXT,
                                    description TEXT,
                                    start_time TIMESTAMP NOT NULL,
                                    end_time TIMESTAMP,
                                    status TEXT DEFAULT 'pending', -- pending / active / finished
                                    winner_user_id BIGINT
);

CREATE TABLE IF NOT EXISTS bids (
                                    id SERIAL PRIMARY KEY,
                                    auction_id INT NOT NULL,
                                    user_id BIGINT NOT NULL,
                                    amount NUMERIC NOT NULL,
                                    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
                                        id SERIAL PRIMARY KEY,
                                        auction_id INT NOT NULL,
                                        user_id BIGINT NOT NULL,
                                        amount NUMERIC NOT NULL,
                                        payment_status TEXT DEFAULT 'pending', -- pending / completed / failed
                                        created_at TIMESTAMP DEFAULT NOW(),
                                        paid_at TIMESTAMP NULL
);
