import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

class DatabaseManager:
    def __init__(self, db_name: str = "bot_database.db"):
        self.db_name = db_name
        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """Получение соединения с базой данных"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self) -> None:
        """Инициализация таблиц базы данных"""
        tables = [
            # Таблица пользователей
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                balance INTEGER DEFAULT 0,
                total_requests INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # Таблица платежей
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                stars_paid INTEGER NOT NULL,
                payment_id TEXT UNIQUE,
                status TEXT DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tg_id) REFERENCES users (tg_id)
            )
            """,
            # Таблица промокодов
            """
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                requests INTEGER NOT NULL,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # Таблица использования промокодов
            """
            CREATE TABLE IF NOT EXISTS promo_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_id INTEGER NOT NULL,
                tg_id INTEGER NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promo_id) REFERENCES promo_codes (id),
                FOREIGN KEY (tg_id) REFERENCES users (tg_id)
            )
            """,
            # Таблица запросов к OpenAI
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                response TEXT,
                tokens_used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tg_id) REFERENCES users (tg_id)
            )
            """
        ]
        
        with self.get_connection() as conn:
            for table in tables:
                conn.execute(table)
    
    def get_or_create_user(self, tg_id: int, username: str = None, 
                          first_name: str = None, last_name: str = None) -> Dict[str, Any]:
        """Получение или создание пользователя"""
        with self.get_connection() as conn:
            # Пытаемся найти пользователя
            user = conn.execute(
                "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
            ).fetchone()
            
            if user:
                return dict(user)
            
            # Создаем нового пользователя
            from config import Config
            conn.execute(
                """INSERT INTO users 
                (tg_id, username, first_name, last_name, balance) 
                VALUES (?, ?, ?, ?, ?)""",
                (tg_id, username, first_name, last_name, Config.DEFAULT_FREE_REQUESTS)
            )
            
            # Возвращаем созданного пользователя
            new_user = conn.execute(
                "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
            ).fetchone()
            
            return dict(new_user)
    
    def update_user_balance(self, tg_id: int, amount: int) -> bool:
        """Обновление баланса пользователя"""
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "UPDATE users SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE tg_id = ?",
                    (amount, tg_id)
                )
                return True
            except Exception as e:
                logging.error(f"Ошибка обновления баланса: {e}")
                return False
    
    def get_user_balance(self, tg_id: int) -> int:
        """Получение баланса пользователя"""
        with self.get_connection() as conn:
            user = conn.execute(
                "SELECT balance FROM users WHERE tg_id = ?", (tg_id,)
            ).fetchone()
            return user['balance'] if user else 0
    
    def add_payment(self, tg_id: int, amount: int, stars_paid: int, 
                   payment_id: str, status: str = "completed") -> bool:
        """Добавление записи о платеже"""
        with self.get_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO payments 
                    (tg_id, amount, stars_paid, payment_id, status) 
                    VALUES (?, ?, ?, ?, ?)""",
                    (tg_id, amount, stars_paid, payment_id, status)
                )
                # Обновляем баланс пользователя
                self.update_user_balance(tg_id, amount)
                return True
            except Exception as e:
                logging.error(f"Ошибка добавления платежа: {e}")
                return False
    
    def create_promo_code(self, code: str, requests: int, max_uses: int = None) -> bool:
        """Создание промокода"""
        with self.get_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO promo_codes (code, requests, max_uses) 
                    VALUES (?, ?, ?)""",
                    (code, requests, max_uses)
                )
                return True
            except sqlite3.IntegrityError:
                logging.error(f"Промокод {code} уже существует")
                return False
            except Exception as e:
                logging.error(f"Ошибка создания промокода: {e}")
                return False
    
    def use_promo_code(self, code: str, tg_id: int) -> Tuple[bool, int]:
        """Использование промокода"""
        with self.get_connection() as conn:
            try:
                # Получаем промокод
                promo = conn.execute(
                    "SELECT * FROM promo_codes WHERE code = ? AND is_active = TRUE",
                    (code,)
                ).fetchone()
                
                if not promo:
                    return False, 0  # Промокод не найден
                
                # Проверяем лимит использования
                if promo['max_uses'] and promo['used_count'] >= promo['max_uses']:
                    return False, 0  # Лимит исчерпан
                
                # Проверяем, использовал ли пользователь уже этот промокод
                existing_usage = conn.execute(
                    "SELECT * FROM promo_usage WHERE promo_id = ? AND tg_id = ?",
                    (promo['id'], tg_id)
                ).fetchone()
                
                if existing_usage:
                    return False, 0  # Промокод уже использован
                
                # Начисляем запросы
                self.update_user_balance(tg_id, promo['requests'])
                
                # Обновляем счетчик использования
                conn.execute(
                    "UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?",
                    (promo['id'],)
                )
                
                # Записываем использование
                conn.execute(
                    "INSERT INTO promo_usage (promo_id, tg_id) VALUES (?, ?)",
                    (promo['id'], tg_id)
                )
                
                return True, promo['requests']
                
            except Exception as e:
                logging.error(f"Ошибка использования промокода: {e}")
                return False, 0
    
    def add_request(self, tg_id: int, prompt: str, response: str = None, 
                   tokens_used: int = 0) -> int:
        """Добавление записи о запросе и уменьшение баланса"""
        with self.get_connection() as conn:
            # Добавляем запрос
            cursor = conn.execute(
                """INSERT INTO requests (tg_id, prompt, response, tokens_used) 
                VALUES (?, ?, ?, ?)""",
                (tg_id, prompt, response, tokens_used)
            )
            
            # Уменьшаем баланс
            conn.execute(
                "UPDATE users SET balance = balance - 1, total_requests = total_requests + 1 WHERE tg_id = ?",
                (tg_id,)
            )
            
            return cursor.lastrowid
    
    def get_user_stats(self, tg_id: int) -> Dict[str, Any]:
        """Получение статистики пользователя"""
        with self.get_connection() as conn:
            user = conn.execute(
                "SELECT balance, total_requests FROM users WHERE tg_id = ?", (tg_id,)
            ).fetchone()
            
            return dict(user) if user else {'balance': 0, 'total_requests': 0}
    
    def get_all_users_stats(self) -> List[Dict[str, Any]]:
        """Получение статистики всех пользователей"""
        with self.get_connection() as conn:
            users = conn.execute(
                """SELECT tg_id, username, first_name, balance, total_requests, created_at 
                FROM users ORDER BY created_at DESC"""
            ).fetchall()
            
            return [dict(user) for user in users]
    
    def get_promo_codes(self) -> List[Dict[str, Any]]:
        """Получение списка всех промокодов"""
        with self.get_connection() as conn:
            promos = conn.execute(
                """SELECT code, requests, max_uses, used_count, is_active, created_at 
                FROM promo_codes ORDER BY created_at DESC"""
            ).fetchall()
            
            return [dict(promo) for promo in promos]
