import sqlite3
from datetime import datetime

class Database:
    def __init__(self, db_path="bot_database.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        """Инициализация таблиц базы данных."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица сообщений (история диалогов)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    role TEXT, -- 'user' или 'assistant'
                    content TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(telegram_id)
                )
            ''')

            # Таблица настроек пользователя
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    model_name TEXT DEFAULT 'gpt-3.5-turbo',
                    temperature REAL DEFAULT 0.7,
                    system_prompt TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(telegram_id)
                )
            ''')
            conn.commit()

    def add_user(self, telegram_id, username, full_name):
        """Добавление нового пользователя или обновление существующего."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (telegram_id, username, full_name)
                VALUES (?, ?, ?)
            ''', (telegram_id, username, full_name))
            # Инициализируем настройки по умолчанию
            cursor.execute('''
                INSERT OR IGNORE INTO user_settings (user_id)
                VALUES (?)
            ''', (telegram_id,))
            conn.commit()

    def get_user_settings(self, user_id):
        """Получение настроек пользователя."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM user_settings WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_user_setting(self, user_id, key, value):
        """Обновление конкретной настройки пользователя."""
        allowed_keys = ['model_name', 'temperature', 'system_prompt']
        if key not in allowed_keys:
            raise ValueError(f"Invalid setting key: {key}")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE user_settings SET {key} = ? WHERE user_id = ?', (value, user_id))
            conn.commit()

    def add_message(self, user_id, role, content):
        """Сохранение сообщения в историю."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (user_id, role, content)
                VALUES (?, ?, ?)
            ''', (user_id, role, content))
            conn.commit()

    def get_history_for_ai(self, user_id, limit=10):
        """Получение истории в формате для нейросети (list of dicts)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT role, content FROM messages
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (user_id, limit))
            rows = cursor.fetchall()[::-1]
            return [{"role": role, "content": content} for role, content in rows]

    def get_history(self, user_id, limit=10):
        """Получение последних N сообщений пользователя."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT role, content FROM messages
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (user_id, limit))
            # Возвращаем в хронологическом порядке (от старых к новым)
            return cursor.fetchall()[::-1]

    def clear_history(self, user_id):
        """Очистка истории сообщений пользователя."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM messages WHERE user_id = ?', (user_id,))
            conn.commit()

if __name__ == "__main__":
    # Тестовая инициализация
    db = Database()
    print("База данных инициализирована.")
