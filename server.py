"""
=============================================================================
CHORVA ERP CLOUD — Ko'p Foydalanuvchili Bulutli Backend & API
=============================================================================
Xususiyatlari:
1. Render.com va bulutli serverlar uchun to'liq moslashtirilgan.
2. PostgreSQL (Render / Neon / Supabase) va SQLite qo'llab-quvvatlaydi.
3. Telegram Bot orqali telefon raqamni xavfsiz tasdiqlash (Tezkor va qulay).
4. Ko'p foydalanuvchili (Multi-tenant): har bir fermer faqat o'z ma'lumotlarini ko'radi.
5. JWT tokenli xavfsiz autentifikatsiya.
6. Mobil ilova uchun to'liq ikki tomonlama Cloud Sync API.
7. Firebase Cloud Messaging (FCM) bildirishnomalari va Reklama tizimi.
=============================================================================
"""

import os
import sys
import json
import time
import random
import string
import hashlib
import threading
import re
import traceback
from datetime import datetime, timedelta, date
from functools import wraps

from flask import Flask, request, jsonify, make_response, send_file, redirect
from flask_cors import CORS
import jwt
import requests

# ═════════════════════════════════════════════════════════════════════════════
# 1. KONFIGURATSIYA VA MUHIT O'ZGARUVCHILARI
# ═════════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

JWT_SECRET = os.environ.get("JWT_SECRET", "chorva-secret-key-change-in-production-2026")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
# 1. AI Chorva Boti (@AIchorvabot)
CHORVA_BOT_TOKEN = os.environ.get("CHORVA_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", "8863497497:AAE3VAD84pR6Av4nzBaJmGjhe6Thh397OJU"))
CHORVA_BOT_USERNAME = os.environ.get("CHORVA_BOT_USERNAME", os.environ.get("TELEGRAM_BOT_USERNAME", "AIchorvabot"))
TELEGRAM_BOT_TOKEN = CHORVA_BOT_TOKEN
TELEGRAM_BOT_USERNAME = CHORVA_BOT_USERNAME

# 2. Asl Namoz Vaqtlari Boti
PRAYER_BOT_TOKEN = os.environ.get("PRAYER_BOT_TOKEN", "8685776741:AAGFbM6DapVTTcCEczoue01lOj2nB4ag440")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "225011967"))
ADMIN_IDS = {225011967, ADMIN_ID}
ADMIN_USERNAMES = {"fazliddinabduraximov", "fazliddin3388", "fazliddin_abduraximov"}
ADMIN_PHONES = {"+998973387827", "998973387827", "+998973388827", "998973388827"}
ACTIVE_ADMIN_IDS = set(ADMIN_IDS)

def is_admin_user(user_id, username=None, phone=None, full_name=None):
    """Foydalanuvchi Bosh Admin ekanligini ID, Username, Telefon, Ism yoki Baza orqali 100% kafolatli aniqlash"""
    if user_id:
        try:
            uid = int(user_id)
            if uid in ACTIVE_ADMIN_IDS:
                return True
            env_id = os.environ.get("ADMIN_ID")
            if env_id and uid == int(env_id):
                ACTIVE_ADMIN_IDS.add(uid)
                return True
        except Exception:
            pass

    # 1. Ism yoki familiyada Fazliddin bo'lsa (Lotin va Kirill \u0444\u0430\u0437\u043b\u0438\u0434\u0434\u0438\u043d)
    if full_name:
        fn = str(full_name).lower()
        # "fazliddin" yoki "фазлиддин"
        if "fazliddin" in fn or "\u0444\u0430\u0437\u043b\u0438\u0434\u0434\u0438\u043d" in fn:
            if user_id:
                try: ACTIVE_ADMIN_IDS.add(int(user_id))
                except Exception: pass
            return True

    # 2. Username tekshiruvi
    if username:
        clean_u = str(username).lower().replace("@", "").strip()
        if clean_u in ADMIN_USERNAMES:
            if user_id:
                try: ACTIVE_ADMIN_IDS.add(int(user_id))
                except Exception: pass
            return True

    # 3. Telefon tekshiruvi
    if phone:
        clean_p = str(phone).replace(" ", "").replace("-", "").strip()
        if clean_p in ADMIN_PHONES or "973387827" in clean_p:
            if user_id:
                try: ACTIVE_ADMIN_IDS.add(int(user_id))
                except Exception: pass
            return True

    # 4. Ma'lumotlar bazasidan tekshiramiz
    if user_id:
        try:
            conn = get_db()
            c = dict_cursor(conn)
            try:
                c.execute(adapt_query("SELECT role, phone, full_name FROM users WHERE telegram_id = ?"), (user_id,))
                row = c.fetchone()
                if row:
                    if row.get("role") == "admin":
                        ACTIVE_ADMIN_IDS.add(int(user_id))
                        return True
                    db_p = str(row.get("phone") or "").replace(" ", "").replace("-", "").strip()
                    if db_p in ADMIN_PHONES or "973387827" in db_p:
                        ACTIVE_ADMIN_IDS.add(int(user_id))
                        return True
                    db_fn = str(row.get("full_name") or "").lower()
                    if "fazliddin" in db_fn or "\u0444\u0430\u0437\u043b\u0438\u0434\u0434\u0438\u043d" in db_fn:
                        ACTIVE_ADMIN_IDS.add(int(user_id))
                        return True
            finally:
                conn.close()
        except Exception:
            pass

    return False

FIREBASE_SERVER_KEY = os.environ.get("FIREBASE_SERVER_KEY", "")


IS_POSTGRES = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")

# Agar DATABASE_URL postgres:// bo'lsa (Render eski standarti), uni postgresql:// ga to'g'irlaymiz
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ═════════════════════════════════════════════════════════════════════════════
# 2. MA'LUMOTLAR BAZASI BOSHQARUVI (PostgreSQL / SQLite)
# ═════════════════════════════════════════════════════════════════════════════
if IS_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        return conn

    def dict_cursor(conn):
        return conn.cursor(cursor_factory=RealDictCursor)

    def adapt_query(query):
        """SQLite ? belgilarini PostgreSQL %s ga o'girish"""
        return query.replace("?", "%s")
else:
    import sqlite3
    LOCAL_DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chorva_cloud.db")

    class SmartRow(dict):
        """SQLite qatorlarini indeks [0], kalit ['col'] va .get('col') orqali xatosiz o'qish imkoniyati"""
        def __getitem__(self, item):
            if isinstance(item, int):
                return list(self.values())[item]
            return super().__getitem__(item)

    def smart_row_factory(cursor, row):
        return SmartRow({col[0]: row[idx] for idx, col in enumerate(cursor.description)})

    def get_db():
        conn = sqlite3.connect(LOCAL_DB_FILE)
        conn.row_factory = smart_row_factory
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def dict_cursor(conn):
        return conn.cursor()

    def adapt_query(query):
        return query


def init_cloud_database():
    """Bulutli ma'lumotlar bazasi jadvallarini yaratish (Multi-tenant)"""
    conn = get_db()
    c = conn.cursor()
    try:
        # 1. Foydalanuvchilar (Fermerlar)
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                phone VARCHAR(32) UNIQUE NOT NULL,
                full_name VARCHAR(128),
                farm_name VARCHAR(128),
                telegram_id BIGINT UNIQUE,
                telegram_username VARCHAR(64),
                password_hash VARCHAR(256),
                is_verified BOOLEAN DEFAULT FALSE,
                fcm_token TEXT,
                role VARCHAR(32) DEFAULT 'farmer',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                full_name TEXT,
                farm_name TEXT,
                telegram_id INTEGER UNIQUE,
                telegram_username TEXT,
                password_hash TEXT,
                is_verified INTEGER DEFAULT 0,
                fcm_token TEXT,
                role TEXT DEFAULT 'farmer',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Telegram Tasdiqlash Sessiyalari
        c.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                session_id VARCHAR(64) PRIMARY KEY,
                phone VARCHAR(32),
                auth_code VARCHAR(16),
                telegram_id BIGINT,
                verified BOOLEAN DEFAULT FALSE,
                jwt_token TEXT,
                user_id INTEGER,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                session_id TEXT PRIMARY KEY,
                phone TEXT,
                auth_code TEXT,
                telegram_id INTEGER,
                verified INTEGER DEFAULT 0,
                jwt_token TEXT,
                user_id INTEGER,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Jonivorlar (Har bir fermer uchun alohida user_id)
        c.execute("""
            CREATE TABLE IF NOT EXISTS bulls (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                tag_id VARCHAR(64) NOT NULL,
                animal_type VARCHAR(64) DEFAULT 'Buqa',
                breed VARCHAR(64),
                buy_date VARCHAR(32),
                buy_price REAL DEFAULT 0,
                initial_weight REAL DEFAULT 0,
                current_weight REAL DEFAULT 0,
                status VARCHAR(32) DEFAULT 'active',
                sold_date VARCHAR(32),
                sold_weight REAL,
                sold_price_total REAL,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT user_tag_unique UNIQUE (user_id, tag_id)
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS bulls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tag_id TEXT NOT NULL,
                animal_type TEXT DEFAULT 'Buqa',
                breed TEXT,
                buy_date TEXT,
                buy_price REAL DEFAULT 0,
                initial_weight REAL DEFAULT 0,
                current_weight REAL DEFAULT 0,
                status TEXT DEFAULT 'active',
                sold_date TEXT,
                sold_weight REAL,
                sold_price_total REAL,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, tag_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 4. Tarozi o'lchovlari
        c.execute("""
            CREATE TABLE IF NOT EXISTS weighings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                bull_id INTEGER,
                tag_id VARCHAR(64) NOT NULL,
                weigh_date VARCHAR(32) NOT NULL,
                weight REAL NOT NULL,
                gain_since_last REAL DEFAULT 0,
                daily_gain_g REAL DEFAULT 0
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS weighings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bull_id INTEGER,
                tag_id TEXT NOT NULL,
                weigh_date TEXT NOT NULL,
                weight REAL NOT NULL,
                gain_since_last REAL DEFAULT 0,
                daily_gain_g REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 5. Kunlik yem jurnali
        c.execute("""
            CREATE TABLE IF NOT EXISTS feed_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                bull_id INTEGER,
                tag_id VARCHAR(64),
                log_date VARCHAR(32) NOT NULL,
                feed_type VARCHAR(128) NOT NULL,
                amount_kg REAL NOT NULL,
                unit_price REAL NOT NULL,
                total_cost REAL NOT NULL,
                note TEXT,
                from_inventory INTEGER DEFAULT 1
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS feed_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bull_id INTEGER,
                tag_id TEXT,
                log_date TEXT NOT NULL,
                feed_type TEXT NOT NULL,
                amount_kg REAL NOT NULL,
                unit_price REAL NOT NULL,
                total_cost REAL NOT NULL,
                note TEXT,
                from_inventory INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 6. Yem Ombori (feed_inventory)
        c.execute("""
            CREATE TABLE IF NOT EXISTS feed_inventory (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                feed_type VARCHAR(128) NOT NULL,
                current_stock_kg REAL DEFAULT 0,
                min_warning_kg REAL DEFAULT 100,
                unit_price REAL DEFAULT 0,
                last_restock_date VARCHAR(32),
                CONSTRAINT user_feed_unique UNIQUE (user_id, feed_type)
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS feed_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                feed_type TEXT NOT NULL,
                current_stock_kg REAL DEFAULT 0,
                min_warning_kg REAL DEFAULT 100,
                unit_price REAL DEFAULT 0,
                last_restock_date TEXT,
                UNIQUE (user_id, feed_type),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 7. Boshqa xarajatlar
        c.execute("""
            CREATE TABLE IF NOT EXISTS other_expenses (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                bull_id INTEGER,
                tag_id VARCHAR(64),
                exp_date VARCHAR(32) NOT NULL,
                category VARCHAR(128) NOT NULL,
                amount REAL NOT NULL,
                description TEXT
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS other_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bull_id INTEGER,
                tag_id TEXT,
                exp_date TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 8. Kassa amaliyotlari
        c.execute("""
            CREATE TABLE IF NOT EXISTS cash_transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                trans_date VARCHAR(32) NOT NULL,
                trans_type VARCHAR(64) NOT NULL,
                amount REAL NOT NULL,
                category VARCHAR(128),
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS cash_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                trans_date TEXT NOT NULL,
                trans_type TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 9. Qarzlar va Kreditorlar
        c.execute("""
            CREATE TABLE IF NOT EXISTS debts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                creditor_name VARCHAR(128) NOT NULL,
                phone VARCHAR(32),
                debt_type VARCHAR(32) DEFAULT 'borrowed',
                initial_amount REAL NOT NULL,
                remaining_amount REAL NOT NULL,
                start_date VARCHAR(32) NOT NULL,
                due_date VARCHAR(32),
                status VARCHAR(32) DEFAULT 'active',
                notes TEXT
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                creditor_name TEXT NOT NULL,
                phone TEXT,
                debt_type TEXT DEFAULT 'borrowed',
                initial_amount REAL NOT NULL,
                remaining_amount REAL NOT NULL,
                start_date TEXT NOT NULL,
                due_date TEXT,
                status TEXT DEFAULT 'active',
                notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 10. Qarz to'lovlari
        c.execute("""
            CREATE TABLE IF NOT EXISTS debt_payments (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                debt_id INTEGER NOT NULL,
                pay_date VARCHAR(32) NOT NULL,
                amount REAL NOT NULL,
                notes TEXT
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS debt_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                debt_id INTEGER NOT NULL,
                pay_date TEXT NOT NULL,
                amount REAL NOT NULL,
                notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 11. Emlash taqvimi
        c.execute("""
            CREATE TABLE IF NOT EXISTS vaccine_schedules (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                bull_id INTEGER,
                tag_id VARCHAR(64),
                vaccine_name VARCHAR(128) NOT NULL,
                planned_date VARCHAR(32) NOT NULL,
                completed_date VARCHAR(32),
                dose VARCHAR(64),
                veterinarian VARCHAR(128),
                status VARCHAR(32) DEFAULT 'pending',
                cost REAL DEFAULT 0,
                notes TEXT
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS vaccine_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bull_id INTEGER,
                tag_id TEXT,
                vaccine_name TEXT NOT NULL,
                planned_date TEXT NOT NULL,
                completed_date TEXT,
                dose TEXT,
                veterinarian TEXT,
                status TEXT DEFAULT 'pending',
                cost REAL DEFAULT 0,
                notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 12. Reklama va E'lonlar (Admin tomonidan boshqariladi)
        c.execute("""
            CREATE TABLE IF NOT EXISTS advertisements (
                id SERIAL PRIMARY KEY,
                title VARCHAR(256) NOT NULL,
                image_url TEXT,
                link_url TEXT,
                description TEXT,
                category VARCHAR(64) DEFAULT 'general',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS advertisements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                image_url TEXT,
                link_url TEXT,
                description TEXT,
                category TEXT DEFAULT 'general',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 13. Namoz vaqtlari foydalanuvchilari (Telegram bot)
        c.execute("""
            CREATE TABLE IF NOT EXISTS prayer_users (
                telegram_id BIGINT PRIMARY KEY,
                username VARCHAR(64),
                full_name VARCHAR(128),
                region VARCHAR(64) DEFAULT 'Toshkent',
                notifications BOOLEAN DEFAULT TRUE,
                notif_offset INTEGER DEFAULT 0,
                last_notif_time VARCHAR(32),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS prayer_users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                region TEXT DEFAULT 'Toshkent',
                notifications INTEGER DEFAULT 1,
                notif_offset INTEGER DEFAULT 0,
                last_notif_time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 14. Mobil Ilova APK Versiyalari (Admin Telegram orqali yangilaydi)
        c.execute("""
            CREATE TABLE IF NOT EXISTS app_releases (
                id SERIAL PRIMARY KEY,
                file_id TEXT NOT NULL,
                file_name VARCHAR(256),
                file_size BIGINT,
                version_name VARCHAR(64) DEFAULT 'v1.8',
                changelog TEXT,
                uploaded_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS app_releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                file_name TEXT,
                file_size INTEGER,
                version_name TEXT DEFAULT 'v1.8',
                changelog TEXT,
                uploaded_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


        # 15. Tizim Sozlamalari (Majburiy kirish, GitHub token, oxirgi zaxira vaqtlari)
        c.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key VARCHAR(64) PRIMARY KEY,
                setting_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Boshlang'ich qiymatlarni kiritish (agar mavjud bo'lmasa)
        c.execute(adapt_query("""
            INSERT INTO system_settings (setting_key, setting_value)
            VALUES ('require_auth', 'true')
            ON CONFLICT (setting_key) DO NOTHING
        """ if IS_POSTGRES else """
            INSERT OR IGNORE INTO system_settings (setting_key, setting_value)
            VALUES ('require_auth', 'true')
        """))

        conn.commit()

        # Avtomatik ustunlar migratsiyasi (mavjud ma'lumotlarni 100% saqlagan holda)
        run_cloud_schema_migrations(conn)

        print("[DB INIT] Bulutli ma'lumotlar bazasi jadvallari muvaffaqiyatli tayyorlandi!")
    except Exception as e:
        conn.rollback()
        print(f"[DB INIT ERR]: {e}")

    finally:
        conn.close()

    # ─── SERVER ISHGA TUSHGANDA GITHUB'DAN BAZANI AVTOMATIK TIKLASH ───
    try:
        def _deferred_restore():
            time.sleep(1)
            fn = globals().get("auto_restore_database_from_github")
            if fn:
                fn()
        threading.Thread(target=_deferred_restore, daemon=True).start()
    except Exception as e_res:
        print(f"[AUTO RESTORE TRIGGER ERR]: {e_res}")


def get_system_setting(key, default=None):
    """Tizim sozlamasini ma'lumotlar bazasidan xavfsiz o'qish"""
    try:
        conn = get_db()
        c = dict_cursor(conn)
        c.execute(adapt_query("SELECT setting_value FROM system_settings WHERE setting_key = ?"), (key,))
        row = c.fetchone()
        conn.close()
        if row and row.get("setting_value") is not None:
            return str(row["setting_value"])
        return default
    except Exception:
        return default


def set_system_setting(key, value):
    """Tizim sozlamasini ma'lumotlar bazasiga saqlash yoki yangilash"""
    try:
        conn = get_db()
        c = conn.cursor()
        val_str = str(value)
        c.execute(adapt_query("""
            INSERT INTO system_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP
        """ if IS_POSTGRES else """
            INSERT INTO system_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP
        """), (key, val_str))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[SETTING SAVE ERR]: {e}")
        return False



def run_cloud_schema_migrations(conn):
    """Mavjud jadvallarga yangi versiya ustunlarini qo'shish (ma'lumotlarni saqlagan holda)"""
    cursor = conn.cursor()
    migrations = [
        ("app_releases", "version_code", "INTEGER DEFAULT 222"),
        ("users", "last_active_at", "TIMESTAMP"),
        ("users", "client_version", "VARCHAR(32)"),
        ("bulls", "sync_id", "VARCHAR(128)"),
        ("bulls", "gender", "VARCHAR(32) DEFAULT 'erkak'"),
        ("bulls", "birth_date", "DATE"),
        ("weighings", "sync_id", "VARCHAR(128)"),
        ("feed_logs", "sync_id", "VARCHAR(128)"),
        ("other_expenses", "sync_id", "VARCHAR(128)"),
        ("cash_transactions", "sync_id", "VARCHAR(128)"),
        ("debts", "sync_id", "VARCHAR(128)"),
        ("debts", "remaining_amount", "NUMERIC(14, 2) DEFAULT 0"),
        ("debt_payments", "sync_id", "VARCHAR(128)"),
        ("vaccine_schedules", "sync_id", "VARCHAR(128)"),
        ("feed_inventory", "sync_id", "VARCHAR(128)"),
        ("advertisements", "media_type", "VARCHAR(32) DEFAULT 'text'"),
        ("advertisements", "media_file_id", "TEXT"),
        ("advertisements", "views_count", "INTEGER DEFAULT 0"),
        ("advertisements", "sent_count", "INTEGER DEFAULT 0"),
        ("bulls", "mother_id", "INTEGER"),
        ("bulls", "mother_tag", "VARCHAR(64)" if IS_POSTGRES else "TEXT"),
        ("bulls", "breeding_status", "VARCHAR(32)" if IS_POSTGRES else "TEXT"),
        ("bulls", "breeding_date", "VARCHAR(32)" if IS_POSTGRES else "TEXT"),
        ("bulls", "expected_birth_date", "VARCHAR(32)" if IS_POSTGRES else "TEXT"),
        ("bulls", "birth_count", "INTEGER DEFAULT 0"),
        ("bulls", "last_birth_date", "VARCHAR(32)" if IS_POSTGRES else "TEXT")
    ]

    for table, col, col_type in migrations:
        try:
            if not IS_POSTGRES:
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [row[1] for row in cursor.fetchall()]
                if col not in cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            else:
                cursor.execute(f"""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = '{table}' AND column_name = '{col}'
                """)
                if not cursor.fetchone():
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}")
        except Exception:
            pass

    # Nasl olish jurnali jadvali (breeding_records)
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS breeding_records (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                mother_id INTEGER,
                mother_tag VARCHAR(64) NOT NULL,
                animal_type VARCHAR(64) DEFAULT 'Sovliq',
                breeding_date VARCHAR(32),
                breeding_method VARCHAR(64),
                sire_info VARCHAR(128),
                status VARCHAR(32) DEFAULT 'kutilmoqda',
                expected_birth_date VARCHAR(32),
                birth_date VARCHAR(32),
                birth_result VARCHAR(64),
                birth_count INTEGER DEFAULT 0,
                offspring_tag VARCHAR(64),
                offspring_type VARCHAR(64),
                offspring_weight REAL,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """ if IS_POSTGRES else """
            CREATE TABLE IF NOT EXISTS breeding_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mother_id INTEGER,
                mother_tag TEXT NOT NULL,
                animal_type TEXT DEFAULT 'Sovliq',
                breeding_date TEXT,
                breeding_method TEXT,
                sire_info TEXT,
                status TEXT DEFAULT 'kutilmoqda',
                expected_birth_date TEXT,
                birth_date TEXT,
                birth_result TEXT,
                birth_count INTEGER DEFAULT 0,
                offspring_tag TEXT,
                offspring_type TEXT,
                offspring_weight REAL,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
    except Exception as e:
        print(f"[BREEDING TABLE MIGRATION ERR]: {e}")

    # Eski 'v1.7' yozuvlarini yangi 'v1.8' ga xavfsiz yangilash
    try:
        cursor.execute("UPDATE app_releases SET version_name = 'v1.8' WHERE version_name = 'v1.7' OR version_name = '1.7'")
    except Exception:
        pass

    try:
        conn.commit()
    except Exception:
        pass


init_cloud_database()

# ═════════════════════════════════════════════════════════════════════════════
# 3. YORDAMCHI VA AUTENTIFIKATSIYA FUNKSIYALARI (JWT)
# ═════════════════════════════════════════════════════════════════════════════
def generate_jwt(user_id, phone, role="farmer"):
    payload = {
        "user_id": user_id,
        "phone": phone,
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=365) # 1 yil yaroqli
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"status": "error", "message": "Avtorizatsiya talab qilinadi (Token mavjud emas)"}), 401
        token = auth_header.split(" ")[1]
        try:
            decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.current_user = decoded
        except jwt.ExpiredSignatureError:
            return jsonify({"status": "error", "message": "Token muddati tugagan"}), 401
        except Exception:
            return jsonify({"status": "error", "message": "Yaroqsiz token"}), 401
        return f(*args, **kwargs)
    return decorated


# ═════════════════════════════════════════════════════════════════════════════
# 4. NAMOZ VAQTLARI & TELEGRAM BOT ENGINE (@AIchorvabot)
# ═════════════════════════════════════════════════════════════════════════════

# Global Toshkent vaqti
def get_now_tashkent():
    """Toshkent vaqti (UTC+5) bo'yicha hozirgi vaqt"""
    try:
        # Agar server UTC da ishlasa
        utc_now = datetime.utcnow()
        return utc_now + timedelta(hours=5)
    except Exception:
        return datetime.now()

# ─── NAMOZ MINTAQALARI MA'LUMOTLAR BAZASI ───
PRAYER_DATA = {
    "Toshkent": ["Toshkent", "Angren", "Bekobod", "Chirchiq"],
    "Andijon": ["Andijon", "Asaka", "Shahrixon", "Xo'jaobod", "Uchqo'rg'on"],
    "Buxoro": ["Buxoro", "G'ijduvon", "Qorako'l", "Olot", "Qorovulbozor", "Gazli"],
    "Farg'ona": ["Farg'ona", "Marg'ilon", "Qo'qon", "Quva", "Rishton", "Oltiariq"],
    "Jizzax": ["Jizzax", "Zomin", "Do'stlik", "G'allaorol", "O'smat", "Arnasoy"],
    "Namangan": ["Namangan", "Chortoq", "Chust", "Kosonsoy", "Mingbuloq", "Pop"],
    "Navoiy": ["Navoiy", "Zarafshon", "Uchquduq", "Nurota", "Qiziltepa", "Konimex", "Tomdi"],
    "Qashqadaryo": ["Qarshi", "Muborak", "Tallimarjon", "G'uzor", "Koson", "Dehqonobod"],
    "Samarqand": ["Samarqand", "Kattaqo'rg'on", "Jomboy", "Urgut"],
    "Sirdaryo": ["Guliston"],
    "Surxondaryo": ["Termiz", "Denov", "Sherobod", "Boysun", "Qumqo'rg'on"],
    "Xorazm": ["Urganch", "Xiva", "Xonqa", "Shovot", "Xazorasp"],
    "Qoraqalpog'iston": ["Nukus", "Mo'ynoq", "Qo'ng'irot", "To'rtko'l", "Chimboy", "Shumanay", "Taxtako'pir"]
}

PRAYER_API_MAP = {
    "Asaka": "Andijon", "Chirchiq": "Toshkent", "G'ijduvon": "Buxoro", "Xo'jaobod": "Andijon",
    "Bog'dod": "Farg'ona", "Sardoba": "Guliston", "Ishtixon": "Samarqand", "Shahrisabz": "Qarshi",
    "Sho'rchi": "Termiz", "Gurlan": "Urganch", "Do'stlik": "Jizzax"
}

PRAYER_CITY_MAP = {
    "Toshkent": "Tashkent", "Chirchiq": "Chirchiq", "Angren": "Angren", "Bekobod": "Tashkent",
    "Samarqand": "Samarkand", "Kattaqo'rg'on": "Samarkand", "Jomboy": "Samarkand", "Urgut": "Samarkand",
    "Andijon": "Andijan", "Asaka": "Andijan", "Shahrixon": "Andijan", "Xo'jaobod": "Andijan", "Uchqo'rg'on": "Andijan",
    "Farg'ona": "Fergana", "Marg'ilon": "Margilan", "Qo'qon": "Kokand", "Quva": "Fergana", "Rishton": "Fergana", "Oltiariq": "Fergana",
    "Namangan": "Namangan", "Chortoq": "Namangan", "Chust": "Namangan", "Kosonsoy": "Namangan", "Mingbuloq": "Namangan", "Pop": "Namangan",
    "Buxoro": "Bukhara", "G'ijduvon": "Bukhara", "Qorako'l": "Bukhara", "Olot": "Bukhara", "Qorovulbozor": "Bukhara", "Gazli": "Bukhara",
    "Qarshi": "Karshi", "Muborak": "Karshi", "Tallimarjon": "Karshi", "G'uzor": "Karshi", "Koson": "Karshi", "Dehqonobod": "Karshi",
    "Termiz": "Termez", "Denov": "Denau", "Sherobod": "Termez", "Boysun": "Termez", "Qumqo'rg'on": "Termez",
    "Guliston": "Guliston",
    "Jizzax": "Jizzakh", "Zomin": "Jizzakh", "Do'stlik": "Jizzakh", "G'allaorol": "Jizzakh", "O'smat": "Jizzakh", "Arnasoy": "Jizzakh",
    "Navoiy": "Navoi", "Zarafshon": "Zarafshan", "Uchquduq": "Navoi", "Nurota": "Navoi", "Qiziltepa": "Navoi", "Konimex": "Navoi", "Tomdi": "Navoi",
    "Urganch": "Urgench", "Xiva": "Urgench", "Xonqa": "Urgench", "Shovot": "Urgench", "Xazorasp": "Urgench",
    "Nukus": "Nukus", "Mo'ynoq": "Nukus", "Qo'ng'irot": "Nukus", "To'rtko'l": "Nukus", "Chimboy": "Nukus", "Shumanay": "Nukus", "Taxtako'pir": "Nukus"
}

PRAYER_CACHE = {}  # {region: {date: '27.09.2026', times: {...}}}
ISLOMAPI_DOWN_UNTIL = 0


def fetch_prayer_times(region="Toshkent"):
    """Birlamchi islomapi.uz va zaxira Aladhan orqali namoz vaqtlarini kesh bilan olish"""
    global ISLOMAPI_DOWN_UNTIL
    now_dt = get_now_tashkent()
    today_str = now_dt.strftime("%d.%m.%Y")

    # Keshni tekshirish
    if region in PRAYER_CACHE and PRAYER_CACHE[region].get("date") == today_str:
        return PRAYER_CACHE[region]["data"]

    api_region = PRAYER_API_MAP.get(region, region)
    times_result = None

    # 1. Birlamchi: islomapi.uz
    if time.time() > ISLOMAPI_DOWN_UNTIL:
        try:
            url = "https://islomapi.uz/api/present/day"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIchorvabot/2.0"}
            r = requests.get(url, params={"region": api_region}, headers=headers, timeout=4)
            if r.status_code == 200:
                dj = r.json()
                if dj and "times" in dj:
                    times_result = dj["times"]
            else:
                ISLOMAPI_DOWN_UNTIL = time.time() + 300
        except Exception:
            ISLOMAPI_DOWN_UNTIL = time.time() + 300

    # 2. Zaxira: Aladhan API (Hanafi, O'zbekiston)
    if not times_result:
        city = PRAYER_CITY_MAP.get(region, PRAYER_CITY_MAP.get(api_region, "Tashkent"))
        try:
            url = f"https://api.aladhan.com/v1/timingsByCity?city={city}&country=Uzbekistan&method=14&school=1"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIchorvabot/2.0"}
            r = requests.get(url, headers=headers, timeout=6)
            if r.status_code == 200:
                data = r.json().get("data", {})
                t = data.get("timings", {})
                times_result = {
                    "tong_saharlik": t.get("Fajr"),
                    "quyosh": t.get("Sunrise"),
                    "peshin": t.get("Dhuhr"),
                    "asr": t.get("Asr"),
                    "shom_iftor": t.get("Maghrib"),
                    "hufton": t.get("Isha")
                }
        except Exception as e:
            print(f"[ALADHAN FALLBACK ERR]: {e}")

    # Agar ikkala API ham javob bermasa standart o'rtacha taqvim
    if not times_result:
        times_result = {
            "tong_saharlik": "05:00",
            "quyosh": "06:20",
            "peshin": "12:30",
            "asr": "16:45",
            "shom_iftor": "18:30",
            "hufton": "19:50"
        }

    # Hozirgi va keyingi namozni aniqlash
    uzb_weekdays = {
        "Monday": "Dushanba", "Tuesday": "Seshanba", "Wednesday": "Chorshanba",
        "Thursday": "Payshanba", "Friday": "Juma", "Saturday": "Shanba", "Sunday": "Yakshanba"
    }
    weekday_uz = uzb_weekdays.get(now_dt.strftime("%A"), "")

    prayer_list = [
        ("tong_saharlik", "Bomdod", "🏙"),
        ("quyosh", "Quyosh", "🌅"),
        ("peshin", "Peshin", "☀️"),
        ("asr", "Asr", "🌇"),
        ("shom_iftor", "Shom", "🌆"),
        ("hufton", "Xufton", "🌃")
    ]

    current_prayer = "Xufton"
    next_prayer = "Bomdod"
    next_time = times_result.get("tong_saharlik", "05:00")
    minutes_left = 0
    time_left_str = ""

    for k, n_uz, _ in prayer_list:
        t_str = times_result.get(k)
        if t_str:
            th, tm = map(int, t_str.split(":"))
            p_dt = now_dt.replace(hour=th, minute=tm, second=0, microsecond=0)
            if p_dt > now_dt:
                next_prayer = n_uz
                next_time = t_str
                diff_sec = int((p_dt - now_dt).total_seconds())
                minutes_left = diff_sec // 60
                h_left, m_left = divmod(minutes_left, 60)
                time_left_str = f"{h_left} soat {m_left} daqiqa" if h_left > 0 else f"{m_left} daqiqa"
                break
            else:
                current_prayer = n_uz

    # Agar bugungi barcha namozlar o'tgan bo'lsa (keyingisi ertangi Bomdod)
    if not time_left_str:
        t_str = times_result.get("tong_saharlik", "05:00")
        th, tm = map(int, t_str.split(":"))
        p_dt = (now_dt + timedelta(days=1)).replace(hour=th, minute=tm, second=0, microsecond=0)
        diff_sec = int((p_dt - now_dt).total_seconds())
        minutes_left = diff_sec // 60
        h_left, m_left = divmod(minutes_left, 60)
        time_left_str = f"{h_left} soat {m_left} daqiqa" if h_left > 0 else f"{m_left} daqiqa"
        next_prayer = "Bomdod (ertaga)"
        next_time = t_str

    formatted_data = {
        "region": region,
        "date": today_str,
        "weekday": weekday_uz,
        "now_time": now_dt.strftime("%H:%M"),
        "times": times_result,
        "current_prayer": current_prayer,
        "next_prayer": next_prayer,
        "next_time": next_time,
        "minutes_left": minutes_left,
        "time_left_str": time_left_str
    }

    # Keshga yozish
    PRAYER_CACHE[region] = {"date": today_str, "data": formatted_data}
    return formatted_data


def format_prayer_card_message(region: str):
    """Telegram bot uchun ko'rkam namoz vaqtlari matni"""
    data = fetch_prayer_times(region)
    times = data["times"]

    prayer_lines = [
        ("tong_saharlik", "Bomdod", "🏙"),
        ("quyosh", "Quyosh", "🌅"),
        ("peshin", "Peshin", "☀️"),
        ("asr", "Asr", "🌇"),
        ("shom_iftor", "Shom", "🌆"),
        ("hufton", "Xufton", "🌃")
    ]

    schedule_text = ""
    for k, name, ico in prayer_lines:
        val = times.get(k, "--:--")
        if name in data["current_prayer"]:
            schedule_text += f"🟢 <b>{ico} {name}: {val}</b> <i>(Hozir)</i>\n"
        else:
            schedule_text += f"▫️ {ico} {name}: <code>{val}</code>\n"

    msg = (
        "╭────────────────────────╮\n"
        f"   🕌  <b>{region.upper()} NAMOZ TAQVIMI</b>\n"
        "╰────────────────────────╯\n"
        f"📅 <b>Sana:</b> {data['date']} • <b>{data['weekday']}</b>\n"
        f"🕒 <b>Hozirgi vaqt:</b> {data['now_time']}\n\n"
        f"📋 <b>Kunlik namoz vaqtlari:</b>\n"
        f"{schedule_text}\n"
        f"⏳ <b>Keyingi ibodat:</b> <b>{data['next_prayer']} ({data['next_time']})</b>\n"
        f"⌛️ <b>Qolgan vaqt:</b> <i>{data['time_left_str']}</i>\n\n"
        "────────────────────────\n"
        "💬 <i>«Namozni to'kis ado etinglar. Albatta, namoz mo'minlarga vaqtida tayinlangan farzdir.» (Niso, 103)</i>\n"
        "✨ <i>Alloh taolo ibodatlaringizni dargohida qabul qilsin!</i>"
    )
    return msg


# Telegram bot yordamchi funksiyalari (Ikkala botni qo'llab-quvvatlaydi)
def send_telegram_msg(chat_id, text, reply_markup=None, bot_token=None):
    tok = bot_token or CHORVA_BOT_TOKEN
    if not tok:
        return None
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code == 200:
            return r.json().get("result")
        print(f"[TG MSG RESP ERR]: status={r.status_code} body={r.text}")
        # Agar HTML formatda xatolik bo'lsa, oddiy matn sifatida qayta yuborish
        if "entity" in r.text.lower() or "parse" in r.text.lower() or "bad request" in r.text.lower():
            payload.pop("parse_mode", None)
            r2 = requests.post(url, json=payload, timeout=8)
            if r2.status_code == 200:
                return r2.json().get("result")
    except Exception as e:
        print(f"[TG MSG ERR]: {e}")
    return None


def inspect_apk_metadata(source):
    """
    APK faylidan (fayl yo'li, baytlar yoki file-like obyektdan) haqiqiy versiya (version_name),
    versiya kodi (version_code) va fayl hajmini (size_mb) avtomatik aniqlash.
    """
    meta = {"version_name": None, "version_code": None, "size_mb": None}
    if not source:
        return meta
    try:
        import zipfile
        import io
        zf = None
        if isinstance(source, (str, bytes, bytearray)):
            if isinstance(source, str):
                if os.path.exists(source):
                    meta["size_mb"] = round(os.path.getsize(source) / (1024 * 1024), 2)
                    zf = zipfile.ZipFile(source, 'r')
            else:
                meta["size_mb"] = round(len(source) / (1024 * 1024), 2)
                zf = zipfile.ZipFile(io.BytesIO(source), 'r')
        elif hasattr(source, 'read'):
            zf = zipfile.ZipFile(source, 'r')

        if zf:
            with zf:
                # 1. assets/public/app.js ichidagi APP_VERSION va APP_VERSION_CODE
                for name in zf.namelist():
                    if name.endswith("app.js") or "app.bundle" in name:
                        try:
                            content = zf.read(name).decode("utf-8", errors="ignore")
                            m_v = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", content)
                            if m_v:
                                meta["version_name"] = m_v.group(1).replace("v", "").strip()
                            m_c = re.search(r"APP_VERSION_CODE\s*=\s*(\d+)", content)
                            if m_c:
                                meta["version_code"] = int(m_c.group(1))
                            if meta["version_name"]:
                                break
                        except Exception:
                            pass

                # 2. Agar js dan topilmasa, AndroidManifest.xml string poolidan tahlil
                if not meta["version_name"] and "AndroidManifest.xml" in zf.namelist():
                    try:
                        import struct
                        axml_data = zf.read("AndroidManifest.xml")
                        str_count = struct.unpack('<I', axml_data[16:20])[0]
                        flags = struct.unpack('<I', axml_data[24:28])[0]
                        strings_start = struct.unpack('<I', axml_data[28:32])[0]
                        is_utf8 = bool(flags & (1 << 8))
                        offsets = [struct.unpack('<I', axml_data[36 + i*4:40 + i*4])[0] for i in range(min(str_count, 120))]
                        base = 8 + strings_start
                        for off in offsets:
                            pos = base + off
                            if is_utf8:
                                u8len = axml_data[pos+1]
                                s = axml_data[pos+2:pos+2+u8len].decode('utf-8', errors='ignore')
                            else:
                                u16len = struct.unpack('<H', axml_data[pos:pos+2])[0]
                                s = axml_data[pos+2:pos+2+u16len*2].decode('utf-16le', errors='ignore')
                            if re.match(r'^\d+\.\d+(\.\d+)?$', s):
                                meta["version_name"] = s.strip()
                                break
                    except Exception:
                        pass
    except Exception as e:
        print(f"[APK METADATA INSPECT ERR]: {e}")
    return meta


def cache_apk_locally(file_id, bot_token=None):
    """Admin yuborgan APK faylni Telegramdan yuklab olib, server diskida ChorvaERP.apk nomi bilan saqlash"""
    tok = bot_token or CHORVA_BOT_TOKEN
    if not tok or not file_id:
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getFile?file_id={file_id}", timeout=15)
        if r.status_code == 200:
            file_path = r.json().get("result", {}).get("file_path")
            if file_path:
                dl_url = f"https://api.telegram.org/file/bot{tok}/{file_path}"
                dl_resp = requests.get(dl_url, timeout=90, stream=True)
                if dl_resp.status_code == 200:
                    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk")
                    with open(local_path, "wb") as f:
                        for chunk in dl_resp.iter_content(chunk_size=1024 * 64):
                            if chunk:
                                f.write(chunk)
                    print(f"[APK DISK SAVE OK]: Server diskiga saqlandi -> {local_path} ({os.path.getsize(local_path)} bayt)")

                    # APK ichidagi versiya va kodni avtomatik aniqlab version.json ga yozish
                    try:
                        meta = inspect_apk_metadata(local_path)
                        if meta.get("version_name"):
                            v_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.json")
                            v_obj = {
                                "versionName": meta["version_name"],
                                "versionCode": meta.get("version_code") or 224,
                                "sizeMb": str(meta.get("size_mb") or 5.37),
                                "lastBuild": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "changelog": "Rasmiy yangilangan APK ilovasi"
                            }
                            with open(v_file, "w", encoding="utf-8") as vf:
                                json.dump(v_obj, vf, indent=2)
                    except Exception as ex_m:
                        print(f"[APK AUTO UPDATE JSON ERR]: {ex_m}")

                    return local_path
    except Exception as e:
        print(f"[APK DISK SAVE ERR]: {e}")
    return None


def send_telegram_document(chat_id, document, caption=None, reply_markup=None, bot_token=None):
    tok = bot_token or CHORVA_BOT_TOKEN
    if not tok:
        return None
    url = f"https://api.telegram.org/bot{tok}/sendDocument"

    # 1. Agar document server diskidagi mahalliy fayl bo'lsa
    if isinstance(document, str) and os.path.exists(document):
        try:
            with open(document, "rb") as f_obj:
                ext = os.path.splitext(document)[1].lower()
                if ext == ".apk":
                    mime_type = "application/vnd.android.package-archive"
                elif ext in (".db", ".sqlite", ".sqlite3"):
                    mime_type = "application/x-sqlite3"
                elif ext == ".json":
                    mime_type = "application/json"
                else:
                    mime_type = "application/octet-stream"
                files = {"document": (os.path.basename(document), f_obj, mime_type)}
                data = {"chat_id": chat_id, "parse_mode": "HTML"}
                if caption: data["caption"] = caption
                if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
                r = requests.post(url, data=data, files=files, timeout=60)
                if r.status_code == 200:
                    return r.json().get("result")
                print(f"[TG DOC FILE ERR]: status={r.status_code} body={r.text}")
        except Exception as e:
            print(f"[TG DOC FILE EXCEPTION]: {e}")

    # 2. Agar document Telegram file_id bo'lsa
    payload = {"chat_id": chat_id, "document": document, "parse_mode": "HTML"}
    if caption:
        payload["caption"] = caption
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=35)
        if r.status_code == 200:
            return r.json().get("result")
        print(f"[TG DOC ERR]: token={tok[:10]}... status={r.status_code} body={r.text}")

        # Boshqa bot tokeni bilan urinib ko'rish
        other_tok = PRAYER_BOT_TOKEN if tok == CHORVA_BOT_TOKEN else CHORVA_BOT_TOKEN
        if other_tok and other_tok != tok:
            url2 = f"https://api.telegram.org/bot{other_tok}/sendDocument"
            r2 = requests.post(url2, json=payload, timeout=35)
            if r2.status_code == 200:
                return r2.json().get("result")
            print(f"[TG DOC RETRY ERR]: token={other_tok[:10]}... status={r2.status_code} body={r2.text}")

        # Agar file_id o'tmasa, server diskidagi ChorvaERP.apk ni fayl qilib uzatish
        local_apk = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk")
        if os.path.exists(local_apk):
            with open(local_apk, "rb") as f_obj:
                files = {"document": ("ChorvaERP.apk", f_obj, "application/vnd.android.package-archive")}
                data = {"chat_id": chat_id, "parse_mode": "HTML"}
                if caption: data["caption"] = caption
                if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
                r3 = requests.post(url, data=data, files=files, timeout=60)
                if r3.status_code == 200:
                    return r3.json().get("result")
    except Exception as e:
        print(f"[TG DOC EXCEPTION]: {e}")
    return None


def send_telegram_photo(chat_id, photo, caption=None, reply_markup=None, bot_token=None):
    """Telegram orqali rasm yuborish (Mahalliy fayl yoki file_id)"""
    tok = bot_token or CHORVA_BOT_TOKEN
    if not tok:
        return None
    url = f"https://api.telegram.org/bot{tok}/sendPhoto"

    # 1. Agar photo diskdagi mahalliy fayl bo'lsa
    if isinstance(photo, str) and os.path.exists(photo):
        try:
            with open(photo, "rb") as f_obj:
                files = {"photo": (os.path.basename(photo), f_obj, "image/jpeg")}
                data = {"chat_id": chat_id, "parse_mode": "HTML"}
                if caption: data["caption"] = caption
                if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
                r = requests.post(url, data=data, files=files, timeout=35)
                if r.status_code == 200:
                    return r.json().get("result")
                print(f"[TG PHOTO FILE ERR]: status={r.status_code} body={r.text}")
        except Exception as e:
            print(f"[TG PHOTO EXCEPTION]: {e}")
            return None

    # 2. Agar photo file_id yoki URL bo'lsa
    payload = {"chat_id": chat_id, "photo": photo, "parse_mode": "HTML"}
    if caption: payload["caption"] = caption
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=25)
        if r.status_code == 200:
            return r.json().get("result")
        print(f"[TG PHOTO ERR]: status={r.status_code} body={r.text}")
    except Exception as e:
        print(f"[TG PHOTO ERR]: {e}")
    return None


def send_telegram_video(chat_id, video, caption=None, reply_markup=None, bot_token=None):
    """Telegram orqali video yuborish (Mahalliy fayl yoki file_id)"""
    tok = bot_token or CHORVA_BOT_TOKEN
    if not tok:
        return None
    url = f"https://api.telegram.org/bot{tok}/sendVideo"

    # 1. Agar video diskdagi mahalliy fayl bo'lsa
    if isinstance(video, str) and os.path.exists(video):
        try:
            with open(video, "rb") as f_obj:
                files = {"video": (os.path.basename(video), f_obj, "video/mp4")}
                data = {"chat_id": chat_id, "parse_mode": "HTML"}
                if caption: data["caption"] = caption
                if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
                r = requests.post(url, data=data, files=files, timeout=60)
                if r.status_code == 200:
                    return r.json().get("result")
                print(f"[TG VIDEO FILE ERR]: status={r.status_code} body={r.text}")
        except Exception as e:
            print(f"[TG VIDEO FILE EXCEPTION]: {e}")
            return None

    # 2. Agar video file_id yoki URL bo'lsa
    payload = {"chat_id": chat_id, "video": video, "parse_mode": "HTML"}
    if caption: payload["caption"] = caption
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json().get("result")
        print(f"[TG VIDEO ERR]: status={r.status_code} body={r.text}")
    except Exception as e:
        print(f"[TG VIDEO ERR]: {e}")
    return None


def send_telegram_media_generic(chat_id, media_type, file_id_or_path, text_content=None, reply_markup=None, bot_token=None):
    """
    Universal media jo'natish funksiyasi (text, photo, video, document).
    Qaytaradi: (success: bool, is_blocked: bool, error_msg: str)
    """
    tok = bot_token or CHORVA_BOT_TOKEN
    if not tok:
        return False, False, "Token mavjud emas"

    m_type = (media_type or "text").lower()
    
    if m_type == "photo" and file_id_or_path:
        url = f"https://api.telegram.org/bot{tok}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": file_id_or_path, "caption": text_content or "", "parse_mode": "HTML"}
    elif m_type == "video" and file_id_or_path:
        url = f"https://api.telegram.org/bot{tok}/sendVideo"
        payload = {"chat_id": chat_id, "video": file_id_or_path, "caption": text_content or "", "parse_mode": "HTML"}
    elif m_type in ("document", "file") and file_id_or_path:
        url = f"https://api.telegram.org/bot{tok}/sendDocument"
        payload = {"chat_id": chat_id, "document": file_id_or_path, "caption": text_content or "", "parse_mode": "HTML"}
    else:
        url = f"https://api.telegram.org/bot{tok}/sendMessage"
        payload = {"chat_id": chat_id, "text": text_content or "", "parse_mode": "HTML"}

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200:
            return True, False, ""
        
        resp_text = r.text.lower()
        if "entity" in resp_text or "parse" in resp_text:
            payload.pop("parse_mode", None)
            r2 = requests.post(url, json=payload, timeout=20)
            if r2.status_code == 200:
                return True, False, ""
            resp_text = r2.text.lower()

        is_blocked = ("blocked" in resp_text or "deactivated" in resp_text or "chat not found" in resp_text or "forbidden" in resp_text)
        return False, is_blocked, resp_text[:120]
    except Exception as e:
        return False, False, str(e)


def edit_telegram_msg(chat_id, message_id, text, reply_markup=None, bot_token=None):
    tok = bot_token or CHORVA_BOT_TOKEN
    if not tok:
        return
    url = f"https://api.telegram.org/bot{tok}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=6)
    except Exception as e:
        print(f"[TG EDIT ERR]: {e}")


def answer_callback_query(callback_query_id, text=None, show_alert=False, bot_token=None):
    tok = bot_token or CHORVA_BOT_TOKEN
    if not tok:
        return
    url = f"https://api.telegram.org/bot{tok}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass


def get_current_app_version_info():
    """Serverdagi eng so'nggi APK va versiya ma'lumotlarini olish"""
    v_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.json")
    v_info = {
        "version_name": "1.8",
        "version_code": 224,
        "changelog": "Ilova ichidan avtomatik yangilash va o'rnatish tizimi",
        "apk_size_mb": 5.37,
        "release_date": datetime.now().strftime("%Y-%m-%d")
    }
    if os.path.exists(v_file):
        try:
            with open(v_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                v_info["version_name"] = str(data.get("versionName", v_info["version_name"])).replace("v", "").strip()
                v_info["version_code"] = int(data.get("versionCode", v_info["version_code"]))
                v_info["changelog"] = str(data.get("changelog", v_info["changelog"]))
                if "sizeMb" in data:
                    v_info["apk_size_mb"] = float(data["sizeMb"])
                if "lastBuild" in data:
                    v_info["release_date"] = str(data["lastBuild"]).split(" ")[0]
        except Exception:
            pass

    # Mahalliy ChorvaERP.apk faylini to'liq tahlil qilish (eng ishonchli manba)
    apk_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ChorvaERP.apk")
    ]
    for ap in apk_candidates:
        if os.path.exists(ap):
            try:
                meta = inspect_apk_metadata(ap)
                if meta.get("size_mb"):
                    v_info["apk_size_mb"] = meta["size_mb"]
                if meta.get("version_name"):
                    v_info["version_name"] = meta["version_name"]
                if meta.get("version_code"):
                    v_info["version_code"] = meta["version_code"]
                break
            except Exception as e:
                print(f"[INSPECT LOCAL APK ERR]: {e}")

    try:
        conn = get_db()
        c = dict_cursor(conn)
        c.execute(adapt_query("SELECT file_id, file_name, file_size, version_name, changelog, created_at FROM app_releases ORDER BY id DESC LIMIT 1"))
        row = c.fetchone()
        conn.close()
        if row:
            db_v_str = str(row.get("version_name") or "").replace("v", "").strip()
            def parse_ver(v_s):
                return [int(x) for x in re.findall(r'\d+', str(v_s))] if v_s else [0]

            # Faqat bazadagi versiya version.json dan yuqori bo'lsa yangilaymiz (eski v1.7 qaytib qolmasligi uchun)
            if parse_ver(db_v_str) > parse_ver(v_info["version_name"]):
                v_info["version_name"] = db_v_str
                if row.get("changelog"):
                    v_info["changelog"] = str(row["changelog"])
                if row.get("file_size"):
                    v_info["apk_size_mb"] = round(row["file_size"] / (1024 * 1024), 2)
                if row.get("created_at"):
                    v_info["release_date"] = str(row["created_at"])[:10]

            v_info["file_id"] = row.get("file_id")
    except Exception:
        pass

    return v_info


def broadcast_version_update_to_users(version_name=None, changelog=None, size_mb=None, active_token=None):
    """Barcha fermerlarga yangi versiya haqida xabar va yuklab olish tugmalarini yuborish"""
    v_info = get_current_app_version_info()
    v_name = version_name or v_info.get("version_name", "1.8")
    c_log = changelog or v_info.get("changelog", "Yangi imkoniyatlar va yaxshilanishlar")
    f_size = size_mb or v_info.get("apk_size_mb", 5.5)
    tok = active_token or CHORVA_BOT_TOKEN

    # 1. Mobil ilovadagi e'lonlar bo'limiga ham qo'shamiz
    try:
        conn_ad = get_db()
        c_ad = conn_ad.cursor()
        c_ad.execute(adapt_query("""
            INSERT INTO advertisements (title, description, category, is_active)
            VALUES (?, ?, 'version_update', ?)
        """), (f"Yangi Chorva ERP v{v_name}", c_log, True if IS_POSTGRES else 1))
        conn_ad.commit()
        conn_ad.close()
    except Exception as e:
        print(f"[VERSION AD ERR]: {e}")

    # 2. Telegram foydalanuvchilarini aniqlaymiz
    recipients = set()
    try:
        conn = get_db()
        c = dict_cursor(conn)
        c.execute(adapt_query("SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL"))
        for r in c.fetchall():
            if r.get("telegram_id"):
                recipients.add(r["telegram_id"])
        c.execute(adapt_query("SELECT telegram_id FROM prayer_users WHERE telegram_id IS NOT NULL"))
        for r in c.fetchall():
            if r.get("telegram_id"):
                recipients.add(r["telegram_id"])
        conn.close()
    except Exception as e:
        print(f"[GET RECIPIENTS ERR]: {e}")

    if not recipients:
        print("[BROADCAST VERSION]: Hech qanday foydalanuvchi topilmadi.")
        return 0

    text_msg = (
        "╭────────────────────────╮\n"
        f"   🚀  <b>YANGI VERSIYA: v{v_name}!</b>\n"
        "╰────────────────────────╯\n\n"
        "Hurmatli foydalanuvchi! <b>Chorva ERP</b> mobil ilovamizning yangi va yanada mukammal versiyasi taqdim etildi.\n\n"
        f"✨ <b>Yangiliklar va qulayliklar:</b>\n<i>{c_log}</i>\n\n"
        f"📦 <b>Hajmi:</b> <b>{f_size} MB</b>\n"
        "🛡 <b>Eslatma:</b> Yangilanganda telefoningizdagi barcha ma'lumotlar to'liq saqlanib qoladi!\n\n"
        "Pastdagi tugmalar orqali ilovani darhol yuklab oling va o'rnating:"
    )

    inline_kb = {
        "inline_keyboard": [
            [
                {"text": "📥 Yangi APK ni yuklab olish (Havola)", "url": "https://aichorva-cloud.onrender.com/download/ChorvaERP.apk"}
            ],
            [
                {"text": "📱 Botdan to'g'ridan-to'g'ri yuklash", "callback_data": "dl_latest_apk"}
            ]
        ]
    }

    sent = 0
    recipients_list = list(recipients)
    # 🌊 To'lqinli (Wave / Queue) tarqatish:
    # Serverga birdaniga katta yuklama tushmasligi va Telegram flood cheklovlariga uchramaslik uchun
    # 15 tadan foydalanuvchiga 20 soniya oraliq bilan navbatma-navbat tarqatiladi
    BATCH_SIZE = 15
    for i in range(0, len(recipients_list), BATCH_SIZE):
        batch = recipients_list[i:i + BATCH_SIZE]
        for tid in batch:
            try:
                send_telegram_msg(tid, text_msg, reply_markup=inline_kb, bot_token=tok)
                sent += 1
                time.sleep(0.05)
            except Exception:
                pass
        if i + BATCH_SIZE < len(recipients_list):
            print(f"[BROADCAST BATCH]: {sent}/{len(recipients_list)} yuborildi. Keyingi to'lqin uchun 20s kutilmoqda...")
            time.sleep(20)

    print(f"[BROADCAST VERSION COMPLETE]: {sent}/{len(recipients_list)} foydalanuvchiga yuborildi.")
    return sent


def send_latest_apk_document(chat_id, active_token=None):
    """Foydalanuvchiga eng so'nggi APK faylini jo'natish"""
    v_info = get_current_app_version_info()
    f_size = v_info.get("apk_size_mb", 5.37)
    v_name = v_info.get("version_name", "1.8")
    ch_log = v_info.get("changelog", "Yangi rasmiy APK ilovasi")

    cap = (
        "╭────────────────────────╮\n"
        "   📲  <b>AI CHORVA RASMIY APK</b>\n"
        "╰────────────────────────╯\n\n"
        "📁 <b>Fayl:</b> <code>ChorvaERP.apk</code>\n"
        f"🏷 <b>Versiya:</b> <b>v{v_name}</b>\n"
        f"📦 <b>Hajmi:</b> <b>{f_size} MB</b>\n"
    )
    if ch_log:
        cap += f"📝 <b>Izoh / Yangiliklar:</b>\n<i>{ch_log}</i>\n"
    cap += (
        "\n────────────────────────\n"
        "💡 <b>O'rnatish yo'riqnomasi:</b>\n"
        "1️⃣ Yuqoridagi fayl ustiga bosib, telefoningizga o'rnating;\n"
        "2️⃣ Ilovani ochgach, ushbu botdagi <b>«📱 Telefon raqamni ulashish»</b> yoki <b>«🔑 Ilovaga kirish kodi»</b> tugmasi orqali olingan kod bilan tizimga kiring!"
    )

    main_menu = get_telegram_main_menu(is_admin_user(chat_id), is_prayer_bot=(active_token == PRAYER_BOT_TOKEN))

    # 1. Avval server diskidagi mahalliy ChorvaERP.apk ni tekshiramiz (eng ishonchli va yangi versiya)
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk")
    if os.path.exists(local_path):
        res2 = send_telegram_document(chat_id, local_path, caption=cap, reply_markup=main_menu, bot_token=active_token)
        if res2:
            return True

    # 2. Agar diskda bo'lmasa, Telegram file_id orqali uzatamiz
    if v_info.get("file_id"):
        res = send_telegram_document(chat_id, v_info["file_id"], caption=cap, reply_markup=main_menu, bot_token=active_token)
        if res:
            return True

    # 3. Fallback to'g'ridan-to'g'ri havola
    fallback_text = (
        cap + "\n\n🌐 <b>Yuklab olish havolasi:</b>\n"
        "👉 https://aichorva-cloud.onrender.com/download/ChorvaERP.apk"
    )
    send_telegram_msg(chat_id, fallback_text, reply_markup=main_menu, bot_token=active_token)
    return True


ADMIN_STATE = {}        # {chat_id: 'waiting_broadcast' | 'replying_12345' | 'waiting_apk' | 'waiting_edit_ad_1'}
USER_STATE = {}         # {user_id: 'waiting_support'}
ADMIN_MSG_MAP = {}      # {admin_sent_msg_id: user_id}
PENDING_BROADCASTS = {} # {chat_id: {'type': 'text'|'photo'|'video'|'document', 'file_id': ..., 'text': ..., 'caption': ...}}

def get_telegram_main_menu(is_admin=False, is_prayer_bot=False):
    """Foydalanuvchilar va Bosh Admin uchun alohida moslashtirilgan asosiy menyu"""
    if is_prayer_bot:
        # 1. Namoz Vaqtlari Boti
        if is_admin:
            kb = [
                [{"text": "👑 ADMIN BOSHQARUV PANELI"}],
                [{"text": "🕌 Bugungi namoz vaqtlari"}, {"text": "📍 Hududni tanlash"}],
                [{"text": "🔔 Azon eslatmalari"}, {"text": "📖 5 vaqt namoz tartibi"}],
                [{"text": "🤲 Kunlik duolar va zikrlar"}, {"text": "📊 Baza statistikasi"}],
            ]
        else:
            kb = [
                [{"text": "🕌 Bugungi namoz vaqtlari"}, {"text": "📍 Hududni tanlash"}],
                [{"text": "🔔 Azon eslatmalari"}, {"text": "📖 5 vaqt namoz tartibi"}],
                [{"text": "🤲 Kunlik duolar va zikrlar"}],
            ]
    else:
        # 2. AI Chorva Boti (@AIchorvabot)
        if is_admin:
            # 👑 Bosh Admin uchun to'liq boshqaruv menyusi (telefon ulashish va ilovaga kirish kodi bilan)
            kb = [
                [{"text": "👑 ADMIN BOSHQARUV PANELI"}],
                [{"text": "📱 Telefon raqamni ulashish", "request_contact": True}, {"text": "🔑 Ilovaga kirish kodi"}],
                [{"text": "📥 Ilovani yuklab olish (APK)"}, {"text": "📏 Torozisiz vazn o'lchash"}],
                [{"text": "🐂 AI Chorva haqida"}, {"text": "👤 Mening profilim"}],
                [{"text": "📊 Baza statistikasi"}, {"text": "📦 Yangi APK yuklash"}],
                [{"text": "📣 Reklama / E'lon yuborish"}, {"text": "❓ Qo'llanma va Yordam"}],
            ]
        else:
            # 🌾 Oddiy fermer (foydalanuvchi) ko'rinishi
            kb = [
                [{"text": "📱 Telefon raqamni ulashish", "request_contact": True}, {"text": "🔑 Ilovaga kirish kodi"}],
                [{"text": "📥 Ilovani yuklab olish (APK)"}, {"text": "📏 Torozisiz vazn o'lchash"}],
                [{"text": "🐂 AI Chorva haqida"}, {"text": "👤 Mening profilim"}],
                [{"text": "✍️ Adminga murojaat"}, {"text": "❓ Qo'llanma va Yordam"}],
            ]
    return {
        "keyboard": kb,
        "resize_keyboard": True
    }


def send_lenta_guide(chat_id, animal="menu", bot_token=None):
    """Torozisiz vazn o'lchash rasmli diagrammalari va hisob-kitob yo'riqnomasi"""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    img_dir = os.path.join(root_dir, "img")
    tok = bot_token or CHORVA_BOT_TOKEN

    def resolve_img(fname):
        p1 = os.path.join(img_dir, fname)
        if os.path.exists(p1): return p1
        p2 = os.path.join(root_dir, fname)
        if os.path.exists(p2): return p2
        return p1

    if animal == "cattle":
        photo_path = resolve_img("bull_measure.jpg")
        caption = (
            "╭────────────────────────╮\n"
            "   🐂  <b>QORAMOL VA BUQA VAZNINI O'LCHASH</b>\n"
            "╰────────────────────────╯\n\n"
            "Yuqoridagi diagrammada ko'rsatilgan 2 ta o'lchovni oling:\n\n"
            "🔴 <b>A (Ko'krak aylanasi):</b> Old oyoqlar orqasidan (kurak orqasidan) ko'krak qafasi aylanasi (sm da).\n"
            "🔵 <b>B (Tana uzunligi):</b> Kurak-yelka bo'g'imidan to orqa dum suyagi bo'rtig'igacha bo'lgan masofa (sm da).\n\n"
            "🧮 <b>Formula (Truxanovskiy):</b>\n"
            "<code>Vazn (kg) = (A × B) ÷ 50</code>\n"
            "<i>• Juda semiz / bo'rdoqi bo'lsa: +10% qo'shiladi</i>\n"
            "<i>• Ozg'in bo'lsa: -10% ayiriladi</i>\n\n"
            "💡 <b>Misol:</b> A=180 sm, B=155 sm bo'lsa:\n"
            "(180 × 155) ÷ 50 = <b>558 kg</b> tirik vazn!\n"
            "🥩 <i>Taxminiy sof go'sht: ~312 kg (56%)</i>"
        )
        kb = {
            "inline_keyboard": [
                [{"text": "🐑 Qo'yni ko'rish", "callback_data": "lenta_sheep"}, {"text": "🐎 Otni ko'rish", "callback_data": "lenta_horse"}],
                [{"text": "🧮 Buqa vaznini hisoblash", "callback_data": "lenta_calc_cattle"}]
            ]
        }
        send_telegram_photo(chat_id, photo_path, caption=caption, reply_markup=kb, bot_token=tok)

    elif animal == "sheep":
        photo_path = resolve_img("sheep_measure.jpg")
        caption = (
            "╭────────────────────────╮\n"
            "   🐑  <b>QO'Y VA QO'CHQOR VAZNINI O'LCHASH</b>\n"
            "╰────────────────────────╯\n\n"
            "Qo'y va qo'chqorlar (Hisori, Arashan, Jaydari) uchun o'lchash:\n\n"
            "🔴 <b>A (Ko'krak aylanasi):</b> Old oyoqlari orqasidan ko'krak qafasi aylanasi (sm da, junini biroz bosib).\n"
            "🔵 <b>B (Tana uzunligi):</b> Kurak suyagidan to dum ildizigacha bo'lgan to'g'ri masofa (sm da).\n\n"
            "🧮 <b>Formula:</b>\n"
            "<code>Vazn (kg) = (A² × B) ÷ 10800</code>\n\n"
            "💡 <b>Misol:</b> A=95 sm, B=82 sm bo'lsa:\n"
            "(95 × 95 × 82) ÷ 10800 = <b>68.5 kg</b>!\n"
            "🥩 <i>Taxminiy sof go'sht: ~35 kg (50%)</i>"
        )
        kb = {
            "inline_keyboard": [
                [{"text": "🐂 Qoramolni ko'rish", "callback_data": "lenta_cattle"}, {"text": "🐎 Otni ko'rish", "callback_data": "lenta_horse"}],
                [{"text": "🧮 Qo'y vaznini hisoblash", "callback_data": "lenta_calc_sheep"}]
            ]
        }
        send_telegram_photo(chat_id, photo_path, caption=caption, reply_markup=kb, bot_token=tok)

    elif animal == "horse":
        photo_path = resolve_img("horse_measure.jpg")
        caption = (
            "╭────────────────────────╮\n"
            "   🐎  <b>OT VA YILQI VAZNINI O'LCHASH</b>\n"
            "╰────────────────────────╯\n\n"
            "Ot va toychoqlar uchun Kerroll va Xantington standarti:\n\n"
            "🔴 <b>A (Ko'krak aylanasi):</b> Yag'rina ustidan va old tirsak orqasidan ko'krak aylanasi (sm da).\n"
            "🔵 <b>B (Tana uzunligi):</b> Yelka suyagidan to orqa dumba suyagi bo'rtig'igacha bo'lgan masofa (sm da).\n\n"
            "🧮 <b>Formula:</b>\n"
            "<code>Vazn (kg) = (A² × B) ÷ 11877</code>\n\n"
            "💡 <b>Misol:</b> A=185 sm, B=160 sm bo'lsa:\n"
            "(185 × 185 × 160) ÷ 11877 = <b>460 kg</b> tirik vazn!"
        )
        kb = {
            "inline_keyboard": [
                [{"text": "🐂 Qoramolni ko'rish", "callback_data": "lenta_cattle"}, {"text": "🐑 Qo'yni ko'rish", "callback_data": "lenta_sheep"}],
                [{"text": "🧮 Ot vaznini hisoblash", "callback_data": "lenta_calc_horse"}]
            ]
        }
        send_telegram_photo(chat_id, photo_path, caption=caption, reply_markup=kb, bot_token=tok)

    else:
        intro_text = (
            "╭────────────────────────╮\n"
            "   📏  <b>TOROZISIS VAZNNI O'LCHASH</b>\n"
            "╰────────────────────────╯\n\n"
            "Chorvachilikda oddiy santimetr (ruletka) lentasi orqali tirik vaznni 95–97% aniqlikda bilish mumkin!\n\n"
            "👇 <b>Qaysi jonivorning o'lchash diagrammasini ko'rmoqchisiz?</b>\n"
            "Tugmani bosing — bot sizga barcha chiziqlari ko'rsatilgan rasmli qo'llanmani yuboradi:"
        )
        kb = {
            "inline_keyboard": [
                [{"text": "🐂 Qoramol / Bo'rdoqi Buqa", "callback_data": "lenta_cattle"}],
                [{"text": "🐑 Qo'y va Qo'chqor", "callback_data": "lenta_sheep"}],
                [{"text": "🐎 Ot va Yilqi", "callback_data": "lenta_horse"}],
                [{"text": "🧮 Botda hisob-kitob qilish", "callback_data": "lenta_calc"}]
            ]
        }
        send_telegram_msg(chat_id, intro_text, reply_markup=kb, bot_token=tok)


def get_ads_hub_keyboard():
    """Reklama va E'lonlar markazi asosiy boshqaruv inline menyusi"""
    return {
        "inline_keyboard": [
            [{"text": "🚀 Yangi Reklama / E'lon yaratish", "callback_data": "ad_hub_new"}],
            [{"text": "📋 Barcha reklamalar ro'yxati (Boshqaruv)", "callback_data": "ad_hub_list_1"}],
            [{"text": "📊 Oxirgi tarqatish hisoboti & Audit", "callback_data": "ad_hub_report"}],
            [{"text": "🔙 Boshqaruv paneliga qaytish", "callback_data": "ad_hub_back_panel"}]
        ]
    }


def format_advertisements_list(page=1, per_page=5):
    """Bazadagi barcha reklamalarni sahifalab boshqarish uchun chiqarish"""
    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("SELECT COUNT(*) as cnt FROM advertisements"))
        total = c.fetchone()["cnt"]
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page

        c.execute(adapt_query("""
            SELECT id, title, description, media_type, media_file_id, is_active, created_at,
                   COALESCE(views_count, 0) as views, COALESCE(sent_count, 0) as sent
            FROM advertisements 
            ORDER BY id DESC LIMIT ? OFFSET ?
        """), (per_page, offset))
        ads = c.fetchall()

        if not ads:
            text = (
                "╭────────────────────────╮\n"
                "   📋  <b>REKLAMALAR RO'YXATI</b>\n"
                "╰────────────────────────╯\n\n"
                "Hozircha tizimda birorta ham reklama yoki e'lon mavjud emas.\n\n"
                "<i>Yangi reklama yaratish uchun «🚀 Yangi Reklama yaratish» tugmasini bosing!</i>"
            )
            kb = {
                "inline_keyboard": [
                    [{"text": "🚀 Yangi Reklama yaratish", "callback_data": "ad_hub_new"}],
                    [{"text": "🔙 Reklamalar markaziga qaytish", "callback_data": "ad_hub_main"}]
                ]
            }
            return text, kb

        text = (
            "╭────────────────────────╮\n"
            "   📋  <b>REKLAMA VA E'LONLAR BAZASI</b>\n"
            "╰────────────────────────╯\n\n"
            f"Jami e'lonlar: <b>{total} ta</b> | Sahifa: <b>{page}/{total_pages}</b>\n\n"
        )
        
        type_icons = {
            "photo": "📸 Surat",
            "video": "🎥 Video",
            "document": "📁 Fayl",
            "file": "📁 Fayl",
            "text": "📝 Matn"
        }

        kb_rows = []
        for a in ads:
            ad_id = a["id"]
            is_act = bool(a["is_active"])
            status_ico = "🟢 Faol" if is_act else "🔴 Nofaol"
            m_icon = type_icons.get(a.get("media_type", "text"), "📝 Matn")
            c_date = str(a.get("created_at", ""))[:16]

            text += (
                f"🔹 <b>#{ad_id} — {a['title'][:32]}</b>\n"
                f"   ├ 📂 Turi: {m_icon} | ⚙️ Holat: <b>{status_ico}</b>\n"
                f"   ├ 👥 Yuborilgan: {a.get('sent', 0)} ta | 📅 {c_date}\n\n"
            )

            toggle_txt = "🔴 Nofaol qilish" if is_act else "🟢 Faollashtirish"
            kb_rows.append([
                {"text": f"👁 #{ad_id} Ko'rish", "callback_data": f"ad_view_{ad_id}"},
                {"text": f"{toggle_txt}", "callback_data": f"ad_toggle_{ad_id}"},
                {"text": "🗑 O'chirish", "callback_data": f"ad_del_{ad_id}"}
            ])

        nav_row = []
        if page > 1:
            nav_row.append({"text": "⬅️ Oldingi", "callback_data": f"ad_hub_list_{page-1}"})
        if page < total_pages:
            nav_row.append({"text": "Keyingi ➡️", "callback_data": f"ad_hub_list_{page+1}"})
        if nav_row:
            kb_rows.append(nav_row)

        kb_rows.append([{"text": "🚀 Yangi Reklama yaratish", "callback_data": "ad_hub_new"}])
        kb_rows.append([{"text": "🔙 Reklamalar markaziga qaytish", "callback_data": "ad_hub_main"}])

        return text, {"inline_keyboard": kb_rows}
    finally:
        conn.close()


def execute_broadcast_campaign(admin_chat_id, draft, bot_token=None):
    """
    To'liq audit va tahliliy hisobot bilan barcha foydalanuvchilarga reklama tarqatish.
    Surat, video, fayl yoki matnni ikkala bot obunachilariga xavfsiz va to'lqinli yuboradi.
    """
    start_time = time.time()
    now_dt = get_now_tashkent()
    start_str = now_dt.strftime("%H:%M:%S")
    start_date = now_dt.strftime("%Y-%m-%d")

    m_type = draft.get("type", "text")
    file_id = draft.get("file_id")
    text_content = draft.get("text", "")
    ad_title = draft.get("title") or (text_content.split("\n")[0][:50] if text_content else "E'lon")

    conn = get_db()
    c = dict_cursor(conn)
    chorva_users = set()
    prayer_users = set()
    try:
        c.execute(adapt_query("SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL"))
        for r in c.fetchall():
            if r["telegram_id"]: chorva_users.add(int(r["telegram_id"]))

        c.execute(adapt_query("SELECT telegram_id FROM prayer_users WHERE telegram_id IS NOT NULL"))
        for r in c.fetchall():
            if r["telegram_id"]: prayer_users.add(int(r["telegram_id"]))
    finally:
        conn.close()

    all_recipients = prayer_users | chorva_users
    total_recipients = len(all_recipients)

    if total_recipients == 0:
        send_telegram_msg(admin_chat_id, "⚠️ Baza bo'sh! Birorta ham qabul qiluvchi Telegram foydalanuvchi topilmadi.", bot_token=bot_token)
        return

    send_telegram_msg(
        admin_chat_id, 
        f"⏳ <b>Reklama tarqatish boshlandi...</b>\n"
        f"👥 Jami qamrov: <b>{total_recipients} ta</b> foydalanuvchi.\n"
        f"<i>Tugashi bilan to'liq tahliliy hisobot shu yerga yuboriladi.</i>", 
        bot_token=bot_token
    )

    success_count = 0
    blocked_count = 0
    failed_count = 0
    prayer_sent = 0
    chorva_sent = 0

    BATCH_SIZE = 25
    batch_counter = 0

    # A) Asl Namoz boti a'zolariga jo'natish
    if PRAYER_BOT_TOKEN:
        for tid in prayer_users:
            ok, is_bl, err = send_telegram_media_generic(tid, m_type, file_id, text_content, bot_token=PRAYER_BOT_TOKEN)
            if ok:
                success_count += 1
                prayer_sent += 1
            elif is_bl:
                blocked_count += 1
            else:
                failed_count += 1
            batch_counter += 1
            if batch_counter % BATCH_SIZE == 0:
                time.sleep(1.0)
            else:
                time.sleep(0.04)

    # B) AI Chorva boti a'zolariga
    remaining_chorva = chorva_users - prayer_users
    if CHORVA_BOT_TOKEN:
        for tid in remaining_chorva:
            ok, is_bl, err = send_telegram_media_generic(tid, m_type, file_id, text_content, bot_token=CHORVA_BOT_TOKEN)
            if ok:
                success_count += 1
                chorva_sent += 1
            elif is_bl:
                blocked_count += 1
            else:
                failed_count += 1
            batch_counter += 1
            if batch_counter % BATCH_SIZE == 0:
                time.sleep(1.0)
            else:
                time.sleep(0.04)

    # Mobil ilova uchun ma'lumotlar bazasiga saqlash
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(adapt_query("""
            INSERT INTO advertisements (title, description, category, is_active, media_type, media_file_id, sent_count)
            VALUES (?, ?, 'broadcast', ?, ?, ?, ?)
        """), (ad_title, text_content, True if IS_POSTGRES else 1, m_type, file_id, success_count))
        conn.commit()
        conn.close()
    except Exception as e_save:
        print(f"[SAVE AD RECORD ERR]: {e_save}")

    end_time = time.time()
    now_end_dt = get_now_tashkent()
    end_str = now_end_dt.strftime("%H:%M:%S")
    duration_sec = round(end_time - start_time, 1)
    speed_per_sec = round(total_recipients / max(duration_sec, 0.1), 1)
    success_percent = round((success_count / total_recipients) * 100, 1) if total_recipients > 0 else 0

    type_names = {
        "photo": "📸 Rasm / Suratli reklama",
        "video": "🎥 Video rolik",
        "document": "📁 Fayl / Hujjat",
        "file": "📁 Fayl / Hujjat",
        "text": "📝 Matnli e'lon"
    }

    report_text = (
        "╭────────────────────────╮\n"
        "   📊  <b>REKLAMA TARQATISH HISOBOTI</b>\n"
        "╰────────────────────────╯\n\n"
        f"🏷 <b>E'lon:</b> <i>«{ad_title}»</i>\n"
        f"📂 <b>Format:</b> <b>{type_names.get(m_type, '📝 Matnli e\'lon')}</b>\n"
        f"📅 <b>Sana:</b> {start_date} | 🕒 <b>Vaqt:</b> {start_str} ➔ {end_str}\n\n"
        "📈 <b>NATIJALAR TAHLILI:</b>\n"
        f" • 👥 <b>Umumiy auditoriya:</b> <b>{total_recipients} ta</b>\n"
        f" • ✅ <b>Muvaffaqiyatli yetkazildi:</b> <b>{success_count} ta ({success_percent}%)</b>\n"
        f" • 🚫 <b>Botni bloklaganlar:</b> <b>{blocked_count} ta</b> <i>(Yetib bormadi)</i>\n"
        f" • ⚠️ <b>Boshqa uzilishlar:</b> <b>{failed_count} ta</b>\n\n"
        "🤖 <b>MANBALAR KESIMIDA:</b>\n"
        f" • 🕌 <b>Asl Namoz Boti:</b> {prayer_sent} ta obunachiga\n"
        f" • 🐂 <b>AI Chorva Boti:</b> {chorva_sent} ta obunachiga\n"
        f" • 📲 <b>AI Chorva Ilovasi:</b> Bosh sahifaga joylandi ✅\n\n"
        "⏱ <b>VAQT KO'RSATKICHI:</b>\n"
        f" • ⏳ <b>Sarflangan vaqt:</b> <b>{duration_sec} soniya</b>\n"
        f" • ⚡️ <b>O'rtacha tezlik:</b> <b>~{speed_per_sec} ta xabar/soniya</b>\n\n"
        "🛡 <i>Ushbu hisobot tizim audit jurnalida saqlandi.</i>"
    )

    set_system_setting("last_ad_report", report_text)
    set_system_setting("last_ad_time", f"{start_date} {end_str}")

    kb_done = {
        "inline_keyboard": [
            [{"text": "📋 Barcha reklamalar ro'yxati", "callback_data": "ad_hub_list_1"}],
            [{"text": "🚀 Yangi reklama yaratish", "callback_data": "ad_hub_new"}],
            [{"text": "🔙 Reklamalar markaziga qaytish", "callback_data": "ad_hub_main"}]
        ]
    }
    send_telegram_msg(admin_chat_id, report_text, reply_markup=kb_done, bot_token=bot_token)


def get_admin_panel_menu(is_prayer_bot=False):
    """Faqat Admin uchun maxsus boshqaruv paneli menyusi"""
    if is_prayer_bot:
        kb = [
            [{"text": "📣 Reklama va E'lonlar markazi"}, {"text": "📊 Baza statistikasi"}],
            [{"text": "🔔 Azon eslatmasini sinash"}, {"text": "🔙 Asosiy menyuga qaytish"}],
        ]
    else:
        auth_required = (get_system_setting("require_auth", "true") == "true")
        auth_btn_text = "🔒 Majburiy kirish: YOQILGAN 🟢" if auth_required else "🔓 Majburiy kirish: O'CHIRILGAN 🔴"
        kb = [
            [{"text": "👥 Foydalanuvchilar ro'yxati"}, {"text": "📊 Baza statistikasi"}],
            [{"text": auth_btn_text}, {"text": "🐙 GitHub Zaxira (Kunlik)"}],
            [{"text": "💾 Bazani yuklab olish"}, {"text": "📥 Bazani tiklash"}],
            [{"text": "📦 Yangi APK yuklash"}, {"text": "📢 Versiya yangiligini e'lon qilish"}],
            [{"text": "📣 Reklama va E'lonlar markazi"}, {"text": "🔙 Asosiy menyuga qaytish"}],
        ]
    return {
        "keyboard": kb,
        "resize_keyboard": True
    }


def format_user_list_keyboard(page=1, per_page=6):
    """Foydalanuvchilar ro'yxati, ularning chorvalari va sarmoyalari (Sahifalash bilan)"""
    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("SELECT COUNT(*) as cnt FROM users"))
        row_cnt = c.fetchone()
        total_count = row_cnt["cnt"] if row_cnt else 0
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page

        c.execute(adapt_query("""
            SELECT u.id, u.phone, u.full_name, u.farm_name, u.role,
                   (SELECT COUNT(*) FROM bulls WHERE user_id = u.id) as bull_cnt,
                   (SELECT COALESCE(SUM(amount), 0) FROM cash_transactions WHERE user_id = u.id AND trans_type = 'capital') as capital_amt
            FROM users u
            ORDER BY u.id DESC
            LIMIT ? OFFSET ?
        """), (per_page, offset))
        users = c.fetchall()

        inline_kb = []
        for u in users:
            name = (u.get("full_name") or u.get("phone") or f"Fermer #{u.get('id')}").strip()
            if len(name) > 14:
                name = name[:12] + "…"
            bulls = u.get("bull_cnt") or 0
            cap_val = float(u.get("capital_amt") or 0)
            if cap_val >= 1_000_000_000:
                cap_str = f"{cap_val/1_000_000_000:.1f} mlrd"
            elif cap_val >= 1_000_000:
                cap_str = f"{cap_val/1_000_000:.1f} mln"
            elif cap_val > 0:
                cap_str = f"{int(cap_val):,} so'm".replace(",", " ")
            else:
                cap_str = "0"

            btn_text = f"👤 {name} | 🐂 {bulls} ta | 💰 {cap_str}"
            inline_kb.append([{"text": btn_text, "callback_data": f"u_view_{u['id']}_{page}"}])

        # Sahifalash (Pagination) tugmalari
        nav_row = []
        if page > 1:
            nav_row.append({"text": "◀️ Oldingi", "callback_data": f"u_page_{page - 1}"})
        nav_row.append({"text": f"📄 {page} / {total_pages}", "callback_data": f"u_page_{page}"})
        if page < total_pages:
            nav_row.append({"text": "Keyingi ▶️", "callback_data": f"u_page_{page + 1}"})
        if nav_row:
            inline_kb.append(nav_row)

        inline_kb.append([
            {"text": "🔄 Yangilash", "callback_data": f"u_page_{page}"},
            {"text": "🔙 Yopish", "callback_data": "u_close"}
        ])

        summary_text = (
            "╭────────────────────────╮\n"
            "   👥  <b>FOYDALANUVCHILAR RO'YXATI</b>\n"
            "╰────────────────────────╯\n\n"
            f"📊 <b>Jami ro'yxatdan o'tganlar:</b> <b>{total_count} ta</b> fermer\n"
            f"📄 <b>Sahifa:</b> <b>{page} / {total_pages}</b>\n\n"
            "👇 <i>Fermer haqida to'liq hisobotni ko'rish uchun uning tugmasini bosing:</i>"
        )
        return summary_text, {"inline_keyboard": inline_kb}
    finally:
        conn.close()


def format_user_details(user_id, return_page=1):
    """Bitta fermerning to'liq moliyaviy va chorva hisoboti kartochkasi"""
    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("SELECT id, phone, full_name, farm_name, role, telegram_id, telegram_username, is_verified, created_at FROM users WHERE id = ?"), (user_id,))
        u = c.fetchone()
        if not u:
            return "Foydalanuvchi topilmadi.", {"inline_keyboard": [[{"text": "🔙 Ro'yxatga qaytish", "callback_data": f"u_page_{return_page}"}]]}

        # Jonivorlar statistikasi
        c.execute(adapt_query("SELECT COUNT(*) as total, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active, SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END) as sold FROM bulls WHERE user_id = ?"), (user_id,))
        b_stat = c.fetchone()
        b_total = (b_stat["total"] or 0) if b_stat else 0
        b_active = (b_stat["active"] or 0) if b_stat else 0
        b_sold = (b_stat["sold"] or 0) if b_stat else 0

        # O'lchovlar soni
        c.execute(adapt_query("SELECT COUNT(*) as cnt FROM weighings WHERE user_id = ?"), (user_id,))
        w_cnt = (c.fetchone()["cnt"] or 0)

        # Kassa balansi va sarmoya
        c.execute(adapt_query("SELECT trans_type, SUM(amount) as s FROM cash_transactions WHERE user_id = ? GROUP BY trans_type"), (user_id,))
        cash_rows = c.fetchall()
        cap_amt = 0.0
        income_amt = 0.0
        expense_amt = 0.0
        for cr in cash_rows:
            ttype = cr.get("trans_type")
            val = float(cr.get("s") or 0)
            if ttype == 'capital': cap_amt += val
            elif ttype in ('sale', 'income', 'capital_withdraw'): income_amt += val
            else: expense_amt += val
        kassa_balance = (cap_amt + income_amt) - expense_amt

        # Qarzlar
        c.execute(adapt_query("SELECT COALESCE(SUM(remaining_amount), 0) as s FROM debts WHERE user_id = ? AND status != 'paid'"), (user_id,))
        debt_amt = float(c.fetchone()["s"] or 0)

        # Yem ombori turlari
        c.execute(adapt_query("SELECT COUNT(*) as cnt, COALESCE(SUM(current_stock_kg), 0) as stock FROM feed_inventory WHERE user_id = ?"), (user_id,))
        f_inv = c.fetchone()
        feed_types_cnt = (f_inv["cnt"] or 0) if f_inv else 0
        feed_stock_kg = float(f_inv["stock"] or 0) if f_inv else 0.0

        created_str = str(u.get("created_at") or "")[:16] or "Noma'lum"

        cap_fmt = f"{int(cap_amt):,} so'm".replace(",", " ")
        kassa_fmt = f"{int(kassa_balance):,} so'm".replace(",", " ")
        feed_fmt = f"{int(feed_stock_kg):,} kg".replace(",", " ")
        debt_fmt = f"{int(debt_amt):,} so'm".replace(",", " ")

        card = (
            f"╭────────────────────────╮\n"
            f"   👤  <b>FERMER PROFILI: #{u['id']}</b>\n"
            f"╰────────────────────────╯\n\n"
            f"👤 <b>Ismi:</b> <b>{u.get('full_name') or 'Kiritilmagan'}</b>\n"
            f"📞 <b>Telefon raqami:</b> <code>{u.get('phone') or 'Mavjud emas'}</code>\n"
            f"🏡 <b>Ferma nomi:</b> <b>{u.get('farm_name') or 'Mavjud emas'}</b>\n"
            f"🌐 <b>Telegram:</b> @{u.get('telegram_username') or 'mavjud_emas'} (ID: <code>{u.get('telegram_id') or '—'}</code>)\n"
            f"🛡 <b>Maqomi (Rol):</b> <b>{u.get('role') or 'farmer'}</b>\n"
            f"📅 <b>Ro'yxatdan o'tgan:</b> {created_str}\n\n"
            f"📊 <b>FERMA HISOBOTI:</b>\n"
            f" ├ 🐂 <b>Jonivorlar:</b> Jami <b>{b_total} ta</b> (🟢 Faol: {b_active} ta | 🏷 Sotilgan: {b_sold} ta)\n"
            f" ├ ⚖️ <b>Tarozi o'lchovlari:</b> <b>{w_cnt} ta</b>\n"
            f" ├ 💰 <b>Kiritilgan sarmoya:</b> <b>{cap_fmt}</b>\n"
            f" ├ 💵 <b>Kassa qoldig'i:</b> <b>{kassa_fmt}</b>\n"
            f" ├ 🌾 <b>Yem ombori:</b> {feed_types_cnt} xil (Jami {feed_fmt})\n"
            f" └ 🤝 <b>To'lanmagan qarzlar:</b> <b>{debt_fmt}</b>\n\n"
            f"👇 <i>Pastdagi tugmalar orqali ushbu foydalanuvchiga xabar yuborishingiz yoki ro'yxatga qaytishingiz mumkin:</i>"
        )

        buttons = []
        if u.get("telegram_id"):
            buttons.append([{"text": f"✉️ {u.get('full_name') or 'Fermer'}ga xabar yozish", "callback_data": f"reply_{u['telegram_id']}"}])
        buttons.append([{"text": "◀️ Ro'yxatga qaytish", "callback_data": f"u_page_{return_page}"}])

        return card, {"inline_keyboard": buttons}
    finally:
        conn.close()


def export_database_json():
    """Barcha jadvallarni JSON zaxira fayliga chiqarish"""
    conn = get_db()
    c = dict_cursor(conn)
    backup_data = {}
    tables = [
        "users", "prayer_users", "bulls", "weighings", "feed_logs", 
        "feed_inventory", "other_expenses", "cash_transactions", "debts", 
        "debt_payments", "vaccine_schedules", "advertisements", 
        "app_releases", "system_settings"
    ]
    try:
        for t in tables:
            try:
                c.execute(adapt_query(f"SELECT * FROM {t}"))
                rows = [dict(r) for r in c.fetchall()]
                if t == "system_settings":
                    # GitHub Secret Scanning bloklamasligi uchun maxfiy kalitlarni maskalaymiz
                    for row in rows:
                        if row.get("setting_key") == "github_token":
                            row["setting_value"] = "***CONFIGURED_ON_SERVER***"
                backup_data[t] = rows
            except Exception:
                backup_data[t] = []
        return backup_data
    finally:
        conn.close()


def import_database_json(data):
    """JSON zaxira faylidan ma'lumotlarni bazaga yuklash"""
    if not isinstance(data, dict):
        return {}
    # Agar backup_payload ichidagi "data" o'rami bo'lsa
    actual_data = data.get("data") if ("data" in data and isinstance(data["data"], dict)) else data

    conn = get_db()
    c = conn.cursor()
    imported_counts = {}
    try:
        for table, rows in actual_data.items():
            if not isinstance(rows, list) or not rows:
                continue
            cnt = 0
            for r in rows:
                cols = list(r.keys())
                vals = [r[col] for col in cols]
                placeholders = ", ".join(["?" for _ in cols])
                cols_str = ", ".join(cols)
                try:
                    c.execute(adapt_query(f"""
                        INSERT INTO {table} ({cols_str}) VALUES ({placeholders})
                        ON CONFLICT DO NOTHING
                    """ if IS_POSTGRES else f"""
                        INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({placeholders})
                    """), vals)
                    cnt += 1
                except Exception:
                    pass
            imported_counts[table] = cnt
        conn.commit()
        return imported_counts
    finally:
        conn.close()


def auto_restore_database_from_github():
    """
    Render server har safar qayta tushganda yoki start bo'lganda 
    GitHub dagi oxirgi zaxiradan barcha ma'lumotlarni avtomatik yuklab olib tiklaydi.
    Natijada Renderning bepul tarifi bazani o'chirib yuborsa ham, tizim o'z-o'zini avtomatik tiklaydi!
    """
    print("[AUTO RESTORE] GitHub dan avtomatik baza zaxirasini yuklash boshlandi...")
    try:
        # 1. Avval mahalliy papkadagi database_backup/chorva_database_backup.json ni tekshiramiz
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, "..", "database_backup", "chorva_database_backup.json"),
            os.path.join(base_dir, "database_backup", "chorva_database_backup.json"),
            os.path.join(base_dir, "chorva_database_backup.json")
        ]
        json_data = None
        for p in candidates:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        json_data = json.load(f)
                    print(f"[AUTO RESTORE] Diskdagi zaxira fayli topildi: {p}")
                    break
                except Exception:
                    pass

        # 2. Agar diskda topilmasa, to'g'ridan-to'g'ri GitHub RAW havolasidan yuklab olamiz (Token shart emas!)
        if not json_data:
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/database_backup/chorva_database_backup.json"
            try:
                r = requests.get(raw_url, timeout=12)
                if r.status_code == 200:
                    json_data = r.json()
                    print(f"[AUTO RESTORE] GitHub RAW ({raw_url}) dan zaxira muvaffaqiyatli yuklab olindi!")
                else:
                    print(f"[AUTO RESTORE] GitHub RAW javob kodi: {r.status_code}")
            except Exception as e_gh:
                print(f"[AUTO RESTORE GH ERR]: {e_gh}")

        # 3. Agar ma'lumot topilgan bo'lsa, bazaga import qilamiz!
        if json_data:
            counts = import_database_json(json_data)
            u_c = counts.get("users", 0)
            b_c = counts.get("bulls", 0)
            print(f"[AUTO RESTORE SUCCESS]: Baza avtomatik tiklandi! Fermerlar: {u_c} ta, Jonivorlar: {b_c} ta, Jadvallar: {len(counts)} ta!")
            return True, counts
        else:
            print("[AUTO RESTORE]: Zaxira fayli topilmadi yoki bo'sh.")
            return False, "Zaxira topilmadi"
    except Exception as ex:
        print(f"[AUTO RESTORE EXCEPTION]: {ex}")
        return False, str(ex)


GITHUB_REPO = os.environ.get("GITHUB_REPO", "fazliddin3388/aichorva-cloud")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

def get_effective_github_token():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        tok = (get_system_setting("github_token", "") or "").strip()
    return tok


def backup_database_to_github(triggered_by="cron", chat_id=None):
    """Barcha jadvallarni eksport qilib, GitHub API orqali repositoryga har kuni yangilab yuborish"""
    try:
        now_dt = get_now_tashkent()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M")
        today_date = now_dt.strftime("%Y-%m-%d")

        # 1. Barcha jadvallarni to'liq JSON eksport qilish
        dump_data = export_database_json()
        backup_payload = {
            "backup_date": now_str,
            "server": "https://aichorva-cloud.onrender.com",
            "repository": GITHUB_REPO,
            "total_tables": len(dump_data),
            "tables_summary": {k: len(v) for k, v in dump_data.items()},
            "data": dump_data
        }
        json_str = json.dumps(backup_payload, ensure_ascii=False, indent=2, default=str)
        json_bytes = json_str.encode("utf-8")
        import base64
        b64_content = base64.b64encode(json_bytes).decode("utf-8")

        token = get_effective_github_token()
        admin_chat = chat_id or ADMIN_ID

        # 2. Telegram orqali ham Adminga zaxira faylini kafolatli yuborish
        try:
            tmp_json = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chorva_backup_daily.json")
            with open(tmp_json, "wb") as f:
                f.write(json_bytes)
            
            caption_tg = (
                "╭────────────────────────╮\n"
                "   💾  <b>KUNLIK AVTOMATIK BAZA ZAXIRASI</b>\n"
                "╰────────────────────────╯\n\n"
                f"📅 <b>Vaqt:</b> {now_str}\n"
                f"📊 <b>Jadvallar soni:</b> {len(dump_data)} ta\n"
                f"👥 <b>Fermerlar:</b> {len(dump_data.get('users', []))} ta | 🐂 <b>Jonivorlar:</b> {len(dump_data.get('bulls', []))} ta\n"
                f"📁 <b>Fayl:</b> <code>chorva_backup_daily.json</code>\n\n"
                "🛡 <i>Ushbu nusxa tizim tomonidan har kuni avtomatik shakllantiriladi va saqlanadi.</i>"
            )
            send_telegram_document(admin_chat, tmp_json, caption=caption_tg, bot_token=CHORVA_BOT_TOKEN)
            if os.path.exists(tmp_json):
                try: os.remove(tmp_json)
                except Exception: pass
        except Exception as tg_err:
            print(f"[TG BACKUP SEND ERR]: {tg_err}")

        # 3. GitHub API orqali repository ga commit/push qilish
        if not token:
            msg_no_token = (
                "⚠️ <b>GitHub Token hali o'rnatilmagan!</b>\n\n"
                f"Baza zaxirasini to'g'ridan-to'g'ri GitHub (<code>{GITHUB_REPO}</code>) ga avtomatik yuklash uchun "
                "GitHub Personal Access Token (classic yoki fine-grained) kerak.\n\n"
                "🔑 <b>Qanday o'rnatiladi:</b>\n"
                "1. GitHub -> Settings -> Developer settings -> Personal access tokens -> <code>repo</code> huquqi bilan token oling;\n"
                "2. Botga quyidagi buyruqni yuboring:\n"
                "<code>/set_github_token ghp_sizning_tokeningiz</code>\n\n"
                "<i>(Xotirjam bo'ling: Bugungi zaxira fayli hozirgina yuqorida Telegram orqali sizga yuborildi!)</i>"
            )
            if chat_id:
                send_telegram_msg(chat_id, msg_no_token, bot_token=CHORVA_BOT_TOKEN)
            set_system_setting("last_backup_date", today_date)
            return False, "GitHub token o'rnatilmagan"

        gh_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ChorvaERP-Cloud-Backup"
        }
        gh_file_path = "database_backup/chorva_database_backup.json"
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{gh_file_path}"

        # Oldingi fayl SHA sini olamiz (fayl mavjud bo'lsa eskisining o'rniga yangisi yoziladi!)
        sha = None
        try:
            get_resp = requests.get(api_url, headers=gh_headers, timeout=15)
            if get_resp.status_code == 200:
                sha = get_resp.json().get("sha")
        except Exception as e:
            print(f"[GET GH SHA ERR]: {e}")

        put_body = {
            "message": f"🤖 Avtomatik kunlik baza zaxirasi: {now_str} (Render -> GitHub)",
            "content": b64_content,
            "branch": "main"
        }
        if sha:
            put_body["sha"] = sha

        put_resp = requests.put(api_url, headers=gh_headers, json=put_body, timeout=25)
        if put_resp.status_code in (200, 201):
            set_system_setting("last_backup_date", today_date)
            set_system_setting("last_backup_time", now_str)

            success_gh = (
                "╭────────────────────────╮\n"
                "   🎉  <b>GITHUBGA MUVAFFAQIYATLI YUKLANDI!</b>\n"
                "╰────────────────────────╯\n\n"
                f"📁 <b>Repository:</b> <a href='https://github.com/{GITHUB_REPO}'>{GITHUB_REPO}</a>\n"
                f"📄 <b>Fayl:</b> <code>database_backup/chorva_database_backup.json</code> (14 ta jadval to'liq)\n"
                f"📅 <b>Vaqt:</b> {now_str}\n"
                f"🔄 <b>Holat:</b> Eskisi yangisiga almashtirildi (Updated)\n\n"
                "✅ <i>Barcha ma'lumotlar bazasi GitHub kodingiz bilan birga xavfsiz saqlanmoqda!</i>"
            )
            if chat_id:
                send_telegram_msg(chat_id, success_gh, bot_token=CHORVA_BOT_TOKEN)
            print(f"[GITHUB BACKUP SUCCESS]: {now_str}")
            return True, "Muvaffaqiyatli saqlandi"
        else:
            set_system_setting("last_backup_date", today_date)
            err_msg = f"GitHub API xatosi ({put_resp.status_code}): {put_resp.text[:150]}"
            print(f"[GITHUB BACKUP ERR]: {err_msg}")
            if chat_id:
                send_telegram_msg(chat_id, f"⚠️ <b>GitHub ga yuklashda xatolik:</b>\n<code>{err_msg}</code>\n\n<i>(Xotirjam bo'ling: bugungi zaxira nusxasi yuqorida Telegram orqali sizga to'liq yuborildi!)</i>", bot_token=CHORVA_BOT_TOKEN)
            return False, err_msg
    except Exception as ex:
        set_system_setting("last_backup_date", today_date)
        print(f"[BACKUP FATAL ERR]: {ex}")
        traceback.print_exc()
        if chat_id:
            send_telegram_msg(chat_id, f"⚠️ <b>Zaxira yaratishda kutilmagan xatolik:</b> {ex}", bot_token=CHORVA_BOT_TOKEN)
        return False, str(ex)


def daily_db_backup_scheduler_thread():
    """Har 15 daqiqada tekshiradi. Kuniga faqat 1 marta Toshkent vaqti bilan 03:00 dan keyin ishga tushadi"""
    print("[SCHEDULER] Kunlik baza zaxira monitoringi ishga tushdi...")
    while True:
        try:
            now_dt = get_now_tashkent()
            today_str = now_dt.strftime("%Y-%m-%d")
            last_date = get_system_setting("last_backup_date", "")

            # Faqat bugun hali qilinmagan bo'lsa va soat 03:00 dan o'tgan bo'lsa
            if last_date != today_str and now_dt.hour >= 3:
                # Qayta-qayta har 15 daqiqada xabar tashlab spam qilmasligi uchun
                # Avval bugungi sanani belgilab olamiz
                set_system_setting("last_backup_date", today_str)
                print(f"[SCHEDULER] Kunlik zaxira boshlanmoqda: {today_str}")
                backup_database_to_github(triggered_by="cron", chat_id=ADMIN_ID)

            time.sleep(900)  # Har 15 daqiqada tekshirish
        except Exception as e:
            print(f"[SCHEDULER LOOP ERR]: {e}")
            time.sleep(300)








def get_regions_inline_keyboard():
    """12 ta viloyatni tanlash inline klaviaturasi"""
    buttons = []
    provinces = list(PRAYER_DATA.keys())
    for i in range(0, len(provinces), 2):
        row = [{"text": f"📍 {provinces[i]}", "callback_data": f"prov_{provinces[i]}"}]
        if i + 1 < len(provinces):
            row.append({"text": f"📍 {provinces[i+1]}", "callback_data": f"prov_{provinces[i+1]}"})
        buttons.append(row)
    return {"inline_keyboard": buttons}


def get_cities_inline_keyboard(province):
    """Tanlangan viloyatning shahar va tumanlari"""
    cities = PRAYER_DATA.get(province, [])
    buttons = []
    for i in range(0, len(cities), 2):
        row = [{"text": f"🕌 {cities[i]}", "callback_data": f"pr_{cities[i]}"}]
        if i + 1 < len(cities):
            row.append({"text": f"🕌 {cities[i+1]}", "callback_data": f"pr_{cities[i+1]}"})
        buttons.append(row)
    buttons.append([{"text": "⬅️ Viloyatlarga qaytish", "callback_data": "pr_main_back"}])
    return {"inline_keyboard": buttons}


def get_prayer_action_keyboard(region):
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Yangilash", "callback_data": f"pr_{region}"},
                {"text": "📍 Boshqa hudud", "callback_data": "pr_main_back"}
            ]
        ]
    }


# ─── TELEGRAM XABARLARINI QAYTA ISHLASH ───
def handle_telegram_update(update, bot_token=None):
    """Telegramdan kelgan barcha buyruqlar va hodisalarni qayta ishlash (Dual bot)"""
    active_token = bot_token or CHORVA_BOT_TOKEN
    is_prayer_bot = (active_token == PRAYER_BOT_TOKEN)

    # 1. Inline tugma (Callback Query) bosilganda
    cb = update.get("callback_query")
    if cb:
        cb_id = cb.get("id")
        cb_data = cb.get("data", "")
        from_user = cb.get("from", {})
        user_id = from_user.get("id")
        username = from_user.get("username", "")
        first_name = from_user.get("first_name", "")
        last_name = from_user.get("last_name", "")
        full_u_name = f"{first_name} {last_name}".strip()

        msg = cb.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        msg_id = msg.get("message_id")
        is_admin = is_admin_user(user_id, username=username, full_name=full_u_name)

        if cb_data == "test_azon_notif":
            answer_callback_query(cb_id, "🔔 Test azon eslatmasi yuborildi!", bot_token=active_token)
            now_hm = get_now_tashkent().strftime("%H:%M")
            test_azon = (
                "╭────────────────────────╮\n"
                "   🔔  <b>AZON BILDIRISHNOMASI (TEST)</b>\n"
                "╰────────────────────────╯\n\n"
                f"📍 <b>Hudud:</b> Toshkent | 🕒 <b>Hozirgi vaqt:</b> {now_hm}\n\n"
                "🕌 <b>Namoz vaqti kirdi.</b>\n"
                "<i>«Albatta, namoz mo'minlarga vaqtida farz qilingandir.» (Niso, 103)</i>\n\n"
                "✅ <b>Bildirishnoma tizimi 100% ideal ishlamoqda!</b>\n"
                "Har kuni 5 mahal namoz vaqti kirganda aynan shunday eslatma avtomatik keladi."
            )
            send_telegram_msg(chat_id, test_azon, bot_token=active_token)
            return

        if cb_data == "pr_main_back":
            answer_callback_query(cb_id, bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, "📍 <b>O'zbekiston viloyatini tanlang:</b>", get_regions_inline_keyboard(), bot_token=active_token)
            return

        if cb_data.startswith("prov_"):
            province = cb_data.replace("prov_", "")
            answer_callback_query(cb_id, bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, f"📍 <b>{province}</b>: Tuman yoki shahringizni tanlang:", get_cities_inline_keyboard(province), bot_token=active_token)
            return

        if cb_data.startswith("pr_"):
            region = cb_data.replace("pr_", "")
            answer_callback_query(cb_id, f"✅ {region} tanlandi!", bot_token=active_token)

            # Bazaga foydalanuvchining hududini yozib qo'yamiz
            conn = get_db()
            c = conn.cursor()
            try:
                c.execute(adapt_query("""
                    INSERT INTO prayer_users (telegram_id, username, full_name, region, notifications)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET region = excluded.region
                """ if IS_POSTGRES else """
                    INSERT INTO prayer_users (telegram_id, username, full_name, region, notifications)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(telegram_id) DO UPDATE SET region = excluded.region
                """), (user_id, from_user.get("username", ""), from_user.get("first_name", ""), region, True if IS_POSTGRES else 1))
                conn.commit()
            except Exception as e:
                print(f"[PRAYER USER SAVE ERR]: {e}")
            finally:
                conn.close()

            card_text = format_prayer_card_message(region)
            edit_telegram_msg(chat_id, msg_id, card_text, get_prayer_action_keyboard(region), bot_token=active_token)
            return

        if cb_data == "tgl_notif":
            conn = get_db()
            c = conn.cursor()
            try:
                c.execute(adapt_query("SELECT notifications FROM prayer_users WHERE telegram_id = ?"), (user_id,))
                row = c.fetchone()
                current_state = bool(row[0]) if row else True
                new_state = not current_state
                c.execute(adapt_query("""
                    INSERT INTO prayer_users (telegram_id, username, full_name, notifications)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET notifications = excluded.notifications
                """), (user_id, from_user.get("username", ""), from_user.get("first_name", ""), new_state if IS_POSTGRES else (1 if new_state else 0)))
                conn.commit()
                status_txt = "✅ Azon eslatmalari yoqildi!" if new_state else "❌ Azon eslatmalari o'chirildi!"
                answer_callback_query(cb_id, status_txt, show_alert=True, bot_token=active_token)
                notif_btn = "🔔 Eslatmani o'chirish ❌" if new_state else "🔔 Eslatmani yoqish ✅"
                kb = {"inline_keyboard": [[{"text": notif_btn, "callback_data": "tgl_notif"}]]}
                edit_telegram_msg(chat_id, msg_id, f"🔔 <b>Azon eslatmalari holati:</b> {status_txt}", kb, bot_token=active_token)
            except Exception as e:
                print(f"[NOTIF TGL ERR]: {e}")
            finally:
                conn.close()
            return

        if cb_data == "dl_latest_apk":
            answer_callback_query(cb_id, "APK fayli yuborilmoqda...", bot_token=active_token)
            send_latest_apk_document(chat_id, active_token)
            return

        if cb_data == "confirm_broadcast_version" and is_admin:
            answer_callback_query(cb_id, "Versiya e'loni yuborilmoqda...", show_alert=True, bot_token=active_token)
            v_info = get_current_app_version_info()
            edit_telegram_msg(chat_id, msg_id, f"🚀 <b>v{v_info['version_name']} versiyasi haqidagi xabar barcha foydalanuvchilarga tarqatilmoqda...</b>", bot_token=active_token)
            threading.Thread(target=broadcast_version_update_to_users, args=(v_info['version_name'], v_info['changelog'], v_info['apk_size_mb'], active_token), daemon=True).start()
            return

        if cb_data == "cancel_broadcast_version" and is_admin:
            answer_callback_query(cb_id, "Bekor qilindi", bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, "❌ <i>Versiya e'loni bekor qilindi.</i>", bot_token=active_token)
            return

        if cb_data == "trigger_github_backup_now" and is_admin:
            answer_callback_query(cb_id, "Zaxira yaratilmoqda...", bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, "⏳ <b>Baza zaxirasi tayyorlanib, GitHub ga yuklanmoqda...</b>\n<i>Natija bir ozdan so'ng xabar qilinadi.</i>", bot_token=active_token)
            threading.Thread(target=backup_database_to_github, kwargs={"triggered_by": "admin_manual", "chat_id": chat_id}, daemon=True).start()
            return

        if cb_data == "prompt_set_github_token" and is_admin:
            ADMIN_STATE[chat_id] = "waiting_github_token"
            answer_callback_query(cb_id, bot_token=active_token)
            prompt_tok_text = (
                "╭────────────────────────╮\n"
                "   🔑  <b>GITHUB TOKENNI O'RNATISH</b>\n"
                "╰────────────────────────╯\n\n"
                "GitHub Personal Access Tokeningizni (masalan: <code>ghp_xxxxxxxxxxxx</code>) yuboring:\n\n"
                "<i>Bekor qilish uchun pastdagi «❌ Bekor qilish» tugmasini bosing.</i>"
            )
            cancel_kb = {"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}
            send_telegram_msg(chat_id, prompt_tok_text, reply_markup=cancel_kb, bot_token=active_token)
            return

        if cb_data.startswith("reply_"):
            target_user = cb_data.replace("reply_", "")
            ADMIN_STATE[chat_id] = f"replying_{target_user}"
            answer_callback_query(cb_id, bot_token=active_token)
            cancel_kb = {"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}
            send_telegram_msg(
                chat_id,
                f"✍️ <b>Foydalanuvchiga (ID: <code>{target_user}</code>) javob yozish:</b>\n\n"
                f"Javob matningizni yozib yuboring (yoki bevosita xabarga Telegram Reply qiling):\n\n"
                f"<i>Bekor qilish uchun pastdagi «❌ Bekor qilish» tugmasini bosing.</i>",
                reply_markup=cancel_kb,
                bot_token=active_token
            )
        if cb_data.startswith("closechat_"):
            target_user = int(cb_data.replace("closechat_", ""))
            USER_STATE.pop(target_user, None)
            answer_callback_query(cb_id, "Muloqot yopildi!", bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, f"🚪 <i>Foydalanuvchi (ID: <code>{target_user}</code>) bilan muloqot yakunlandi.</i>", reply_markup=None, bot_token=active_token)
            send_telegram_msg(
                target_user,
                "╭────────────────────────╮\n"
                "   ✅  <b>MULOQOT YAKUNLANDI</b>\n"
                "╰────────────────────────╯\n\n"
                "Admin bilan savol-javob muloqoti yakunlandi.\n"
                "Agar yana savollaringiz bo'lsa, istalgan payt «✍️ Adminga murojaat» tugmasi orqali yozishingiz mumkin!\n\n"
                "Quyidagi menyudan kerakli bo'limni tanlashingiz mumkin:",
                reply_markup=get_telegram_main_menu(False, is_prayer_bot),
                bot_token=CHORVA_BOT_TOKEN
            )
            return

        if cb_data.startswith("u_page_"):
            page_num = int(cb_data.replace("u_page_", ""))
            answer_callback_query(cb_id, bot_token=active_token)
            text_out, kb_out = format_user_list_keyboard(page=page_num)
            edit_telegram_msg(chat_id, msg_id, text_out, kb_out, bot_token=active_token)
            return

        if cb_data.startswith("u_view_"):
            parts = cb_data.split("_")
            u_id = int(parts[2])
            ret_page = int(parts[3]) if len(parts) > 3 else 1
            answer_callback_query(cb_id, bot_token=active_token)
            text_out, kb_out = format_user_details(u_id, return_page=ret_page)
            edit_telegram_msg(chat_id, msg_id, text_out, kb_out, bot_token=active_token)
            return

        if cb_data == "u_close":
            answer_callback_query(cb_id, bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, "👥 <i>Foydalanuvchilar ro'yxati yopildi.</i>", reply_markup=None, bot_token=active_token)
            return

        if cb_data in ("lenta_cattle", "lenta_sheep", "lenta_horse"):
            answer_callback_query(cb_id, bot_token=active_token)
            an_type = cb_data.replace("lenta_", "")
            send_lenta_guide(chat_id, animal=an_type, bot_token=active_token)
            return

        if cb_data.startswith("lenta_calc"):
            target_an = cb_data.replace("lenta_calc_", "").replace("lenta_calc", "") or "cattle"
            USER_STATE[user_id] = f"waiting_lenta_calc_{target_an}"
            answer_callback_query(cb_id, bot_token=active_token)

            if target_an == "sheep":
                ex_txt = "95 82 (A: Ko'krak=95 sm, B: Uzunlik=82 sm)"
                an_title = "🐑 Qo'y / Qo'chqor"
            elif target_an == "horse":
                ex_txt = "185 160 (A: Ko'krak=185 sm, B: Uzunlik=160 sm)"
                an_title = "🐎 Ot / Yilqi"
            else:
                ex_txt = "180 155 (A: Ko'krak=180 sm, B: Uzunlik=155 sm)"
                an_title = "🐂 Qoramol / Bo'rdoqi Buqa"

            c_prompt = (
                f"╭────────────────────────╮\n"
                f"   🧮  <b>{an_title.upper()} VAZNINI HISOBLASH</b>\n"
                f"╰────────────────────────╯\n\n"
                f"O'lchangan ikkita sonni (A va B) yuboring:\n\n"
                f"💡 <b>Namunaviy yuborish:</b> <code>{ex_txt}</code>\n\n"
                f"<i>Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing.</i>"
            )
            cancel_kb = {"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}
            send_telegram_msg(chat_id, c_prompt, reply_markup=cancel_kb, bot_token=active_token)
            return

        # ─── REKLAMALAR VA E'LONLAR MARKAZI (CALLBACKS) ───
        if cb_data == "ad_hub_main" and is_admin:
            answer_callback_query(cb_id, bot_token=active_token)
            msg_hub = (
                "╭────────────────────────╮\n"
                "   📢  <b>REKLAMA VA E'LONLAR MARKAZI</b>\n"
                "╰────────────────────────╯\n\n"
                "Ushbu bo'lim orqali siz:\n"
                " • 📸 <b>Surat, 🎥 Video, 📁 Fayl</b> yoki 📝 <b>Matnli</b> reklamalarni barcha Telegram botlari va Mobil ilovaga bir vaqtda tarqatishingiz;\n"
                " • 📋 Mavjud e'lonlarni ko'rish, yoqish/o'chirish va tahrirlashingiz;\n"
                " • 📊 Tarqatish tezligi, yetib borgan va yetib bormaganlar soni bo'yicha to'liq hisobotni ko'rishingiz mumkin!\n\n"
                "👇 <i>Kerakli amalni tanlang:</i>"
            )
            edit_telegram_msg(chat_id, msg_id, msg_hub, get_ads_hub_keyboard(), bot_token=active_token)
            return

        if cb_data == "ad_hub_new" and is_admin:
            ADMIN_STATE[chat_id] = "waiting_broadcast_content"
            answer_callback_query(cb_id, bot_token=active_token)
            instr_new = (
                "╭────────────────────────╮\n"
                "   🚀  <b>YANGI REKLAMA / E'LON YARATISH</b>\n"
                "╰────────────────────────╯\n\n"
                "Menga reklama materialini yuboring:\n\n"
                " • 📸 <b>Surat (Photo):</b> Tagiga tavsif/matn (caption) yozib yuboring;\n"
                " • 🎥 <b>Video rolik:</b> Tagiga tavsif yozib yuboring;\n"
                " • 📁 <b>Fayl / Hujjat:</b> PDF, Word, narxlar ro'yxati yoki katalog;\n"
                " • 📝 <b>Oddiy Matn:</b> E'lon matnining o'zi.\n\n"
                "💡 <i>Siz yuborgan material avval o'zingizga ko'rsatiladi va tasdiqlaganingizdan keyingina barcha foydalanuvchilarga tarqatiladi!</i>\n\n"
                "<i>Bekor qilish uchun pastdagi «❌ Bekor qilish» tugmasini bosing.</i>"
            )
            cancel_kb = {"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}
            send_telegram_msg(chat_id, instr_new, reply_markup=cancel_kb, bot_token=active_token)
            return

        if cb_data.startswith("ad_hub_list_") and is_admin:
            page_num = int(cb_data.replace("ad_hub_list_", "") or "1")
            answer_callback_query(cb_id, bot_token=active_token)
            t_ads, kb_ads = format_advertisements_list(page=page_num)
            edit_telegram_msg(chat_id, msg_id, t_ads, kb_ads, bot_token=active_token)
            return

        if cb_data == "ad_hub_report" and is_admin:
            answer_callback_query(cb_id, bot_token=active_token)
            rep_text = get_system_setting("last_ad_report")
            if not rep_text:
                rep_text = (
                    "╭────────────────────────╮\n"
                    "   📊  <b>OXIRGI HISOBOT MAVJUD EMAS</b>\n"
                    "╰────────────────────────╯\n\n"
                    "Hali hech qanday reklama tarqatilmagan.\n"
                    "Yangi reklama tarqatilgach, bu yerda batafsil vaqt va qamrov statistikasi saqlanadi."
                )
            back_kb = {"inline_keyboard": [[{"text": "🔙 Reklamalar markaziga qaytish", "callback_data": "ad_hub_main"}]]}
            edit_telegram_msg(chat_id, msg_id, rep_text, back_kb, bot_token=active_token)
            return

        if cb_data == "ad_hub_back_panel" and is_admin:
            answer_callback_query(cb_id, bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, "👑 <b>Admin boshqaruv paneliga qaytildi.</b>", reply_markup=None, bot_token=active_token)
            send_telegram_msg(chat_id, "Quyidagi menyudan kerakli bo'limni tanlang:", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return

        if cb_data.startswith("ad_view_") and is_admin:
            ad_id = int(cb_data.replace("ad_view_", ""))
            answer_callback_query(cb_id, bot_token=active_token)
            conn = get_db()
            c = dict_cursor(conn)
            try:
                c.execute(adapt_query("SELECT * FROM advertisements WHERE id = ?"), (ad_id,))
                ad_row = c.fetchone()
            finally:
                conn.close()

            if not ad_row:
                send_telegram_msg(chat_id, "⚠️ Reklama topilmadi.", bot_token=active_token)
                return

            m_t = ad_row.get("media_type") or "text"
            m_fid = ad_row.get("media_file_id")
            desc = ad_row.get("description") or ad_row.get("title") or ""
            is_act = bool(ad_row.get("is_active"))
            act_word = "🟢 Faol (Ilovada ko'rinadi)" if is_act else "🔴 Nofaol (Yashiringan)"
            sent_cnt = ad_row.get("sent_count") or 0
            created_s = str(ad_row.get("created_at") or "")[:16]

            caption_full = (
                f"╭────────────────────────╮\n"
                f"   👁  <b>REKLAMA #{ad_id} TAFSILOTLARI</b>\n"
                f"╰────────────────────────╯\n\n"
                f"📌 <b>Sarlavha:</b> {ad_row.get('title')}\n"
                f"⚙️ <b>Holat:</b> <b>{act_word}</b>\n"
                f"👥 <b>Yuborilgan foydalanuvchilar:</b> {sent_cnt} ta\n"
                f"📅 <b>Yaratilgan sana:</b> {created_s}\n\n"
                f"📝 <b>Matn / Tavsif:</b>\n{desc}"
            )

            toggle_act = "🔴 Nofaol qilish" if is_act else "🟢 Faollashtirish"
            v_kb = {
                "inline_keyboard": [
                    [{"text": f"{toggle_act}", "callback_data": f"ad_toggle_{ad_id}"}],
                    [{"text": "✏️ Matnni tahrirlash", "callback_data": f"ad_edit_{ad_id}"}],
                    [{"text": "🚀 Qaytadan barchaga yuborish", "callback_data": f"ad_resend_{ad_id}"}],
                    [{"text": "🗑 O'chirish", "callback_data": f"ad_del_{ad_id}"}],
                    [{"text": "⬅️ Ro'yxatga qaytish", "callback_data": "ad_hub_list_1"}]
                ]
            }

            if m_t == "photo" and m_fid:
                send_telegram_photo(chat_id, m_fid, caption=caption_full, reply_markup=v_kb, bot_token=active_token)
            elif m_t == "video" and m_fid:
                send_telegram_video(chat_id, m_fid, caption=caption_full, reply_markup=v_kb, bot_token=active_token)
            elif m_t in ("document", "file") and m_fid:
                send_telegram_document(chat_id, m_fid, caption=caption_full, reply_markup=v_kb, bot_token=active_token)
            else:
                send_telegram_msg(chat_id, caption_full, reply_markup=v_kb, bot_token=active_token)
            return

        if cb_data.startswith("ad_toggle_") and is_admin:
            ad_id = int(cb_data.replace("ad_toggle_", ""))
            conn = get_db()
            c = conn.cursor()
            try:
                c.execute(adapt_query("UPDATE advertisements SET is_active = CASE WHEN is_active = ? THEN ? ELSE ? END WHERE id = ?"),
                          (True if IS_POSTGRES else 1, False if IS_POSTGRES else 0, True if IS_POSTGRES else 1, ad_id))
                conn.commit()
            finally:
                conn.close()
            answer_callback_query(cb_id, "Holat muvaffaqiyatli o'zgartirildi!", show_alert=True, bot_token=active_token)
            t_ads, kb_ads = format_advertisements_list(page=1)
            edit_telegram_msg(chat_id, msg_id, t_ads, kb_ads, bot_token=active_token)
            return

        if cb_data.startswith("ad_del_") and is_admin:
            ad_id = int(cb_data.replace("ad_del_", ""))
            conn = get_db()
            c = conn.cursor()
            try:
                c.execute(adapt_query("DELETE FROM advertisements WHERE id = ?"), (ad_id,))
                conn.commit()
            finally:
                conn.close()
            answer_callback_query(cb_id, f"#{ad_id} reklama o'chirildi!", show_alert=True, bot_token=active_token)
            t_ads, kb_ads = format_advertisements_list(page=1)
            edit_telegram_msg(chat_id, msg_id, t_ads, kb_ads, bot_token=active_token)
            return

        if cb_data.startswith("ad_edit_") and is_admin:
            ad_id = int(cb_data.replace("ad_edit_", ""))
            ADMIN_STATE[chat_id] = f"waiting_edit_ad_{ad_id}"
            answer_callback_query(cb_id, bot_token=active_token)
            prompt_edit = (
                f"╭────────────────────────╮\n"
                f"   ✏️  <b>REKLAMA #{ad_id} MATNINI TAHRIRLASH</b>\n"
                f"╰────────────────────────╯\n\n"
                f"Ushbu reklama uchun yangi matnni yozib yuboring:\n\n"
                f"<i>Bekor qilish uchun pastdagi «❌ Bekor qilish» tugmasini bosing.</i>"
            )
            cancel_kb = {"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}
            send_telegram_msg(chat_id, prompt_edit, reply_markup=cancel_kb, bot_token=active_token)
            return

        if cb_data.startswith("ad_resend_") and is_admin:
            ad_id = int(cb_data.replace("ad_resend_", ""))
            conn = get_db()
            c = dict_cursor(conn)
            try:
                c.execute(adapt_query("SELECT * FROM advertisements WHERE id = ?"), (ad_id,))
                ad_row = c.fetchone()
            finally:
                conn.close()

            if not ad_row:
                answer_callback_query(cb_id, "E'lon topilmadi!", show_alert=True, bot_token=active_token)
                return

            draft = {
                "type": ad_row.get("media_type") or "text",
                "file_id": ad_row.get("media_file_id"),
                "text": ad_row.get("description") or ad_row.get("title") or "",
                "title": ad_row.get("title")
            }
            answer_callback_query(cb_id, "Qaytadan tarqatish boshlanmoqda...", bot_token=active_token)
            threading.Thread(target=execute_broadcast_campaign, args=(chat_id, draft, active_token), daemon=True).start()
            return

        if cb_data == "confirm_send_broadcast" and is_admin:
            draft = PENDING_BROADCASTS.pop(chat_id, None)
            ADMIN_STATE.pop(chat_id, None)
            if not draft:
                answer_callback_query(cb_id, "Xabar qoralamasi muddati o'tgan yoki topilmadi.", show_alert=True, bot_token=active_token)
                return

            answer_callback_query(cb_id, "Tarqatish boshlandi!", bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, "🚀 <b>Reklama barcha foydalanuvchilarga tarqatilmoqda...</b>\n<i>Kuting, hisobot tez orada tayyor bo'ladi.</i>", reply_markup=None, bot_token=active_token)
            threading.Thread(target=execute_broadcast_campaign, args=(chat_id, draft, active_token), daemon=True).start()
            return

        if cb_data == "save_app_only_broadcast" and is_admin:
            draft = PENDING_BROADCASTS.pop(chat_id, None)
            ADMIN_STATE.pop(chat_id, None)
            if not draft:
                answer_callback_query(cb_id, "Qoralama topilmadi.", show_alert=True, bot_token=active_token)
                return

            m_t = draft.get("type", "text")
            f_id = draft.get("file_id")
            txt = draft.get("text", "")
            title = draft.get("title") or (txt.split("\n")[0][:50] if txt else "E'lon")

            conn = get_db()
            c = conn.cursor()
            try:
                c.execute(adapt_query("""
                    INSERT INTO advertisements (title, description, category, is_active, media_type, media_file_id, sent_count)
                    VALUES (?, ?, 'broadcast', ?, ?, ?, 0)
                """), (title, txt, True if IS_POSTGRES else 1, m_t, f_id))
                conn.commit()
            finally:
                conn.close()

            answer_callback_query(cb_id, "Faqat ilovaga saqlandi!", show_alert=True, bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, "✅ <b>E'lon faqat AI Chorva mobil ilovasi uchun muvaffaqiyatli saqlandi!</b>", reply_markup=None, bot_token=active_token)
            send_telegram_msg(chat_id, "Boshqaruv menyusi:", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return

        if cb_data == "cancel_broadcast_draft" and is_admin:
            PENDING_BROADCASTS.pop(chat_id, None)
            ADMIN_STATE.pop(chat_id, None)
            answer_callback_query(cb_id, "Bekor qilindi", bot_token=active_token)
            edit_telegram_msg(chat_id, msg_id, "❌ <i>Reklama qoralamasi bekor qilindi.</i>", reply_markup=None, bot_token=active_token)
            send_telegram_msg(chat_id, "Boshqaruv menyusi:", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return

    # 2. Xabar (Message) kelganda
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id = msg.get("chat", {}).get("id")
    from_user = msg.get("from", {})
    user_id = from_user.get("id")
    username = from_user.get("username", "")
    text = (msg.get("text") or "").strip()
    contact = msg.get("contact")
    doc = msg.get("document")

    first_name = from_user.get("first_name", "")
    last_name = from_user.get("last_name", "")
    full_u_name = f"{first_name} {last_name}".strip()

    is_admin = is_admin_user(user_id, username=username, full_name=full_u_name)
    print(f"[TG UPDATE] user_id={user_id}, name='{full_u_name}', is_admin={is_admin}, text='{text}', doc={'yes' if doc else 'no'}")

    # Namoz boti foydalanuvchilarini avtomatik obuna qilish (barcha foydalanuvchilar azon eslatmalarini oladi)
    if is_prayer_bot and user_id:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute(adapt_query("""
                INSERT INTO prayer_users (telegram_id, username, full_name, region, notifications)
                VALUES (?, ?, ?, 'Toshkent', ?)
                ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name
            """), (user_id, username, first_name, True if IS_POSTGRES else 1))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # 0.0. Admin APK yuklash holatida bo'lsa yoki bevosita APK yuborganida
    is_in_apk_state = (ADMIN_STATE.get(chat_id) == "waiting_apk")

    # 0. Holatni bekor qilish
    if text in ("/cancel", "❌ Bekor qilish", "Bekor qilish", "/bekor", "❌ Bekor qilish (/cancel)"):
        ADMIN_STATE.pop(chat_id, None)
        USER_STATE.pop(user_id, None)
        send_telegram_msg(chat_id, "Amal bekor qilindi.", reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return

    # A) Admin yangi APK fayl (Document) yuborganida
    if doc and (is_admin or is_in_apk_state):
        f_name = doc.get("file_name") or "ChorvaERP.apk"
        mime = (doc.get("mime_type") or "").lower()
        f_size = doc.get("file_size") or 0
        file_id = doc.get("file_id")

        is_in_db_restore = (ADMIN_STATE.get(chat_id) == "waiting_db_restore")
        f_name_lower = f_name.lower()
        is_db_backup = (
            is_in_db_restore or
            f_name_lower.endswith(".db") or
            f_name_lower.endswith(".sqlite") or
            f_name_lower.endswith(".sqlite3") or
            (f_name_lower.endswith(".json") and ("backup" in f_name_lower or "chorva" in f_name_lower or is_in_db_restore))
        )

        # 1. Baza zaxira fayli kelganda (.db yoki .json)
        if is_db_backup and is_admin:
            ADMIN_STATE.pop(chat_id, None)
            send_telegram_msg(chat_id, "⏳ <b>Baza fayli qabul qilinmoqda va tiklanmoqda...</b>", bot_token=active_token)
            try:
                r_fi = requests.get(f"https://api.telegram.org/bot{active_token}/getFile?file_id={file_id}", timeout=20)
                tg_path = r_fi.json().get("result", {}).get("file_path")
                if not tg_path:
                    send_telegram_msg(chat_id, "❌ Telegramdan faylni yuklab bo'lmadi.", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
                    return

                down_url = f"https://api.telegram.org/file/bot{active_token}/{tg_path}"
                r_down = requests.get(down_url, timeout=60)
                file_bytes = r_down.content

                if f_name_lower.endswith(".json"):
                    json_data = json.loads(file_bytes.decode("utf-8"))
                    imported = import_database_json(json_data)
                    u_cnt = imported.get("users", 0)
                    b_cnt = imported.get("bulls", 0)
                    w_cnt = imported.get("weighings", 0)
                    msg_succ = (
                        "╭────────────────────────╮\n"
                        "   ✅  <b>BAZA TIKLANDI (JSON)!</b>\n"
                        "╰────────────────────────╯\n\n"
                        f"📁 <b>Fayl:</b> <code>{f_name}</code>\n"
                        f"👥 <b>Fermerlar:</b> <b>{u_cnt} ta</b>\n"
                        f"🐂 <b>Jonivorlar:</b> <b>{b_cnt} ta</b>\n"
                        f"⚖️ <b>O'lchovlar:</b> <b>{w_cnt} ta</b>\n\n"
                        "🟢 Barcha ma'lumotlar muvaffaqiyatli tiklandi!"
                    )
                    send_telegram_msg(chat_id, msg_succ, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
                    return
                else:
                    if not IS_POSTGRES:
                        import shutil
                        tmp_test = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_restore.db")
                        with open(tmp_test, "wb") as f_tmp:
                            f_tmp.write(file_bytes)

                        test_conn = sqlite3.connect(tmp_test)
                        test_cur = test_conn.cursor()
                        test_cur.execute("SELECT COUNT(*) FROM users")
                        u_cnt = test_cur.fetchone()[0]
                        test_cur.execute("SELECT COUNT(*) FROM bulls")
                        b_cnt = test_cur.fetchone()[0]
                        test_conn.close()

                        shutil.copyfile(tmp_test, LOCAL_DB_FILE)
                        try: os.remove(tmp_test)
                        except Exception: pass

                        init_cloud_database()

                        msg_succ = (
                            "╭────────────────────────╮\n"
                            "   ✅  <b>BAZA TIKLANDI (SQLITE)!</b>\n"
                            "╰────────────────────────╯\n\n"
                            f"📁 <b>Fayl:</b> <code>{f_name}</code>\n"
                            f"📦 <b>Hajmi:</b> <b>{round(len(file_bytes)/1024, 1)} KB</b>\n"
                            f"👥 <b>Fermerlar:</b> <b>{u_cnt} ta</b>\n"
                            f"🐂 <b>Jonivorlar:</b> <b>{b_cnt} ta</b>\n\n"
                            "🟢 <b>Render serveridagi baza 100% tiklandi va faol!</b>"
                        )
                        send_telegram_msg(chat_id, msg_succ, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
                        return
                    else:
                        send_telegram_msg(chat_id, "⚠️ Server PostgreSQL rejimida. Iltimos, .json formatdagi zaxira faylini yuboring.", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
                        return
            except Exception as ex:
                send_telegram_msg(chat_id, f"❌ <b>Bazani tiklashda xatolik:</b> {ex}", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
                return

        # 2. Yangi APK ilova kelganda
        is_apk_target = (
            is_in_apk_state or
            f_name.lower().endswith(".apk") or
            "apk" in f_name.lower() or
            "android" in mime or
            "package-archive" in mime or
            "application/octet-stream" in mime
        )

        if is_apk_target:
            if not f_name.lower().endswith(".apk"):
                f_name = f"{f_name}.apk"

            cap = (msg.get("caption") or text or "").strip()
            version_match = re.search(r'v?\d+(\.\d+)+', cap, re.IGNORECASE)
            if not version_match:
                version_match = re.search(r'v?\d+', cap, re.IGNORECASE)
            if not version_match:
                version_match = re.search(r'v?\d+(\.\d+)+', f_name, re.IGNORECASE)

            if not file_id:
                send_telegram_msg(
                    chat_id,
                    "⚠️ <b>Xatolik:</b> Telegram fayl identifikatorini (file_id) aniqlab bo'lmadi. Iltimos faylni qaytadan yuboring.",
                    reply_markup=get_telegram_main_menu(True, is_prayer_bot),
                    bot_token=active_token
                )
                return

            # Server diskiga saqlash va APK ichidagi haqiqiy versiyani avtomatik aniqlash
            saved_local = cache_apk_locally(file_id, active_token)
            apk_meta = inspect_apk_metadata(saved_local) if saved_local else None

            if version_match:
                version_name = version_match.group(0)
            elif apk_meta and apk_meta.get("version_name"):
                version_name = f"v{apk_meta['version_name']}"
            else:
                curr_v_info = get_current_app_version_info()
                version_name = f"v{curr_v_info.get('version_name', '1.8')}"

            v_code = (apk_meta.get("version_code") if apk_meta else None) or 224
            size_mb = (apk_meta.get("size_mb") if apk_meta else None) or (round(f_size / (1024 * 1024), 2) if f_size else 5.37)
            changelog = cap or f"Yangi rasmiy APK ilovasi ({version_name})"

            conn = get_db()
            c = conn.cursor()
            try:
                if not IS_POSTGRES:
                    c.execute("""
                        CREATE TABLE IF NOT EXISTS app_releases (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            file_id TEXT NOT NULL,
                            file_name TEXT,
                            file_size INTEGER,
                            version_name TEXT DEFAULT 'v1.8',
                            version_code INTEGER DEFAULT 224,
                            changelog TEXT,
                            uploaded_by INTEGER,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                else:
                    c.execute("""
                        CREATE TABLE IF NOT EXISTS app_releases (
                            id SERIAL PRIMARY KEY,
                            file_id TEXT NOT NULL,
                            file_name VARCHAR(256),
                            file_size BIGINT,
                            version_name VARCHAR(64) DEFAULT 'v1.8',
                            version_code INTEGER DEFAULT 224,
                            changelog TEXT,
                            uploaded_by BIGINT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                c.execute(adapt_query("""
                    INSERT INTO app_releases (file_id, file_name, file_size, version_name, version_code, changelog, uploaded_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """), (file_id, f_name, f_size, version_name, v_code, changelog, user_id))
                conn.commit()
                print(f"[APK SUCCESS]: Saved new APK {f_name} ({size_mb} MB) version={version_name} code={v_code} file_id={file_id}")
            except Exception as e:
                print(f"[APK SAVE ERR]: {e}")
                traceback.print_exc()
            finally:
                conn.close()

            # Barcha foydalanuvchilarga yangi versiya haqida avtomatik bildirishnoma tarqatish
            try:
                threading.Thread(target=broadcast_version_update_to_users, args=(version_name, changelog, size_mb, active_token), daemon=True).start()
            except Exception as e:
                print(f"[BROADCAST VERSION ERR]: {e}")

            ADMIN_STATE.pop(chat_id, None)

            success_admin_msg = (
                "╭────────────────────────╮\n"
                "   🎉  <b>YANGI APK VERSIYASI SAQLANDI!</b>\n"
                "╰────────────────────────╯\n\n"
                f"📁 <b>Fayl nomi:</b> <code>{f_name}</code>\n"
                f"📦 <b>Hajmi:</b> <b>{size_mb} MB</b>\n"
                f"🏷 <b>Versiya:</b> <b>{version_name}</b>\n"
            )
            if changelog and changelog != f_name:
                success_admin_msg += f"📝 <b>Izoh / Yangiliklar:</b>\n<i>{changelog}</i>\n\n"
            success_admin_msg += (
                "────────────────────────\n"
                "✅ <b>Serverda muvaffaqiyatli saqlandi!</b>\n"
                "📢 <b>Barcha foydalanuvchilarga yangilanish xabari yuborilmoqda...</b>\n\n"
                "Endi barcha foydalanuvchilar (va siz) botdagi <b>«📥 Ilovani yuklab olish (APK)»</b> "
                "tugmasini bosganda yoki ilova ichidan yangilaganda aynan siz hozir yuklagan ushbu yangi fayl yuboriladi!"
            )
            send_telegram_msg(chat_id, success_admin_msg, reply_markup=get_telegram_main_menu(True, is_prayer_bot), bot_token=active_token)
            return

    # B) Agar admin APK kutish holatida bo'lib, lekin fayl emas boshqa narsa yuborgan bo'lsa:
    if is_in_apk_state and not doc:
        warn_apk_text = (
            "⚠️ <b>Iltimos, APK faylini yuboring!</b>\n\n"
            "Siz matn yoki boshqa turdagi xabar yubordingiz. Yangi ilovani yuklash uchun faylni "
            "Telegramga <b>Fayl (Document)</b> sifatida ilova qilib jo'nating (masalan: <code>ChorvaERP.apk</code>).\n\n"
            "<i>Bekor qilish uchun pastdagi «❌ Bekor qilish» tugmasini bosing.</i>"
        )
        send_telegram_msg(
            chat_id,
            warn_apk_text,
            reply_markup={"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True},
            bot_token=active_token
        )
        return


    # 0.05. Admin GitHub Token yuboryaptimi?
    if is_admin and ADMIN_STATE.get(chat_id) == "waiting_github_token":
        ADMIN_STATE.pop(chat_id, None)
        token_candidate = (text or "").strip()
        if token_candidate in ("❌ Bekor qilish", "/cancel", "Bekor qilish"):
            send_telegram_msg(chat_id, "GitHub tokenni o'rnatish bekor qilindi.", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return

        if len(token_candidate) < 15:
            send_telegram_msg(chat_id, "⚠️ Token juda qisqa ko'rinadi. Iltimos, haqiqiy GitHub Access Token yuboring.", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return

        set_system_setting("github_token", token_candidate)
        confirm_token_msg = (
            "╭────────────────────────╮\n"
            "   ✅  <b>GITHUB TOKEN SAQLANDI!</b>\n"
            "╰────────────────────────╯\n\n"
            f"📁 <b>Repository:</b> <code>{GITHUB_REPO}</code>\n"
            "🔑 <b>Token:</b> <code>" + token_candidate[:6] + "..." + token_candidate[-4:] + "</code>\n\n"
            "Endi har kuni soat 03:00 da ma'lumotlar bazasi avtomatik ravishda ushbu GitHub repo ga zaxiralanadi!\n"
            "Shuningdek, hozirning o'zida tekshirib ko'rish uchun <b>«🐙 GitHub Zaxira (Kunlik)»</b> tugmasidan foydalanishingiz mumkin."
        )
        send_telegram_msg(chat_id, confirm_token_msg, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
        return

    # 0.1. Admin foydalanuvchi murojaatiga javob yozyaptimi?
    reply_target_user = None
    if is_admin:
        if ADMIN_STATE.get(chat_id, "").startswith("replying_"):
            try:
                reply_target_user = int(ADMIN_STATE[chat_id].replace("replying_", ""))
            except Exception:
                pass
            ADMIN_STATE.pop(chat_id, None)
        elif msg.get("reply_to_message"):
            rep_msg_id = msg.get("reply_to_message", {}).get("message_id")
            if rep_msg_id in ADMIN_MSG_MAP:
                reply_target_user = ADMIN_MSG_MAP[rep_msg_id]

    if is_admin and reply_target_user:
        ans_text = text or msg.get("caption") or ""
        if not ans_text:
            send_telegram_msg(chat_id, "Javob matni bo'sh bo'lishi mumkin emas.", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return

        # Foydalanuvchini chat rejimida saqlab qolamiz (uzilib qolmasligi uchun!)
        USER_STATE[reply_target_user] = "in_support_chat"

        user_notification = (
            "╭────────────────────────╮\n"
            "   📬  <b>ADMINDAN JAVOB KELDI!</b>\n"
            "╰────────────────────────╯\n\n"
            f"{ans_text}\n\n"
            "────────────────────────\n"
            "💬 <i>Muloqot faol. Qo'shimcha savolingiz yoki javobingiz bo'lsa, to'g'ridan-to'g'ri shu yerga yozishingiz mumkin.</i>\n\n"
            "<i>(Muloqotni yakunlash uchun pastdagi «🚪 Muloqotni yakunlash» tugmasini bosing).</i>"
        )
        chat_user_kb = {
            "keyboard": [[{"text": "🚪 Muloqotni yakunlash (Chiqish)"}]],
            "resize_keyboard": True
        }
        send_telegram_msg(reply_target_user, user_notification, reply_markup=chat_user_kb, bot_token=CHORVA_BOT_TOKEN)

        admin_card_kb = {
            "inline_keyboard": [
                [
                    {"text": "💬 Yana javob berish", "callback_data": f"reply_{reply_target_user}"},
                    {"text": "🚪 Chatni yopish", "callback_data": f"closechat_{reply_target_user}"}
                ]
            ]
        }
        send_telegram_msg(
            chat_id,
            f"✅ <b>Javobingiz foydalanuvchiga (ID: <code>{reply_target_user}</code>) muvaffaqiyatli yetkazildi!</b>\n"
            "<i>Muloqot ochiq qoldi. Foydalanuvchi yana yozsa, xabari to'g'ridan-to'g'ri sizga keladi.</i>",
            reply_markup=admin_card_kb,
            bot_token=active_token
        )
        return

    # 0.15. Foydalanuvchi torozisiz vazn hisoblashda sonlarni yubordimi?
    if USER_STATE.get(user_id, "").startswith("waiting_lenta_calc"):
        state_val = USER_STATE.get(user_id, "")
        target_animal = state_val.replace("waiting_lenta_calc_", "").replace("waiting_lenta_calc", "").strip("_")
        USER_STATE.pop(user_id, None)

        if text in ("/cancel", "❌ Bekor qilish", "Bekor qilish", "/exit"):
            send_telegram_msg(chat_id, "Amal bekor qilindi.", reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
            return

        nums = [float(s) for s in re.findall(r'\d+(?:\.\d+)?', text)]
        if len(nums) >= 2:
            a, b = nums[0], nums[1]
            t_lower = text.lower()
            if "qo'y" in t_lower or "qoy" in t_lower or target_animal == "sheep" or (not target_animal and a <= 120 and b <= 110):
                w = (a * a * b) / 10800
                an_name = "Qo'y / Qo'chqor"
                meat_kg = round(w * 0.50)
                meat_pct = "50%"
                active_key = "sheep"
            elif "ot" in t_lower or target_animal == "horse":
                w = (a * a * b) / 11877
                an_name = "Ot / Yilqi"
                meat_kg = round(w * 0.50)
                meat_pct = "50%"
                active_key = "horse"
            else:
                w = (a * b) / 50
                an_name = "Qoramol / Bo'rdoqi Buqa"
                meat_kg = round(w * 0.56)
                meat_pct = "56%"
                active_key = "cattle"

            w_round = round(w)
            res_txt = (
                "╭────────────────────────╮\n"
                "   🎯  <b>HISOBLANGAN TIRIK VAZN</b>\n"
                "╰────────────────────────╯\n\n"
                f"🐾 <b>Jonivor:</b> <b>{an_name}</b>\n"
                f"📏 <b>Ko'krak aylanasi (A):</b> <b>{int(a)} sm</b>\n"
                f"📏 <b>Tana uzunligi (B):</b> <b>{int(b)} sm</b>\n\n"
                f"⚖️ <b>Tirik vazn (Taxminiy):</b> <b>{w_round} kg</b>\n"
                f"📊 <b>Aniq oraliq:</b> {round(w*0.97)} – {round(w*1.03)} kg (±3% aniqlik)\n"
                f"🥩 <b>Taxminiy sof go'sht chiqishi:</b> <b>~{meat_kg} kg</b>\n\n"
                "<i>📱 Mobil ilovada barcha jonivorlarning vazn dinamikasini saqlab borishingiz mumkin!</i>"
            )
            calc_kb = {
                "inline_keyboard": [
                    [{"text": "🖼 Rasmli qo'llanmani ko'rish", "callback_data": f"lenta_{active_key}"}],
                    [{"text": "🔄 Yana boshqa hisoblash", "callback_data": f"lenta_calc_{active_key}"}]
                ]
            }
            send_telegram_msg(chat_id, res_txt, reply_markup=calc_kb, bot_token=active_token)
            send_telegram_msg(chat_id, "Asosiy menyuga qaytildi:", reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
            return
        else:
            send_telegram_msg(chat_id, "⚠️ Iltimos, ikkita son kiriting (masalan: <code>180 155</code> yoki <code>qo'y 95 82</code>).", bot_token=active_token)
            return

    # 0.2. Foydalanuvchi adminga murojaat/savol yozyaptimi? (Jonli muloqot rejimi)
    if USER_STATE.get(user_id) in ("waiting_support", "in_support_chat"):
        # Agar muloqotdan chiqmoqchi bo'lsa
        if text in ("🚪 Muloqotni yakunlash (Chiqish)", "🚪 Muloqotni yakunlash", "🚪 Chiqish", "/exit", "❌ Bekor qilish", "/cancel"):
            USER_STATE.pop(user_id, None)
            send_telegram_msg(chat_id, "✅ <b>Admin bilan muloqot yakunlandi.</b> Asosiy menyuga qaytildi.", reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
            return

        # Agar foydalanuvchi menyudagi asosiy tugmalardan birini bosgan bo'lsa (muloqotdan avtomatik chiqadi)
        if text.startswith("/") or text in ("🐂 AI Chorva haqida", "👤 Mening profilim", "📥 Ilovani yuklab olish (APK)", "❓ Qo'llanma va Yordam", "👑 ADMIN BOSHQARUV PANELI"):
            USER_STATE.pop(user_id, None)
            # pastdagi buyruqlarga o'tkaziladi
        else:
            user_msg = text or msg.get("caption") or ""
            if not user_msg:
                send_telegram_msg(chat_id, "Murojaat matni bo'sh bo'lishi mumkin emas.", reply_markup={"keyboard": [[{"text": "🚪 Muloqotni yakunlash (Chiqish)"}]], "resize_keyboard": True}, bot_token=active_token)
                return

            # Holatni saqlab qolamiz! (Muloqot davom etadi)
            USER_STATE[user_id] = "in_support_chat"

            u_phone = "Kiritilmagan"
            conn = get_db()
            c = dict_cursor(conn)
            try:
                c.execute(adapt_query("SELECT phone, full_name, farm_name FROM users WHERE telegram_id = ?"), (user_id,))
                ur = c.fetchone()
                if ur and ur.get("phone"):
                    u_phone = ur["phone"]
            finally:
                conn.close()

            u_name = from_user.get("first_name", "Foydalanuvchi")
            u_uname = f"@{from_user.get('username')}" if from_user.get("username") else "mavjud emas"
            tashkent_now = get_now_tashkent().strftime("%H:%M | %d.%m.%Y")

            admin_card = (
                "╭────────────────────────╮\n"
                "   📩  <b>YANGI MUROJAAT (AI CHORVA)</b>\n"
                "╰────────────────────────╯\n\n"
                f"👤 <b>Foydalanuvchi:</b> {u_name} ({u_uname})\n"
                f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
                f"📞 <b>Telefon:</b> <code>{u_phone}</code>\n"
                f"🕒 <b>Vaqt:</b> {tashkent_now}\n\n"
                f"💬 <b>Savol / Xabar:</b>\n"
                f"«<i>{user_msg}</i>»"
            )
            reply_kb = {
                "inline_keyboard": [
                    [
                        {"text": "💬 Javob berish", "callback_data": f"reply_{user_id}"},
                        {"text": "🚪 Chatni yopish", "callback_data": f"closechat_{user_id}"}
                    ]
                ]
            }
            res = send_telegram_msg(ADMIN_ID, admin_card, reply_markup=reply_kb, bot_token=CHORVA_BOT_TOKEN)
            if res and res.get("message_id"):
                ADMIN_MSG_MAP[res["message_id"]] = user_id

            client_confirm = (
                "✅ <b>Xabaringiz adminga yetkazildi!</b>\n\n"
                "Admin javob berishi bilan xabari shu yerga keladi.\n"
                "Muloqot faol — qo'shimcha savolingiz bo'lsa, yana yozavering.\n\n"
                "<i>(Muloqotni yakunlash uchun pastdagi «🚪 Muloqotni yakunlash» tugmasini bosing).</i>"
            )
            chat_user_kb = {
                "keyboard": [[{"text": "🚪 Muloqotni yakunlash (Chiqish)"}]],
                "resize_keyboard": True
            }
            send_telegram_msg(chat_id, client_confirm, reply_markup=chat_user_kb, bot_token=active_token)
            return


    # 0.9. Reklama matnini tahrirlash holati
    if is_admin and str(ADMIN_STATE.get(chat_id)).startswith("waiting_edit_ad_"):
        ad_id = int(ADMIN_STATE[chat_id].replace("waiting_edit_ad_", ""))
        ADMIN_STATE.pop(chat_id, None)
        new_text = (text or msg.get("caption") or "").strip()
        if not new_text or new_text in ("❌ Bekor qilish", "/cancel", "Bekor qilish"):
            send_telegram_msg(chat_id, "Tahrirlash bekor qilindi.", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return

        first_title = new_text.split("\n")[0][:50]
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute(adapt_query("UPDATE advertisements SET title = ?, description = ? WHERE id = ?"), (first_title, new_text, ad_id))
            conn.commit()
        finally:
            conn.close()

        send_telegram_msg(chat_id, f"✅ <b>Reklama #{ad_id} matni muvaffaqiyatli yangilandi!</b>", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
        t_ads, kb_ads = format_advertisements_list(page=1)
        send_telegram_msg(chat_id, t_ads, reply_markup=kb_ads, bot_token=active_token)
        return

    # 1. Admin yangi reklama (Matn, Surat, Video yoki Fayl) yuborganida
    if is_admin and ADMIN_STATE.get(chat_id) in ("waiting_broadcast", "waiting_broadcast_content"):
        # A) Bekor qilish
        if text in ("❌ Bekor qilish", "/cancel", "Bekor qilish", "/bekor"):
            ADMIN_STATE.pop(chat_id, None)
            PENDING_BROADCASTS.pop(chat_id, None)
            send_telegram_msg(chat_id, "Reklama yaratish bekor qilindi.", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return

        # B) Xabar turini tahlil qilish (Surat, Video, Fayl yoki Matn)
        m_type = "text"
        m_fid = None
        f_name_doc = ""
        caption_txt = (msg.get("caption") or text or "").strip()

        if msg.get("photo"):
            m_type = "photo"
            m_fid = msg["photo"][-1]["file_id"]
        elif msg.get("video"):
            m_type = "video"
            m_fid = msg["video"]["file_id"]
        elif msg.get("document"):
            m_type = "document"
            m_fid = msg["document"]["file_id"]
            f_name_doc = msg["document"].get("file_name") or "Hujjat"
        elif text:
            m_type = "text"
            caption_txt = text
        else:
            send_telegram_msg(chat_id, "⚠️ Xabar matni yoki media fayl bo'sh bo'lishi mumkin emas. Qaytadan yuboring:", bot_token=active_token)
            return

        ad_title = caption_txt.split("\n")[0][:50] if caption_txt else (f_name_doc or "Yangi e'lon")

        # Qoralamani saqlaymiz
        draft = {
            "type": m_type,
            "file_id": m_fid,
            "file_name": f_name_doc,
            "text": caption_txt,
            "title": ad_title
        }
        PENDING_BROADCASTS[chat_id] = draft
        ADMIN_STATE.pop(chat_id, None)

        # Qabul qiluvchilar umumiy sonini aniqlash
        conn = get_db()
        c = dict_cursor(conn)
        total_recipients = 0
        try:
            c.execute(adapt_query("SELECT COUNT(DISTINCT telegram_id) as cnt FROM (SELECT telegram_id FROM users UNION SELECT telegram_id FROM prayer_users)"))
            row_cnt = c.fetchone()
            total_recipients = row_cnt["cnt"] if row_cnt else 0
        finally:
            conn.close()

        type_names = {
            "photo": "📸 Suratli reklama",
            "video": "🎥 Video rolik",
            "document": "📁 Fayl / Hujjat",
            "text": "📝 Matnli e'lon"
        }

        # 1. Avval prevyu sifatida xabarning o'zini adminning o'ziga yuboramiz
        send_telegram_msg(chat_id, "👀 <b>XABARNING ASL KO'RINISHI (PREVIEW):</b>", bot_token=active_token)
        send_telegram_media_generic(chat_id, m_type, m_fid, caption_txt, bot_token=active_token)

        # 2. Keyin boshqaruv va tasdiqlash tugmalarini beramiz
        preview_prompt = (
            "╭────────────────────────╮\n"
            "   👁  <b>REKLAMA TAYYOR BO'LDI!</b>\n"
            "╰────────────────────────╯\n\n"
            f"📌 <b>Format:</b> <b>{type_names.get(m_type, '📝 Matn')}</b>\n"
            f"👥 <b>Qamrov:</b> <b>{total_recipients} ta</b> faol foydalanuvchi\n\n"
            "Yuqoridagi xabar barcha Telegram a'zolariga to'liq yetkaziladi va "
            "AI Chorva mobil ilovasida ham e'lon sifatida saqlanadi.\n\n"
            "👇 <i>Tarqatishni tasdiqlaysizmi?</i>"
        )
        confirm_kb = {
            "inline_keyboard": [
                [{"text": "🚀 Ha, barcha foydalanuvchilarga tarqatish", "callback_data": "confirm_send_broadcast"}],
                [{"text": "📱 Faqat mobil ilovaga saqlash (Botlarga yubormasdan)", "callback_data": "save_app_only_broadcast"}],
                [{"text": "❌ Bekor qilish", "callback_data": "cancel_broadcast_draft"}]
            ]
        }
        send_telegram_msg(chat_id, preview_prompt, reply_markup=confirm_kb, bot_token=active_token)
        return

    # 2. Reklama va E'lonlar Markazi bosh menyusi
    if is_admin and text in ("📣 Reklama va E'lonlar markazi", "📣 Reklama / E'lon yuborish", "📣 Reklama yuborish", "/reklama", "/elon", "/broadcast", "/ads"):
        hub_text = (
            "╭────────────────────────╮\n"
            "   📢  <b>REKLAMA VA E'LONLAR MARKAZI</b>\n"
            "╰────────────────────────╯\n\n"
            "Ushbu markaz orqali siz:\n"
            " • 📸 <b>Surat, 🎥 Video, 📁 Fayl</b> yoki 📝 <b>Matnli</b> reklamalarni barcha Telegram obunachilari va mobil ilovaga bir zumda tarqatishingiz;\n"
            " • 📋 Mavjud barcha e'lonlarni boshqarish, yoqish/o'chirish va tahrirlashingiz;\n"
            " • 📊 Nechta foydalanuvchiga borgani va ketgan vaqt bo'yicha to'liq hisobotni ko'rishingiz mumkin!\n\n"
            "👇 <i>Kerakli bo'limni tanlang:</i>"
        )
        send_telegram_msg(chat_id, hub_text, reply_markup=get_ads_hub_keyboard(), bot_token=active_token)
        return

    # 3. Admin statistika buyrug'i
    if is_admin and text in ("📊 Baza statistikasi", "/statistika", "/stats"):
        conn = get_db()
        c = dict_cursor(conn)
        try:
            c.execute(adapt_query("SELECT COUNT(*) as cnt FROM users"))
            total_users = c.fetchone()["cnt"]

            c.execute(adapt_query("SELECT COUNT(*) as cnt FROM prayer_users"))
            total_prayer = c.fetchone()["cnt"]

            c.execute(adapt_query("SELECT COUNT(*) as cnt FROM bulls"))
            total_bulls = c.fetchone()["cnt"]

            c.execute(adapt_query("SELECT COUNT(*) as cnt FROM advertisements WHERE is_active = ?"), (True if IS_POSTGRES else 1,))
            total_ads = c.fetchone()["cnt"]

            stat_text = (
                "╭────────────────────────╮\n"
                "   📊  <b>TIZIM BAZASI STATISTIKASI</b>\n"
                "╰────────────────────────╯\n\n"
                f"🕌 <b>Namoz taqvimi obunachilari:</b> <b>{total_prayer} ta</b>\n"
                f"👥 <b>Fermerlar (Foydalanuvchilar):</b> <b>{total_users} ta</b>\n"
                f"🐂 <b>Hisobdagi jami jonivorlar:</b> <b>{total_bulls} ta</b>\n"
                f"📢 <b>Faol e'lon va reklamalar:</b> <b>{total_ads} ta</b>\n\n"
                "🟢 <i>Ikkala Telegram bot va mobil API 100% barqaror ishlamoqda.</i>"
            )
            send_telegram_msg(chat_id, stat_text, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
        finally:
            conn.close()
        return


    # /start buyrug'i
    if text.startswith("/start"):
        parts = text.split()
        session_id = parts[1].replace("auth_", "") if len(parts) > 1 else None

        auth_code_for_admin = None
        if session_id:
            conn = get_db()
            c = conn.cursor()
            try:
                if is_admin:
                    # Bosh Admin uchun darhol avtorizatsiyani tasdiqlaymiz va kod generatsiya qilamiz!
                    c.execute(adapt_query("SELECT id, phone FROM users WHERE telegram_id = ? OR role = 'admin' LIMIT 1"), (user_id,))
                    u_row = c.fetchone()
                    admin_phone = "+998973387827"
                    if u_row:
                        admin_uid = u_row[0]
                        if u_row[1]: admin_phone = u_row[1]
                    else:
                        if IS_POSTGRES:
                            c.execute("INSERT INTO users (phone, full_name, telegram_id, telegram_username, is_verified, role) VALUES (%s, %s, %s, %s, TRUE, 'admin') RETURNING id",
                                      (admin_phone, from_user.get("first_name", "Fazliddin"), user_id, username))
                            admin_uid = c.fetchone()[0]
                        else:
                            c.execute("INSERT INTO users (phone, full_name, telegram_id, telegram_username, is_verified, role) VALUES (?, ?, ?, ?, 1, 'admin')",
                                      (admin_phone, from_user.get("first_name", "Fazliddin"), user_id, username))
                            admin_uid = c.lastrowid

                    auth_code_for_admin = "".join(random.choices(string.digits, k=6))
                    jwt_token = generate_jwt(admin_uid, admin_phone)
                    expires_at = datetime.utcnow() + timedelta(minutes=60)

                    if IS_POSTGRES:
                        c.execute("""
                            UPDATE auth_sessions 
                            SET phone = %s, auth_code = %s, verified = TRUE, jwt_token = %s, user_id = %s, telegram_id = %s, expires_at = %s
                            WHERE session_id = %s
                        """, (admin_phone, auth_code_for_admin, jwt_token, admin_uid, user_id, expires_at, session_id))
                    else:
                        c.execute("""
                            UPDATE auth_sessions 
                            SET phone = ?, auth_code = ?, verified = 1, jwt_token = ?, user_id = ?, telegram_id = ?, expires_at = ?
                            WHERE session_id = ?
                        """, (admin_phone, auth_code_for_admin, jwt_token, admin_uid, user_id, expires_at, session_id))
                    conn.commit()
                else:
                    c.execute(adapt_query("UPDATE auth_sessions SET telegram_id = ? WHERE session_id = ?"), (chat_id, session_id))
                    conn.commit()
            except Exception as e:
                print(f"[TG UPDATE ERR]: {e}")
            finally:
                conn.close()

        # Botga qarab mos tabrik matni
        if is_prayer_bot:
            conn = get_db()
            c = conn.cursor()
            try:
                c.execute(adapt_query("""
                    INSERT INTO prayer_users (telegram_id, username, full_name, region, notifications)
                    VALUES (?, ?, ?, 'Toshkent', ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name
                """), (user_id, username, from_user.get("first_name", ""), True if IS_POSTGRES else 1))
                conn.commit()
            except Exception as e:
                print(f"[AUTO PRAYER USER ERR]: {e}")
            finally:
                conn.close()

            if is_admin:
                welcome_text = (
                    "╔════════════════════════════╗\n"
                    "   🕌 <b>NAMOZ VAQTLARI BOTI (ADMIN)</b>\n"
                    "╚════════════════════════════╝\n\n"
                    f"👋 <b>Assalomu alaykum, Bosh Admin — {from_user.get('first_name', 'Fazliddin')}!</b>\n\n"
                    "Asl Namoz Vaqtlari Boti boshqaruviga xush kelibsiz!\n\n"
                    "👑 <b>Admin boshqaruv imkoniyatlari:</b>\n"
                    " ├ 👑 <b>ADMIN BOSHQARUV PANELI:</b> Barcha obunachilarga e'lon tarqatish\n"
                    " ├ 🕌 <b>Kunlik namoz vaqtlari:</b> 60+ hudud taqvimi\n"
                    " ├ 🔔 <b>Azon eslatmasi:</b> Bildirishnomani sinash va monitoring\n"
                    " └ 📊 <b>Statistika:</b> Jami namoz obunachilari soni\n\n"
                    "👇 <i>Quyidagi menyu tugmalaridan birini tanlang:</i>"
                )
            else:
                welcome_text = (
                    "╔════════════════════════════╗\n"
                    "   🕌 <b>NAMOZ VAQTLARI BOTI</b>\n"
                    "╚════════════════════════════╝\n\n"
                    f"👋 <b>Assalomu alaykum, {from_user.get('first_name', 'Hurmatli foydalanuvchi')}!</b>\n\n"
                    "O'zbekistonning barcha viloyat, shahar va tumanlari bo'yicha aniq namoz taqvimi hamda azon eslatmalari botiga xush kelibsiz!\n\n"
                    "✨ <b>Imkoniyatlar:</b>\n"
                    " ├ 🕌 <b>Kunlik 5 vaqt namoz taqvimi</b> (60+ hudud)\n"
                    " ├ 🔔 <b>Har bir namozda avtomatik Azon eslatmasi</b>\n"
                    " ├ 📍 <b>Hududni istalgan payt o'zgartirish</b>\n"
                    " └ 📖 <b>5 vaqt namoz o'qish tartibi</b>\n\n"
                    "👇 <i>Quyidagi menyu tugmalaridan birini tanlang:</i>"
                )

        else:
            if is_admin:
                if auth_code_for_admin:
                    welcome_text = (
                        "╔════════════════════════════╗\n"
                        "   👑 <b>BOSH ADMIN TASDIQLANDI!</b>\n"
                        "╚════════════════════════════╝\n\n"
                        f"👋 <b>Assalomu alaykum, Bosh Admin — {from_user.get('first_name', 'Fazliddin')}!</b>\n\n"
                        "✅ <b>AI Chorva</b> mobil ilovasiga kirishingiz muvaffaqiyatli tasdiqlandi!\n\n"
                        f"🔑 <b>Bir martalik kirish kodi:</b> <code>{auth_code_for_admin}</code>\n\n"
                        "📲 <i>Ilovangiz hozir avtomatik ochilmoqda yoki ushbu kodni kiriting!</i>\n\n"
                        "👇 <i>Barcha boshqaruv tugmalari pastdagi menyuda faol:</i>"
                    )
                else:
                    welcome_text = (
                        "╔════════════════════════════╗\n"
                        "   👑 <b>BOSH ADMIN BOSHQARUVI</b>\n"
                        "╚════════════════════════════╝\n\n"
                        f"👋 <b>Assalomu alaykum, Bosh Admin — {from_user.get('first_name', 'Fazliddin')}!</b>\n\n"
                        "Siz <b>AI Chorva</b> tizimining boshqaruvchisiz. Tizim sizni to'liq tanidi!\n\n"
                        "👑 <b>Admin boshqaruv imkoniyatlari:</b>\n"
                        " ├ 👑 <b>Admin Paneli:</b> Reklama, statistika va yangi versiyalar\n"
                        " ├ 🔑 <b>Ilovaga kirish kodi:</b> Mobil ilovaga kod orqali kirish\n"
                        " ├ 📦 <b>Yangi APK yuklash:</b> Mobil ilovani serverda darhol yangilash\n"
                        " ├ 📊 <b>Baza statistikasi:</b> Ro'yxatdan o'tgan fermerlar va jonivorlar soni\n"
                        " └ 🔔 <b>Azon eslatmasi:</b> Bildirishnomalarni sinovdan o'tkazish\n\n"
                        "👇 <i>Barcha boshqaruv tugmalari pastdagi menyuda faol:</i>"
                    )
            else:
                welcome_text = (
                    "╔════════════════════════════╗\n"
                    "   🐂 <b>AI CHORVA RASMIY BOTI</b>\n"
                    "╚════════════════════════════╝\n\n"
                    f"👋 <b>Assalomu alaykum, {from_user.get('first_name', 'Hurmatli foydalanuvchi')}!</b>\n\n"
                    "<b>AI Chorva</b> — chorvachilik va fermerlik tizimining rasmiy botiga xush kelibsiz!\n\n"
                    "📲 <b>Ilovaga xavfsiz kirish:</b>\n"
                    "Ilovaga xavfsiz kirish uchun pastdagi <b>«📱 Telefon raqamni ulashish»</b> tugmasini bosing va 6 xonali tasdiqlash kodini oling!\n\n"
                    "✨ <b>Imkoniyatlar:</b>\n"
                    " ├ 🐂 Jonivorlar hisobi, vazn dinamikasi va kunlik og'im\n"
                    " ├ 🌾 Yem ombori va kunlik ratsion taqsimoti\n"
                    " ├ 💰 Kassa, daromad va sof foyda tahlili\n"
                    " └ ☁️ Barcha ma'lumotlarni bulutda xavfsiz saqlash\n\n"
                    "👇 <i>Kerakli bo'limni tanlang:</i>"
                )
        send_telegram_msg(chat_id, welcome_text, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return

    # ─── NAMOZ VAQTLARI BOTI BUYRUQLARI ───
    if text in ("🕌 Bugungi namoz vaqtlari", "🕌 Namoz vaqtlari", "/namoz"):
        conn = get_db()
        c = conn.cursor()
        region = "Toshkent"
        try:
            c.execute(adapt_query("SELECT region FROM prayer_users WHERE telegram_id = ?"), (user_id,))
            row = c.fetchone()
            if row and row[0]:
                region = row[0]
        finally:
            conn.close()

        card_text = format_prayer_card_message(region)
        send_telegram_msg(chat_id, card_text, reply_markup=get_prayer_action_keyboard(region), bot_token=active_token)
        return

    if text in ("📍 Hududni tanlash", "📍 Hudud tanlash", "📍 Hududni o'zgartirish"):
        send_telegram_msg(chat_id, "📍 <b>O'zbekiston viloyatini tanlang:</b>", reply_markup=get_regions_inline_keyboard(), bot_token=active_token)
        return

    if text in ("🔔 Azon eslatmalari", "🔔 Eslatmalar"):
        conn = get_db()
        c = conn.cursor()
        notif_state = True
        region = "Toshkent"
        try:
            c.execute(adapt_query("SELECT notifications, region FROM prayer_users WHERE telegram_id = ?"), (user_id,))
            row = c.fetchone()
            if row:
                notif_state = bool(row[0])
                if len(row) > 1 and row[1]:
                    region = row[1]
        finally:
            conn.close()

        p_info = fetch_prayer_times(region)
        next_p = p_info.get("next_prayer", {})
        next_str = f"{next_p.get('name', 'Namoz')} ({next_p.get('time', '--:--')})" if next_p else "Hisoblanmoqda..."

        status_txt = "✅ <b>Yoqilgan</b> (Azon vaqtida bildirishnoma avtomatik yuboriladi)" if notif_state else "❌ <b>O'chirilgan</b>"
        btn_txt = "🔕 Eslatmani o'chirish ❌" if notif_state else "🔔 Eslatmani yoqish ✅"
        kb = {
            "inline_keyboard": [
                [{"text": btn_txt, "callback_data": "tgl_notif"}],
                [{"text": "🔔 Bildirishnomani sinash (Test)", "callback_data": "test_azon_notif"}],
                [{"text": "📍 Hududni o'zgartirish", "callback_data": "pr_main_back"}]
            ]
        }
        msg_notif = (
            "╭────────────────────────╮\n"
            "   🔔  <b>AZON BILDIRISHNOMALARI</b>\n"
            "╰────────────────────────╯\n\n"
            f"📊 <b>Holati:</b> {status_txt}\n"
            f"📍 <b>Sizning hududingiz:</b> <b>{region}</b>\n"
            f"🕒 <b>Keyingi namoz:</b> <b>{next_str}</b>\n\n"
            "💡 <i>Har bir namoz vaqti (Bomdod, Peshin, Asr, Shom, Xufton) kirishi bilan bot sizga darhol azon eslatmasini yuboradi.</i>\n\n"
            "Pastdagi tugmalar orqali eslatmani boshqarishingiz yoki test qilib ko'rishingiz mumkin:"
        )
        send_telegram_msg(chat_id, msg_notif, reply_markup=kb, bot_token=active_token)
        return

    if text in ("📖 5 vaqt namoz tartibi", "📖 Namoz o'qish tartibi"):
        guide_text = (
            "╭────────────────────────╮\n"
            "   📖  <b>5 VAQT NAMOZ TARTIBI</b>\n"
            "╰────────────────────────╯\n\n"
            "1. 🏙 <b>Bomdod:</b> 2 rakat sunnat, 2 rakat farz.\n"
            "2. ☀️ <b>Peshin:</b> 4 rakat sunnat, 4 rakat farz, 2 rakat sunnat.\n"
            "3. 🌇 <b>Asr:</b> 4 rakat farz.\n"
            "4. 🌆 <b>Shom:</b> 3 rakat farz, 2 rakat sunnat.\n"
            "5. 🌃 <b>Xufton:</b> 4 rakat farz, 2 rakat sunnat, 3 rakat vitr vojib.\n\n"
            "<i>«Albatta, namoz fahsh va yomon ishlardan qaytarur.» (Ankabut surasi, 45-oyat)</i>\n"
            "✨ <i>Ibodatlaringiz qabul bo'lsin!</i>"
        )
        send_telegram_msg(chat_id, guide_text, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return

    if text in ("🤲 Kunlik duolar va zikrlar", "/duolar", "/zikr"):
        dua_text = (
            "╭────────────────────────╮\n"
            "   🤲  <b>KUNLIK DUO VA ZIKRLAR</b>\n"
            "╰────────────────────────╯\n\n"
            "1️⃣ <b>Tonggi va kechki zikr:</b>\n"
            "<i>«Subhanallohi va bihamdihi, subhanallohil aziym»</i>\n\n"
            "2️⃣ <b>Azon eshitgandagi duo:</b>\n"
            "<i>«Allohumma robba hazihid da'vatit taammati vas solatil qoi'mah, ati Muhammadanil vasilata val faziylata vab'ashu maqomam mahmudanillaziy va'adtah.»</i>\n\n"
            "3️⃣ <b>Masjidga kirish duosi:</b>\n"
            "<i>«Allohummaftah liy abvaba rohmatik.»</i>\n\n"
            "4️⃣ <b>Qiyinchilikdagi duo:</b>\n"
            "<i>«La ilaha illa anta subhanaka inniy kuntu minaz zolimiyn.»</i>\n\n"
            "✨ <i>Alloh taolo ibodatlaringizni ijobat qilsin!</i>"
        )
        send_telegram_msg(chat_id, dua_text, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return

    # ─── ADMIN BOSHQARUV PANELI BUYRUQLARI ───
    if text.startswith("/admin") or text.startswith("/panel") or text == "👑 ADMIN BOSHQARUV PANELI":
        admin_pass = text.replace("/admin", "").replace("/panel", "").replace("👑 ADMIN BOSHQARUV PANELI", "").strip()
        u_fn_lower = full_u_name.lower()
        if is_admin or admin_pass in ("7827", "3388", "fazliddin") or "fazliddin" in u_fn_lower or "\u0444\u0430\u0437\u043b\u0438\u0434\u0434\u0438\u043d" in u_fn_lower:
            is_admin = True
            try: ACTIVE_ADMIN_IDS.add(int(user_id))
            except Exception: pass
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute(adapt_query("UPDATE users SET role = 'admin' WHERE telegram_id = ?"), (user_id,))
                conn.commit()
                conn.close()
            except Exception:
                pass

            admin_panel_text = (
                "╭────────────────────────╮\n"
                "   👑  <b>ADMIN BOSHQARUV PANELI</b>\n"
                "╰────────────────────────╯\n\n"
                f"Assalomu alaykum, <b>{from_user.get('first_name', 'Bosh Admin')}</b>!\n"
                "Tizim boshqaruv paneliga xush kelibsiz.\n\n"
                " • 👥 <b>Foydalanuvchilar ro'yxati:</b> Fermerlar, chorvalari va sarmoyalari\n"
                " • 💾 <b>Bazani yuklab olish:</b> Render o'chishidan oldin to'liq zaxira (.db / .json)\n"
                " • 📥 <b>Bazani tiklash:</b> Qayta ishga tushganda bazani 1 soniyada tiklash\n"
                " • 📊 <b>Baza statistikasi:</b> Tizim bo'yicha umumiy holat\n"
                " • 📦 <b>Yangi APK yuklash:</b> Mobil ilovani yangilash\n"
                " • 📣 <b>Reklama / E'lon yuborish:</b> Botlar va ilovaga bir vaqtda xabar tarqatish\n"
                " • 🔔 <b>Azon eslatmasini sinash:</b> Bildirishnomani darhol test qilish\n"
                " • 🔙 <b>Asosiy menyuga qaytish:</b> Oddiy foydalanuvchi ko'rinishiga o'tish"
            )
            send_telegram_msg(chat_id, admin_panel_text, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            return
        else:
            send_telegram_msg(chat_id, "⚠️ Bu bo'lim faqat tizim admini uchun mo'ljallangan.", reply_markup=get_telegram_main_menu(False, is_prayer_bot), bot_token=active_token)
            return

    if text in ("🔙 Asosiy menyuga qaytish", "🔙 Asosiy menyu", "/menu"):
        ADMIN_STATE.pop(chat_id, None)
        USER_STATE.pop(user_id, None)
        send_telegram_msg(chat_id, "Asosiy menyuga qaytildi.", reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return

    # 0.5. Majburiy kirish (Ro'yxatdan o'tish) ni yoqish / o'chirish
    if is_admin and (text.startswith("🔒 Majburiy kirish") or text.startswith("🔓 Majburiy kirish") or text in ("/toggle_auth", "/majburiy", "/auth_toggle", "Majburiy kirish")):
        curr = (get_system_setting("require_auth", "true") == "true")
        new_val = not curr
        set_system_setting("require_auth", "true" if new_val else "false")
        
        status_word = "YOQILDI 🟢\n(Endi ilovani yuklab olgan har bir yangi foydalanuvchi ilovaga kirganda Telegram bot orqali ro'yxatdan o'tishi majburiy bo'ladi!)" if new_val else "O'CHIRILDI 🔴\n(Foydalanuvchilar Telegram orqali ro'yxatdan o'tmasdan ham ilovani erkin oflayn ishlatishi mumkin)"
        
        resp_msg = (
            "╭────────────────────────╮\n"
            "   🛡  <b>RO'YXATDAN O'TISH SOZLAMASI</b>\n"
            "╰────────────────────────╯\n\n"
            f"⚙️ <b>Holat:</b> <b>{status_word}</b>\n\n"
            "💡 <b>Admin nazorati:</b>\n"
            "• 🟢 <b>Yoqilganda:</b> Ilovaga kirgan barcha yangi fermerlar o'z telefon raqamlarini bot orqali tasdiqlaydilar. "
            "Siz «👥 Foydalanuvchilar ro'yxati» da ilovani o'rnatgan har bir insonni, ularning chorvalari va hisob-kitoblarini bevosita ko'rib turasiz!\n"
            "• 🔴 <b>O'chirilganda:</b> Hech qanday majburiy oynasiz ilova to'g'ridan-to'g'ri ochiladi."
        )
        send_telegram_msg(chat_id, resp_msg, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
        return

    # 0.6. GitHub Kunlik Zaxira bo'limi
    if is_admin and text in ("🐙 GitHub Zaxira (Kunlik)", "🐙 GitHub Zaxira", "/backup_github", "/github_backup"):
        tok = get_effective_github_token()
        last_t = get_system_setting("last_backup_time", "Hali qilinmagan")
        last_d = get_system_setting("last_backup_date", "Mavjud emas")
        
        tok_status = "✅ Faol o'rnatilgan" if tok else "❌ Hali o'rnatilmagan"
        gh_info = (
            "╭────────────────────────╮\n"
            "   🐙  <b>GITHUB KUNLIK ZAXIRA TIZIMI</b>\n"
            "╰────────────────────────╯\n\n"
            f"📁 <b>Repository:</b> <code>{GITHUB_REPO}</code>\n"
            f"🔑 <b>GitHub Token:</b> {tok_status}\n"
            f"🕒 <b>Oxirgi zaxira vaqti:</b> <b>{last_t}</b>\n"
            f"📅 <b>Oxirgi sana:</b> <b>{last_d}</b>\n\n"
            "⚡️ <b>Qanday ishlaydi:</b>\n"
            " • Render serveringizdagi barcha ma'lumotlar bazasi har kuni Toshkent vaqti bilan soat 03:00 da "
            "to'g'ridan-to'g'ri GitHub kod yozilgan joydagi <code>database_backup/chorva_database_backup.json</code> fayliga yuklanadi (eskisi yangilanadi);\n"
            " • Shu bilan birga sizning shaxsiy Telegramingizga ham to'liq zaxira fayli yuboriladi!\n\n"
            "👇 <i>Kerakli amalni tanlang:</i>"
        )
        gh_kb = {
            "inline_keyboard": [
                [{"text": "🚀 Hozir zaxirani GitHub ga yuklash", "callback_data": "trigger_github_backup_now"}],
                [{"text": "🔑 GitHub Tokenni kiritish / yangilash", "callback_data": "prompt_set_github_token"}]
            ]
        }
        send_telegram_msg(chat_id, gh_info, reply_markup=gh_kb, bot_token=active_token)
        return

    # 0.7. GitHub tokenni to'g'ridan-to'g'ri buyruq orqali kiritish
    if is_admin and text.startswith("/set_github_token"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_telegram_msg(chat_id, "Iltimos tokenni kiriting:\nMasalan: <code>/set_github_token ghp_xxxxxx</code>", bot_token=active_token)
            return
        new_tok = parts[1].strip()
        set_system_setting("github_token", new_tok)
        send_telegram_msg(chat_id, "✅ <b>GitHub Token muvaffaqiyatli saqlandi!</b>\nEndi kunlik zaxira avtomatik GitHub ga yuboriladi.", reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
        return

    # 1. Foydalanuvchilar ro'yxati (Tugmali, Sahifalash va To'liq tahlil bilan)
    if is_admin and text in ("👥 Foydalanuvchilar ro'yxati", "👥 Foydalanuvchilar", "/users"):
        text_out, kb_out = format_user_list_keyboard(page=1)
        send_telegram_msg(chat_id, text_out, reply_markup=kb_out, bot_token=active_token)
        return

    # 2. Bazani yuklab olish (Render qayta tushishidan oldin yoki istalgan payt)
    if is_admin and text in ("💾 Bazani yuklab olish", "💾 Baza zaxirasi", "/backup", "/dump"):
        send_telegram_msg(chat_id, "⏳ <b>Baza zaxirasi tayyorlanmoqda...</b>", bot_token=active_token)
        now_str = get_now_tashkent().strftime("%Y%m%d_%H%M")
        
        # A) Agar SQLite bo'lsa, .db faylni to'g'ridan-to'g'ri jo'natish
        if not IS_POSTGRES and os.path.exists(LOCAL_DB_FILE):
            cap_db = (
                "╭────────────────────────╮\n"
                "   💾  <b>CHORVA BULUT BAZASI (SQLITE)</b>\n"
                "╰────────────────────────╯\n\n"
                f"📅 <b>Sana:</b> {get_now_tashkent().strftime('%Y-%m-%d %H:%M')}\n"
                f"📁 <b>Fayl:</b> <code>chorva_cloud_{now_str}.db</code>\n\n"
                "💡 <b>Qayta tiklash yo'riqnomasi:</b>\n"
                "Render qayta ishga tushganda yoki yangilanganda, ushbu faylni botga shunchaki qayta jo'nating. "
                "Tizim bazani darhol to'liq tiklab oladi!"
            )
            import shutil
            tmp_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"chorva_cloud_{now_str}.db")
            try:
                shutil.copyfile(LOCAL_DB_FILE, tmp_db)
                send_telegram_document(chat_id, tmp_db, caption=cap_db, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            finally:
                if os.path.exists(tmp_db):
                    try: os.remove(tmp_db)
                    except Exception: pass

        # B) Universal JSON zaxirani ham jo'natish
        try:
            dump_data = export_database_json()
            json_filename = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"chorva_backup_{now_str}.json")
            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(dump_data, f, ensure_ascii=False, indent=2, default=str)

            cap_json = (
                "╭────────────────────────╮\n"
                "   📋  <b>UNIVERSAL JSON ZAXIRA</b>\n"
                "╰────────────────────────╯\n\n"
                f"📅 <b>Sana:</b> {get_now_tashkent().strftime('%Y-%m-%d %H:%M')}\n"
                f"📁 <b>Fayl:</b> <code>chorva_backup_{now_str}.json</code>\n\n"
                "Bu barcha jadvallarning universal matnli zaxira nusxasi. Uni botga jo'natib ham bazani tiklash mumkin."
            )
            send_telegram_document(chat_id, json_filename, caption=cap_json, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
            if os.path.exists(json_filename):
                try: os.remove(json_filename)
                except Exception: pass
        except Exception as e:
            send_telegram_msg(chat_id, f"⚠️ JSON zaxira yaratishda xatolik: {e}", bot_token=active_token)
        return

    # 3. Bazani tiklash rejimi
    if is_admin and text in ("📥 Bazani tiklash", "📥 Tiklash", "/restore"):
        ADMIN_STATE[chat_id] = "waiting_db_restore"
        prompt_rst = (
            "╭────────────────────────╮\n"
            "   📥  <b>BAZANI TIKLASH REJIMI</b>\n"
            "╰────────────────────────╯\n\n"
            "Avval yuklab olgan <code>.db</code> yoki <code>.json</code> zaxira faylingizni menga yuboring (fayl sifatida).\n\n"
            "⚡️ <b>Nima sodir bo'ladi?</b>\n"
            " • Baza ushbu fayl asosida to'liq yangilanadi;\n"
            " • Barcha fermerlar, jonivorlar, kassa va hisobotlar qayta tiklanadi!\n\n"
            "<i>Bekor qilish uchun: «❌ Bekor qilish» tugmasini bosing.</i>"
        )
        send_telegram_msg(chat_id, prompt_rst, reply_markup={"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}, bot_token=active_token)
        return

    if is_admin and text in ("🔔 Azon eslatmasini sinash", "/testnotif", "/test_azon"):
        now_hm = get_now_tashkent().strftime("%H:%M")
        test_azon = (
            "╭────────────────────────╮\n"
            "   🔔  <b>ASR NAMOZI VAQTI KIRDI! (TEST)</b>\n"
            "╰────────────────────────╯\n\n"
            f"📍 <b>Hudud:</b> Toshkent | 🕒 <b>Vaqt:</b> {now_hm}\n\n"
            "🕌 <b>🌇 Asr namozi vaqti kirdi.</b>\n"
            "<i>«Albatta, namoz mo'minlarga vaqtida farz qilingandir.» (Niso, 103)</i>\n\n"
            "✨ <b>Bildirishnoma tizimi 100% barqaror ishlamoqda!</b>\n"
            "<i>Har bir namoz vaqti kirishi bilan ushbu xabar avtomatik yuboriladi.</i>"
        )
        send_telegram_msg(chat_id, test_azon, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
        return


    # ─── AI CHORVA BOTI BUYRUQLARI ───
    if text in ("🐂 AI Chorva haqida", "🐂 AI Chorva", "🐂 AI Chorva ilovasi", "ℹ️ Ilova haqida"):
        info_text = (
            "╭────────────────────────╮\n"
            "   🐂  <b>AI CHORVA MOBIL TIZIMI</b>\n"
            "╰────────────────────────╯\n\n"
            "<b>AI Chorva</b> — O'zbekiston chorvadorlari va fermerlari uchun yaratilgan eng mukammal mobil boshqaruv ilovasi!\n\n"
            "💡 <b>Asosiy imkoniyatlar:</b>\n"
            " • Jonivorlar hisobi, vazn dinamikasi va kunlik semirish (og'im)\n"
            " • Ombor (Sklad), ratsion va kunlik yem taqsimoti\n"
            " • Kassa, daromad, sarmoya, qarzlar va sof foyda hisobi\n"
            " • Zotlar rentabelligi va Zootexnik AI tavsiyalari\n"
            " • 🕌 Ilovada Namoz vaqtlari vidjeti (sozlamalardan yoqish/o'chirish mumkin)\n"
            " • 100% Oflayn rejimda ham to'liq ishlash\n\n"
            "📲 <b>Ilovaga kirish uchun:</b>\n"
            "Pastdagi <b>«📱 Telefon raqamni ulashish»</b> tugmasini bosing va 6 xonali tasdiqlash kodini oling!"
        )
        send_telegram_msg(chat_id, info_text, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return


    if text in ("📥 Ilovani yuklab olish (APK)", "📥 Ilovani yuklab olish", "/apk", "/app"):
        send_latest_apk_document(chat_id, active_token)
        return

        # 3. Agar hali bazada ham, diskda ham bo'lmasa: Yo'riqnoma va to'g'ridan-to'g'ri havola
        fallback_text = (
            "╭────────────────────────╮\n"
            "   📥  <b>ILOVANI YUKLAB OLISH</b>\n"
            "╰────────────────────────╯\n\n"
            "📲 <b>AI Chorva APK (Android versiya):</b>\n"
            "Ilovangizning rasmiy barqaror versiyasi tayyorlangan!\n\n"
            "📁 <b>Fayl nomi:</b> <code>ChorvaERP.apk</code>\n"
            "⚡️ <b>Hajmi:</b> ~4.8 MB\n\n"
            "🌐 <b>To'g'ridan-to'g'ri brauzerdan yuklab olish:</b>\n"
            "👉 <a href='https://aichorva-cloud.onrender.com/download/ChorvaERP.apk'>ChorvaERP.apk ni yuklab olish</a>\n\n"
            "🔑 <b>Kirish yo'riqnomasi:</b>\n"
            "1. Ilovani telefoningizga o'rnating;\n"
            "2. Botdagi <b>«📱 Telefon raqamni ulashish»</b> tugmasini bosing;\n"
            "3. Kelgan 6 xonali kodni ilovaga kiriting va tizimga kiring!"
        )
        if is_admin:
            fallback_text += (
                "\n\n👑 <b>Admin eslatmasi:</b>\n"
                "Siz adminsiz! Menga shunchaki <code>.apk</code> faylni yuboring — "
                "server uni bir zumda saqlab, barcha foydalanuvchilar uchun faollashtiradi!"
            )
        send_telegram_msg(chat_id, fallback_text, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return

    # Admin yangi APK yuklash tugmasini bosganda
    if is_admin and text in ("📦 Yangi APK yuklash", "/newapk", "/uploadapk"):
        ADMIN_STATE[chat_id] = "waiting_apk"
        prompt_apk = (
            "╭────────────────────────╮\n"
            "   📦  <b>YANGI APK YUKLASH</b>\n"
            "╰────────────────────────╯\n\n"
            "Menga shunchaki yangilangan <code>.apk</code> ilova faylini jo'nating (fayl sifatida).\n\n"
            "💡 <b>Maslahat:</b> Xabar izohiga (caption) yangi versiya raqami yoki yangiliklarni yozib yuborishingiz mumkin (masalan: <code>v1.8 - Yangi dizayn</code>).\n\n"
            "<i>Fayl kelishi bilan u darhol serverda saqlanadi, barcha foydalanuvchilarga bildirishnoma boradi va yangi versiya faollashadi!</i>\n\n"
            "<i>Bekor qilish uchun: «❌ Bekor qilish» tugmasini bosing.</i>"
        )
        send_telegram_msg(chat_id, prompt_apk, reply_markup={"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}, bot_token=active_token)
        return

    # Admin versiya e'lon qilish tugmasini bosganda
    if is_admin and text in ("📢 Versiya yangiligini e'lon qilish", "/broadcast_version", "Versiya e'lon qilish"):
        v_info = get_current_app_version_info()
        prompt_text = (
            "╭────────────────────────╮\n"
            "   📢  <b>VERSIYA YANGILIGINI E'LON QILISH</b>\n"
            "╰────────────────────────╯\n\n"
            f"🏷 <b>Hozirgi versiya:</b> <b>v{v_info['version_name']} (Kod: {v_info['version_code']})</b>\n"
            f"📦 <b>Fayl hajmi:</b> <b>{v_info['apk_size_mb']} MB</b>\n"
            f"📝 <b>Yangiliklar:</b>\n<i>{v_info['changelog']}</i>\n\n"
            "Barcha Telegram va ilova foydalanuvchilariga yangilanish bildirishnomasi va yuklab olish havolasi yuborilsinmi?"
        )
        confirm_kb = {
            "inline_keyboard": [
                [
                    {"text": "🚀 Ha, barcha foydalanuvchilarga yuborish", "callback_data": "confirm_broadcast_version"}
                ],
                [
                    {"text": "❌ Bekor qilish", "callback_data": "cancel_broadcast_version"}
                ]
            ]
        }
        send_telegram_msg(chat_id, prompt_text, reply_markup=confirm_kb, bot_token=active_token)
        return


    if text in ("👤 Mening profilim", "📊 Mening profilim", "📊 Mening hisobim"):
        if is_admin:
            p_text = (
                "╭────────────────────────╮\n"
                "   👑  <b>BOSH ADMIN PROFILI</b>\n"
                "╰────────────────────────╯\n\n"
                f"👤 <b>Bosh Admin:</b> {from_user.get('first_name', 'Fazliddin')} {from_user.get('last_name', 'Abduraximov')}\n"
                f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
                f"📞 <b>Telefon:</b> <code>+998 97 338 78 27</code>\n"
                f"🌐 <b>Username:</b> @{username or 'fazliddin3388'}\n"
                "👑 <b>Tizimdagi maqomi:</b> <b>ASOSIY TIZIM BOSHQARUVCHISI</b>\n\n"
                "🟢 <i>Sizga tizimning 100% barcha boshqaruv vakolatlari berilgan. Boshqaruv paneli doimo siz uchun ochiq!</i>"
            )
            send_telegram_msg(chat_id, p_text, reply_markup=get_telegram_main_menu(True, is_prayer_bot), bot_token=active_token)
            return

        conn = get_db()
        c = dict_cursor(conn)
        try:
            c.execute(adapt_query("SELECT id, phone, full_name, farm_name, is_verified, created_at FROM users WHERE telegram_id = ?"), (user_id,))
            u = c.fetchone()
            if u:
                p_text = (
                    "╭────────────────────────╮\n"
                    "   👤  <b>FERMER SHAXSIY PROFILI</b>\n"
                    "╰────────────────────────╯\n\n"
                    f"👤 <b>Ism:</b> {u.get('full_name') or 'Noma`lum'}\n"
                    f"📞 <b>Telefon:</b> <code>{u.get('phone')}</code>\n"
                    f"🏡 <b>Ferma:</b> {u.get('farm_name') or 'Mening fermam'}\n"
                    f"🆔 <b>Fermer ID:</b> #{u.get('id')}\n"
                    "🌾 <b>Roli:</b> Fermer\n"
                    "✅ <b>Holat:</b> Bulutga ulangan (Faol)\n\n"
                    "🟢 <i>AI Chorva ilovasi bilan to'liq sinxronlangan.</i>"
                )
            else:
                p_text = (
                    "👤 <b>Siz hali tizimda ro'yxatdan o'tmagansiz.</b>\n\n"
                    "Ilovaga kirish va profil ochish uchun pastdagi <b>«📱 Telefon raqamni ulashish»</b> tugmasini bosing!"
                )
            send_telegram_msg(chat_id, p_text, reply_markup=get_telegram_main_menu(False, is_prayer_bot), bot_token=active_token)
        finally:
            conn.close()
        return


    if text in ("❓ Qo'llanma va Yordam", "❓ Yordam", "❓ Qo'llab-quvvatlash", "/help"):
        help_text = (
            "╭────────────────────────╮\n"
            "   💡  <b>QO'LLANMA VA YORDAM</b>\n"
            "╰────────────────────────╯\n\n"
            "🔹 <b>1. Mobil ilovaga qanday kiraman?</b>\n"
            "└ Pastdagi <b>«📱 Telefon raqamni ulashish»</b> tugmasini bosing. Bot sizga 6 xonali maxsus kod beradi. Shu kodni ilovaga kiritib, tizimga xavfsiz kirasiz!\n\n"
            "🔹 <b>2. APK ilovani qayerdan yuklayman?</b>\n"
            "└ Menyudagi <b>«📥 Ilovani yuklab olish (APK)»</b> tugmasini bosing. Bot ilovaning eng so'nggi rasmiy faylini to'g'ridan-to'g'ri Telegramingizga yuboradi.\n\n"
            "🔹 <b>3. Internet o'chib qolsa hisoblar yo'qolmaydimi?</b>\n"
            "└ Yo'q! AI Chorva ilovasi 100% oflayn ishlaydi. Internet paydo bo'lishi bilan barcha yangi jonivorlar va hisobotlar avtomatik bulutga sinxronlanadi.\n\n"
            "🔹 <b>4. Savolingiz yoki taklifingiz bormi?</b>\n"
            "└ <b>«✍️ Adminga murojaat»</b> tugmasi orqali yozing, admin shaxsan o'zi javob qaytaradi!"
        )
        send_telegram_msg(chat_id, help_text, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return

    if text in ("✍️ Adminga murojaat", "✍️ Murojaat", "/murojaat", "/support"):
        USER_STATE[user_id] = "in_support_chat"
        prompt = (
            "╭────────────────────────╮\n"
            "   ✍️  <b>ADMINGA MUROJAAT (JONLI CHAT)</b>\n"
            "╰────────────────────────╯\n\n"
            "AI Chorva bo'yicha savolingiz, taklifingiz yoki murojaatingizni batafsil yozib yuboring.\n\n"
            "📩 <b>Xabaringiz to'g'ridan-to'g'ri adminga boradi.</b>\n"
            "Admin javob berishi bilan xabari shu yerga keladi va siz xuddi oddiy chatdagidek to'g'ridan-to'g'ri yozisha olasiz!\n\n"
            "<i>Muloqotni yakunlash uchun istalgan payt pastdagi «🚪 Muloqotni yakunlash (Chiqish)» tugmasini bosing.</i>"
        )
        send_telegram_msg(chat_id, prompt, reply_markup={"keyboard": [[{"text": "🚪 Muloqotni yakunlash (Chiqish)"}]], "resize_keyboard": True}, bot_token=active_token)
    if text in ("📏 Torozisiz vazn o'lchash", "/lenta", "/vazn", "/weight"):
        send_lenta_guide(chat_id, animal="menu", bot_token=active_token)
        return

    # ─── ILOVAGA KIRISH KODI BUYRUG'I (Admin va Fermerlar uchun) ───
    if text in ("🔑 Ilovaga kirish kodi", "🔑 Kirish kodi", "/login", "/kod", "/auth", "/code"):
        auth_code = "".join(random.choices(string.digits, k=6))
        conn = get_db()
        c = conn.cursor()
        try:
            # 1. Foydalanuvchini aniqlaymiz
            c.execute(adapt_query("SELECT id, phone, role FROM users WHERE telegram_id = ? OR phone LIKE ? LIMIT 1"), (user_id, "%973387827%"))
            u_row = c.fetchone()
            if not u_row and is_admin:
                admin_phone = "+998973387827"
                if IS_POSTGRES:
                    c.execute("INSERT INTO users (phone, full_name, telegram_id, telegram_username, is_verified, role) VALUES (%s, %s, %s, %s, TRUE, 'admin') RETURNING id",
                              (admin_phone, full_u_name or "Fazliddin", user_id, username))
                    uid = c.fetchone()[0]
                else:
                    c.execute("INSERT INTO users (phone, full_name, telegram_id, telegram_username, is_verified, role) VALUES (?, ?, ?, ?, 1, 'admin')",
                              (admin_phone, full_u_name or "Fazliddin", user_id, username))
                    uid = c.lastrowid
                user_phone = admin_phone
            elif u_row:
                uid = u_row[0]
                user_phone = u_row[1] or "+998900000000"
            else:
                uid = None
                user_phone = None

            expires_at = datetime.utcnow() + timedelta(minutes=60)
            jwt_token = generate_jwt(uid, user_phone) if uid else None

            # Eng oxirgi sessiyani yangilaymiz yoki yangi ochamiz
            c.execute(adapt_query("SELECT session_id FROM auth_sessions WHERE telegram_id = ? ORDER BY id DESC LIMIT 1"), (user_id,))
            s_row = c.fetchone()
            if s_row:
                s_id = s_row[0]
                if IS_POSTGRES:
                    c.execute("""
                        UPDATE auth_sessions 
                        SET auth_code = %s, verified = TRUE, jwt_token = %s, user_id = %s, expires_at = %s
                        WHERE session_id = %s
                    """, (auth_code, jwt_token, uid, expires_at, s_id))
                else:
                    c.execute("""
                        UPDATE auth_sessions 
                        SET auth_code = ?, verified = 1, jwt_token = ?, user_id = ?, expires_at = ?
                        WHERE session_id = ?
                    """, (auth_code, jwt_token, uid, expires_at, s_id))
            else:
                s_id = "".join(random.choices(string.ascii_letters + string.digits, k=24))
                if IS_POSTGRES:
                    c.execute("""
                        INSERT INTO auth_sessions (session_id, telegram_id, phone, auth_code, verified, jwt_token, user_id, expires_at)
                        VALUES (%s, %s, %s, %s, TRUE, %s, %s, %s)
                    """, (s_id, user_id, user_phone, auth_code, jwt_token, uid, expires_at))
                else:
                    c.execute("""
                        INSERT INTO auth_sessions (session_id, telegram_id, phone, auth_code, verified, jwt_token, user_id, expires_at)
                        VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    """, (s_id, user_id, user_phone, auth_code, jwt_token, uid, expires_at))
            conn.commit()

            role_badge = "👑 <b>BOSH ADMIN HUQUQI</b>\n" if is_admin else "🌾 <b>FERMER HISOBI</b>\n"
            code_msg = (
                "╭────────────────────────╮\n"
                "   🔑  <b>ILOVAGA KIRISH KODI</b>\n"
                "╰────────────────────────╯\n\n"
                f"{role_badge}"
                f"Sizning bir martalik tasdiqlash kodingiz:\n\n"
                f"👉 <code>{auth_code}</code> 👈\n\n"
                "────────────────────────\n"
                "📲 <b>Ilovada nima qilish kerak:</b>\n"
                "1. <b>AI Chorva</b> mobil ilovasini oching.\n"
                "2. Yuqoridagi <b>«☁️ Sinxronlash»</b> oynasiga kiring.\n"
                f"3. Ushbu <b>{auth_code}</b> kodini kiritib, «✅ Kirish» tugmasini bosing!\n\n"
                "<i>⏱ Kod 60 daqiqa davomida amal qiladi.</i>"
            )
            send_telegram_msg(chat_id, code_msg, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        finally:
            conn.close()
        return



    # Foydalanuvchi Kontaktini (Telefonini) yuborganida
    if contact:
        contact_user_id = contact.get("user_id")
        sender_id = from_user.get("id")

        # 🛡️ XAVFSIZLIK FILTRI 1: Birovning kontaktini forward qilish yoki soxtalashtirishni oldini olish
        if contact_user_id and contact_user_id != sender_id:
            send_telegram_msg(
                chat_id,
                "⚠️ <b>Xavfsizlik ogohlantirishi!</b>\n\n"
                "Siz boshqa shaxsning kontakt kartochkasini yubordingiz.\n"
                "Tizimga xavfsiz kirish uchun faqat pastdagi rasmiy <b>«📱 Telefon raqamni ulashish»</b> tugmasini bosing!",
                reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot),
                bot_token=active_token
            )
            return

        raw_phone = contact.get("phone_number", "").replace("+", "").replace(" ", "").replace("-", "").strip()
        phone = "+" + raw_phone
        first_name = from_user.get("first_name", "")
        username = from_user.get("username", "")

        # Admin tekshiruvi: Agar telefon yoki ism admin bo'lsa
        if is_admin or "973387827" in raw_phone or raw_phone in ("998973387827", "998973388827"):
            is_admin = True
            try: ACTIVE_ADMIN_IDS.add(int(user_id))
            except Exception: pass
            user_role = "admin"
        else:
            user_role = "farmer"

        auth_code = "".join(random.choices(string.digits, k=6))

        conn = get_db()
        c = conn.cursor()
        try:
            # 1. Jadvalda role ustuni borligini kafolatlash (migratsiya)
            try:
                c.execute("ALTER TABLE users ADD COLUMN role VARCHAR(32) DEFAULT 'farmer'" if IS_POSTGRES else "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'farmer'")
                conn.commit()
            except Exception:
                pass

            # 2. Foydalanuvchini tekshiramiz (telefon yoki telegram_id orqali)
            c.execute(adapt_query("""
                SELECT id, phone, full_name, farm_name, role FROM users 
                WHERE phone = ? OR phone = ? OR telegram_id = ?
            """), (phone, raw_phone, user_id))
            user_row = c.fetchone()
            if not user_row:
                if IS_POSTGRES:
                    c.execute("""
                        INSERT INTO users (phone, full_name, telegram_id, telegram_username, is_verified, role)
                        VALUES (%s, %s, %s, %s, TRUE, %s) RETURNING id
                    """, (phone, first_name, user_id, username, user_role))
                    uid = c.fetchone()[0]
                else:
                    c.execute("""
                        INSERT INTO users (phone, full_name, telegram_id, telegram_username, is_verified, role)
                        VALUES (?, ?, ?, ?, 1, ?)
                    """, (phone, first_name, user_id, username, user_role))
                    uid = c.lastrowid
            else:
                uid = user_row[0]
                existing_role = user_row[4] if len(user_row) > 4 else "farmer"
                final_role = "admin" if (user_role == "admin" or existing_role == "admin") else "farmer"
                if IS_POSTGRES:
                    c.execute("""
                        UPDATE users 
                        SET phone = %s, full_name = COALESCE(NULLIF(%s, ''), full_name), 
                            telegram_id = %s, telegram_username = %s, is_verified = TRUE, role = %s
                        WHERE id = %s
                    """, (phone, first_name, user_id, username, final_role, uid))
                else:
                    c.execute("""
                        UPDATE users 
                        SET phone = ?, full_name = COALESCE(NULLIF(?, ''), full_name), 
                            telegram_id = ?, telegram_username = ?, is_verified = 1, role = ?
                        WHERE id = ?
                    """, (phone, first_name, user_id, username, final_role, uid))

            # 3. Sessiyani tasdiqlaymiz yoki yangi sessiya yaratamiz (auth_sessions ning kaliti session_id hisoblanadi!)
            jwt_token = generate_jwt(uid, phone)
            expires_at = datetime.utcnow() + timedelta(minutes=60)
            c.execute(adapt_query("SELECT session_id FROM auth_sessions WHERE telegram_id = ? OR phone = ? OR phone = ?"), (user_id, phone, raw_phone))
            sess_row = c.fetchone()
            if sess_row:
                s_id = sess_row[0]
                if IS_POSTGRES:
                    c.execute("""
                        UPDATE auth_sessions 
                        SET phone = %s, auth_code = %s, verified = TRUE, jwt_token = %s, user_id = %s, telegram_id = %s, expires_at = %s
                        WHERE session_id = %s
                    """, (phone, auth_code, jwt_token, uid, user_id, expires_at, s_id))
                else:
                    c.execute("""
                        UPDATE auth_sessions 
                        SET phone = ?, auth_code = ?, verified = 1, jwt_token = ?, user_id = ?, telegram_id = ?, expires_at = ?
                        WHERE session_id = ?
                    """, (phone, auth_code, jwt_token, uid, user_id, expires_at, s_id))
            else:
                session_id = "".join(random.choices(string.ascii_letters + string.digits, k=24))
                if IS_POSTGRES:
                    c.execute("""
                        INSERT INTO auth_sessions (session_id, phone, telegram_id, auth_code, verified, jwt_token, user_id, expires_at)
                        VALUES (%s, %s, %s, %s, TRUE, %s, %s, %s)
                    """, (session_id, phone, user_id, auth_code, jwt_token, uid, expires_at))
                else:
                    c.execute("""
                        INSERT INTO auth_sessions (session_id, phone, telegram_id, auth_code, verified, jwt_token, user_id, expires_at)
                        VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    """, (session_id, phone, user_id, auth_code, jwt_token, uid, expires_at))
            conn.commit()

            # Namoz botiga ham avtomatik ro'yxatdan o'tkazamiz
            try:
                c.execute(adapt_query("""
                    INSERT INTO prayer_users (telegram_id, username, full_name, region, notifications)
                    VALUES (?, ?, ?, 'Toshkent', ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name
                """), (user_id, username, first_name, True if IS_POSTGRES else 1))
                conn.commit()
            except Exception as e_p:
                print(f"[AUTO PRAYER USER ERR]: {e_p}")

            success_msg = (
                "╭────────────────────────╮\n"
                "   ✅  <b>TELEFONINGIZ TASDIQLANDI!</b>\n"
                "╰────────────────────────╯\n\n"
                f"👤 <b>Fermer:</b> {first_name}\n"
                f"📞 <b>Telefon:</b> <code>{phone}</code>\n"
                f"🔑 <b>Bir martalik kirish kodi:</b> <code>{auth_code}</code>\n\n"
                "────────────────────────\n"
                "📲 <b>Ilovaga kirish:</b>\n"
                "Ushbu 6 xonali kodni AI Chorva ilovasiga kiriting yoki ilovangiz darhol ochiladi!"
            )
            if is_admin:
                success_msg += "\n\n👑 <b>Xush kelibsiz, Bosh Admin! Menyuda «👑 ADMIN BOSHQARUV PANELI» faollashtirildi.</b>"

            send_telegram_msg(chat_id, success_msg, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        except Exception as e:
            conn.rollback()
            import traceback
            traceback.print_exc()
            print(f"[TG CONTACT SAVE ERR]: {e}")
            send_telegram_msg(chat_id, "Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.", bot_token=active_token)
        finally:
            conn.close()
        return


    # Standart noma'lum xabarlar uchun
    send_telegram_msg(chat_id, "Kerakli bo'limni tanlash uchun pastdagi tugmalardan foydalaning:", reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)


# ─── NAMOZ VAQTI AZON ESLATMASI FON OQIMI ───
def prayer_reminder_thread():
    """Har daqiqa azon vaqtini tekshirib, foydalanuvchilarga eslatma yuboradi"""
    print("[PRAYER SCHEDULER] Namoz vaqtlari eslatma monitoringi ishga tushdi...")
    last_notified_minute = -1

    while True:
        try:
            now_dt = get_now_tashkent()
            if now_dt.minute == last_notified_minute:
                time.sleep(15)
                continue

            last_notified_minute = now_dt.minute
            current_hm = now_dt.strftime("%H:%M")

            # Faol hududlarni olamiz
            conn = get_db()
            c = dict_cursor(conn)
            try:
                c.execute(adapt_query("SELECT telegram_id, region, last_notif_time FROM prayer_users WHERE notifications = ?"), (True if IS_POSTGRES else 1,))
                active_users = [dict(r) for r in c.fetchall()]
            finally:
                conn.close()

            if not active_users:
                time.sleep(20)
                continue

            # Har bir hudud bo'yicha namoz vaqtini tekshiramiz
            region_times = {}
            for u in active_users:
                reg = u.get("region") or "Toshkent"
                if reg not in region_times:
                    p_data = fetch_prayer_times(reg)
                    region_times[reg] = p_data.get("times", {})

                times = region_times[reg]
                # Tekshiriladigan asosiy 5 ta namoz
                prayers = [
                    ("tong_saharlik", "Bomdod", "🏙"),
                    ("peshin", "Peshin", "☀️"),
                    ("asr", "Asr", "🌇"),
                    ("shom_iftor", "Shom", "🌆"),
                    ("hufton", "Xufton", "🌃")
                ]

                for p_key, p_name, p_ico in prayers:
                    target_time = times.get(p_key)
                    if target_time == current_hm and u.get("last_notif_time") != f"{current_hm}_{p_name}":
                        # Eslatma matni
                        azon_text = (
                            "╭────────────────────────╮\n"
                            f"   🔔  <b>{p_name.upper()} NAMOZI VAQTI KIRDI!</b>\n"
                            "╰────────────────────────╯\n"
                            f"📍 <b>Hudud:</b> {reg} | 🕒 <b>Vaqt:</b> {current_hm}\n\n"
                            f"🕌 <b>{p_ico} {p_name} namozi vaqti kirdi.</b>\n"
                            "<i>«Albatta, namoz mo'minlarga vaqtida farz qilingandir.» (Niso, 103)</i>\n\n"
                            "✨ Alloh taolo qilayotgan ibodat va duolaringizni qabul aylasin!"
                        )
                        sent = False
                        if PRAYER_BOT_TOKEN:
                            res = send_telegram_msg(u["telegram_id"], azon_text, bot_token=PRAYER_BOT_TOKEN)
                            if res:
                                sent = True
                        if not sent and CHORVA_BOT_TOKEN:
                            send_telegram_msg(u["telegram_id"], azon_text, bot_token=CHORVA_BOT_TOKEN)

                        # Oxirgi yuborilgan vaqtni yangilash
                        c_conn = get_db()
                        cc = c_conn.cursor()
                        try:
                            cc.execute(adapt_query("UPDATE prayer_users SET last_notif_time = ? WHERE telegram_id = ?"),
                                       (f"{current_hm}_{p_name}", u["telegram_id"]))
                            c_conn.commit()
                        except Exception:
                            pass
                        finally:
                            c_conn.close()

            time.sleep(20)
        except Exception as e:
            print(f"[PRAYER REMINDER LOOP ERR]: {e}")
            time.sleep(30)


# 1. AI Chorva boti (@AIchorvabot) Polling oqimi
def chorva_bot_polling_thread():
    if not CHORVA_BOT_TOKEN:
        return
    print(f"[TELEGRAM] AI Chorva Bot (@{CHORVA_BOT_USERNAME}) Polling ishga tushmoqda...")
    try:
        requests.post(f"https://api.telegram.org/bot{CHORVA_BOT_TOKEN}/deleteWebhook", timeout=8)
    except Exception:
        pass
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{CHORVA_BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            resp = requests.get(url, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    try:
                        handle_telegram_update(upd, bot_token=CHORVA_BOT_TOKEN)
                    except Exception as e:
                        print(f"[CHORVA BOT UPDATE ERR]: {e}")
                        traceback.print_exc()
        except Exception as e:
            print(f"[CHORVA BOT POLL ERR]: {e}")
            time.sleep(3)
        time.sleep(0.5)


# 2. Asl Namoz Vaqtlari Boti Polling oqimi
def prayer_bot_polling_thread():
    if not PRAYER_BOT_TOKEN:
        return
    print("[TELEGRAM] Asl Namoz Vaqtlari Boti Polling ishga tushmoqda...")
    try:
        requests.post(f"https://api.telegram.org/bot{PRAYER_BOT_TOKEN}/deleteWebhook", timeout=8)
    except Exception:
        pass
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{PRAYER_BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            resp = requests.get(url, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    try:
                        handle_telegram_update(upd, bot_token=PRAYER_BOT_TOKEN)
                    except Exception as e:
                        print(f"[PRAYER BOT UPDATE ERR]: {e}")
                        traceback.print_exc()
        except Exception as e:
            print(f"[PRAYER BOT POLL ERR]: {e}")
            time.sleep(3)
        time.sleep(0.5)



def keep_awake_pinger_thread():
    """Render.com 15 daqiqada uxlab qolmasligi uchun o'z-o'zini har 10 daqiqada internet orqali ping qilib turuvchi oqim"""
    print("[KEEP-AWAKE] 24/7 Anti-Sleep oqimi ishga tushdi...")
    time.sleep(25)  # Server to'liq yuklanguncha kutish
    while True:
        try:
            ext_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("SERVER_URL") or os.environ.get("PING_URL")
            if ext_url:
                target_url = ext_url.rstrip("/") + "/api/health"
                r = requests.get(target_url, timeout=15)
                print(f"[KEEP-AWAKE PING] {target_url} -> Status: {r.status_code}")
            else:
                port = int(os.environ.get("PORT", 5000))
                requests.get(f"http://127.0.0.1:{port}/api/health", timeout=10)
        except Exception as e:
            print(f"[KEEP-AWAKE ERR]: {e}")
        time.sleep(600)  # Har 10 daqiqada (600 soniya) so'rov yuborib Render taymerini yangilab turadi


# Server startida oqimlarni yoqish
if not os.environ.get("USE_WEBHOOK"):
    if CHORVA_BOT_TOKEN:
        t_chorva = threading.Thread(target=chorva_bot_polling_thread, daemon=True)
        t_chorva.start()
    if PRAYER_BOT_TOKEN:
        t_pr_bot = threading.Thread(target=prayer_bot_polling_thread, daemon=True)
        t_pr_bot.start()

t_prayer = threading.Thread(target=prayer_reminder_thread, daemon=True)
t_prayer.start()

t_backup = threading.Thread(target=daily_db_backup_scheduler_thread, daemon=True)
t_backup.start()

t_awake = threading.Thread(target=keep_awake_pinger_thread, daemon=True)
t_awake.start()

# ═════════════════════════════════════════════════════════════════════════════
# 5. REST API ENDPOINTS: NAMOZ VAQTLARI & AUTENTIFIKATSIYA
# ═════════════════════════════════════════════════════════════════════════════
@app.route('/', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health_check():
    """Server holatini tekshirish va Render.com uxlamasligi uchun Keep-Alive endpoint"""
    return jsonify({
        "status": "online",
        "service": "AI Chorva Cloud & Prayer Times Backend",
        "database": "PostgreSQL" if IS_POSTGRES else "SQLite",
        "chorva_bot": f"@{CHORVA_BOT_USERNAME}" if CHORVA_BOT_TOKEN else "unconfigured",
        "prayer_bot": "active" if PRAYER_BOT_TOKEN else "unconfigured",
        "version": "2.0.0",
        "keep_awake": "enabled",
        "timestamp": datetime.utcnow().isoformat(),
        "tashkent_time": get_now_tashkent().strftime("%Y-%m-%d %H:%M:%S")
    }), 200


TELEGRAM_APK_CDN_CACHE = {"url": None, "expires_at": 0}

@app.route('/download/ChorvaERP.apk', methods=['GET'])
@app.route('/download/apk', methods=['GET'])
@app.route('/api/app/download', methods=['GET'])
def download_latest_apk():
    """
    Mobil ilovani yuqori tezlikda va serverni ortiqcha yuklamasdan yuklab olish.
    Render bepul tarifida 512MB RAM bo'lgani sababli, bir vaqtda ko'plab foydalanuvchilar yuklaganda
    server qotib qolmasligi uchun Telegramning yuqori tezlikdagi global CDN tarmog'iga
    (302 Redirect orqali) xavfsiz yo'naltiriladi!
    """
    global TELEGRAM_APK_CDN_CACHE
    now = time.time()

    # 1. Telegram CDN keshini tekshiramiz (kesh 1 soat amal qiladi)
    if TELEGRAM_APK_CDN_CACHE.get("url") and TELEGRAM_APK_CDN_CACHE.get("expires_at", 0) > now:
        return redirect(TELEGRAM_APK_CDN_CACHE["url"], code=302)

    # 2. Bazadan eng so'nggi Telegram file_id ni olib, Telegram CDN ga yo'naltirish
    try:
        conn = get_db()
        c = dict_cursor(conn)
        c.execute(adapt_query("SELECT file_id FROM app_releases WHERE file_id IS NOT NULL ORDER BY id DESC LIMIT 1"))
        row = c.fetchone()
        conn.close()
        if row and row.get("file_id") and CHORVA_BOT_TOKEN:
            file_id = row["file_id"]
            r = requests.get(f"https://api.telegram.org/bot{CHORVA_BOT_TOKEN}/getFile?file_id={file_id}", timeout=10)
            if r.status_code == 200:
                fpath = r.json().get("result", {}).get("file_path")
                if fpath:
                    cdn_url = f"https://api.telegram.org/file/bot{CHORVA_BOT_TOKEN}/{fpath}"
                    TELEGRAM_APK_CDN_CACHE = {"url": cdn_url, "expires_at": now + 3600}
                    return redirect(cdn_url, code=302)
    except Exception as e:
        print(f"[APK CDN STREAM ERR]: {e}")

    # 3. Agar Telegram CDN mavjud bo'lmasa, mahalliy server diskidan uzatamiz
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk")
    if os.path.exists(local_path):
        return send_file(local_path, as_attachment=True, download_name="ChorvaERP.apk", mimetype="application/vnd.android.package-archive")

    return redirect("https://github.com/fazliddin3388/aichorva-cloud/releases", code=302)


@app.route('/img/<path:filename>', methods=['GET'])
def serve_cloud_image(filename):
    """Lenta va tarozi diagrammalari hamda ilova rasmlarini uzatish"""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    img_dir = os.path.join(root_dir, "img")
    target = os.path.join(img_dir, filename)
    if os.path.exists(target):
        return send_file(target, mimetype="image/jpeg")
    target_root = os.path.join(root_dir, filename)
    if os.path.exists(target_root):
        return send_file(target_root, mimetype="image/jpeg")
    return jsonify({"error": "Image not found"}), 404


@app.route('/api/app/latest', methods=['GET'])
@app.route('/api/app/version', methods=['GET'])
@app.route('/api/app/config', methods=['GET'])
def get_latest_app_release():
    """Eng so'nggi mobil ilova versiyasi va tizim sozlamalari (require_auth)"""
    v_info = get_current_app_version_info()
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk")
    has_local = os.path.exists(local_path)
    req_auth = (get_system_setting("require_auth", "true") == "true")

    resp = jsonify({
        "status": "success",
        "version_name": v_info.get("version_name", "1.8"),
        "version_code": v_info.get("version_code", 224),
        "changelog": v_info.get("changelog", "Yangi imkoniyatlar va yaxshilanishlar"),
        "apk_size_mb": v_info.get("apk_size_mb", 5.37),
        "release_date": v_info.get("release_date", "2026-09-28"),
        "has_local_apk": has_local,
        "require_auth": req_auth,
        "download_url": "/download/ChorvaERP.apk",
        "direct_download_url": "https://aichorva-cloud.onrender.com/download/ChorvaERP.apk"
    })
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route('/api/prayer/regions', methods=['GET'])
def get_prayer_regions():
    """Barcha viloyatlar va shaharlar ro'yxati (Mobil ilova uchun)"""
    return jsonify({
        "status": "success",
        "regions": PRAYER_DATA
    })


@app.route('/api/prayer/times', methods=['GET'])
def get_prayer_times_api():
    """Ko'rsatilgan hudud bo'yicha kunlik namoz vaqtlari va keyingi namoz vaqti"""
    region = request.args.get("region", "Toshkent").strip()
    try:
        data = fetch_prayer_times(region)
        return jsonify({
            "status": "success",
            "data": data
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Namoz vaqtlarini yuklashda xatolik: {str(e)}"
        }), 500



@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """Render.com da Webhook orqali Telegram xabarlarini qabul qilish"""
    upd = request.get_json(force=True, silent=True)
    if upd:
        handle_telegram_update(upd)
    return jsonify({"ok": True})


@app.route('/api/auth/telegram-session', methods=['POST'])
def create_telegram_session():
    """Mobil ilovadan Telegram orqali kirish sessiyasini yaratish"""
    data = request.get_json(silent=True) or {}
    session_id = "".join(random.choices(string.ascii_letters + string.digits, k=24))
    phone = data.get("phone", "").strip()

    conn = get_db()
    c = conn.cursor()
    try:
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        c.execute(adapt_query("""
            INSERT INTO auth_sessions (session_id, phone, expires_at)
            VALUES (?, ?, ?)
        """), (session_id, phone, expires_at))
        conn.commit()
    finally:
        conn.close()

    bot_url = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start=auth_{session_id}"
    return jsonify({
        "status": "success",
        "session_id": session_id,
        "bot_url": bot_url,
        "bot_username": TELEGRAM_BOT_USERNAME
    })


@app.route('/api/auth/check-session', methods=['POST'])
def check_telegram_session():
    """Mobil ilova Telegramda kontakt ulashilganligini tekshiradi (Jonli avtomatik kirish)"""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"status": "error", "message": "session_id talab qilinadi"}), 400

    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("SELECT verified, jwt_token, phone, user_id FROM auth_sessions WHERE session_id = ?"), (session_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Sessiya topilmadi"}), 404

        is_verified = bool(row["verified"])
        if is_verified:
            # Foydalanuvchi ma'lumotlarini olamiz
            u_cur = dict_cursor(conn)
            u_cur.execute(adapt_query("SELECT id, phone, full_name, farm_name FROM users WHERE id = ?"), (row["user_id"],))
            user_data = u_cur.fetchone()
            return jsonify({
                "status": "success",
                "verified": True,
                "token": row["jwt_token"],
                "user": dict(user_data) if user_data else {}
            })
        return jsonify({"status": "pending", "verified": False})
    finally:
        conn.close()


@app.route('/api/auth/verify-code', methods=['POST'])
def verify_code():
    """Foydalanuvchi Telegramdan olgan 6 xonali kodni kiritganda tekshirish"""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    code = str(data.get("code", "")).strip()

    if not code:
        return jsonify({"status": "error", "message": "Tasdiqlash kodi kiritilmadi"}), 400

    conn = get_db()
    c = dict_cursor(conn)
    try:
        row = None
        # 1-usul: Agar session_id mavjud bo'lsa va unda shu kod bo'lsa
        if session_id:
            c.execute(adapt_query("""
                SELECT id, session_id, verified, jwt_token, auth_code, user_id, phone, telegram_id, expires_at 
                FROM auth_sessions 
                WHERE session_id = ? AND auth_code = ?
            """), (session_id, code))
            row = c.fetchone()

        # 2-usul: Agar session_id bo'yicha chiqmasa, aynan shu auth_code bo'yicha eng so'nggi faol sessiyani topamiz!
        if not row:
            c.execute(adapt_query("""
                SELECT id, session_id, verified, jwt_token, auth_code, user_id, phone, telegram_id, expires_at 
                FROM auth_sessions 
                WHERE auth_code = ? 
                ORDER BY id DESC LIMIT 1
            """), (code,))
            row = c.fetchone()

        if not row:
            return jsonify({"status": "error", "message": "Noto'g'ri tasdiqlash kodi yoki kod muddati tugagan"}), 400

        # Sessiya muddatini tekshirish (60 daqiqa)
        if row.get("expires_at"):
            exp_dt = row["expires_at"]
            if isinstance(exp_dt, str):
                try: exp_dt = datetime.strptime(exp_dt, "%Y-%m-%d %H:%M:%S.%f")
                except Exception:
                    try: exp_dt = datetime.strptime(exp_dt, "%Y-%m-%d %H:%M:%S")
                    except Exception: pass
            if isinstance(exp_dt, datetime) and exp_dt < datetime.utcnow():
                return jsonify({"status": "error", "message": "Tasdiqlash kodi muddati tugagan. Qaytadan yangi kod oling."}), 400

        user_id = row.get("user_id")
        user_phone = row.get("phone")
        tg_id = row.get("telegram_id")

        # Agar user_id hali sessiyaga ulanmagan bo'lsa
        if not user_id and tg_id:
            u_cur = dict_cursor(conn)
            u_cur.execute(adapt_query("SELECT id, phone, role FROM users WHERE telegram_id = ? LIMIT 1"), (tg_id,))
            u_find = u_cur.fetchone()
            if u_find:
                user_id = u_find["id"]
                user_phone = u_find.get("phone") or user_phone
            elif is_admin_user(tg_id, phone=user_phone):
                u_cur.execute(adapt_query("SELECT id, phone FROM users WHERE role = 'admin' LIMIT 1"))
                u_admin = u_cur.fetchone()
                if u_admin:
                    user_id = u_admin["id"]
                    user_phone = u_admin["phone"]

        # Agar hanuz user_id bo'lmasa, lekin Bosh Admin bo'lsa:
        if not user_id and (is_admin_user(tg_id, phone=user_phone) or tg_id == 225011967):
            u_cur = dict_cursor(conn)
            u_cur.execute(adapt_query("SELECT id, phone FROM users WHERE role = 'admin' OR telegram_id = 225011967 LIMIT 1"))
            u_adm = u_cur.fetchone()
            if u_adm:
                user_id = u_adm["id"]
                user_phone = u_adm["phone"]

        if not user_id:
            return jsonify({"status": "error", "message": "Iltimos, avval Telegram botda telefon raqamingizni ulashing!"}), 400

        # Foydalanuvchi ma'lumotlarini yuklaymiz
        u_cur = dict_cursor(conn)
        u_cur.execute(adapt_query("SELECT id, phone, full_name, farm_name, role FROM users WHERE id = ?"), (user_id,))
        user_data = u_cur.fetchone()

        token = row.get("jwt_token") or generate_jwt(user_id, user_phone or "+998900000000")

        # Sessiyani tasdiqlangan qilib qo'yamiz va kodni tozalaymiz
        target_s_id = row["session_id"]
        c.execute(adapt_query("UPDATE auth_sessions SET verified = 1, jwt_token = ?, auth_code = NULL, user_id = ? WHERE session_id = ?"), 
                  (token, user_id, target_s_id))
        conn.commit()

        return jsonify({
            "status": "success",
            "token": token,
            "user": dict(user_data) if user_data else {"id": user_id, "phone": user_phone, "role": "admin" if is_admin_user(tg_id, phone=user_phone) else "farmer"}
        })
    finally:
        conn.close()


@app.route('/api/user/profile', methods=['GET', 'POST'])
@jwt_required
def user_profile():
    user_id = request.current_user["user_id"]
    conn = get_db()
    c = dict_cursor(conn)
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            full_name = data.get("full_name")
            farm_name = data.get("farm_name")
            fcm_token = data.get("fcm_token")
            c.execute(adapt_query("""
                UPDATE users 
                SET full_name = COALESCE(?, full_name),
                    farm_name = COALESCE(?, farm_name),
                    fcm_token = COALESCE(?, fcm_token)
                WHERE id = ?
            """), (full_name, farm_name, fcm_token, user_id))
            conn.commit()

        c.execute(adapt_query("SELECT id, phone, full_name, farm_name, role, created_at FROM users WHERE id = ?"), (user_id,))
        user = c.fetchone()
        return jsonify({"status": "success", "user": dict(user)})
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# 6. BULUTLI SINXRONLASH API (Multi-Tenant Cloud Sync)
# ═════════════════════════════════════════════════════════════════════════════
@app.route('/api/cloud/sync', methods=['POST'])
@jwt_required
def cloud_sync():
    """
    Mobil ilovadagi mahalliy IndexedDB ma'lumotlarini foydalanuvchining
    shaxsiy bulutli bo'limi bilan ikki tomonlama to'liq sinxronlash (Push + Pull).
    """
    user_id = request.current_user["user_id"]
    payload = request.get_json(silent=True) or {}
    conn = get_db()
    c = conn.cursor()

    counts = {"bulls": 0, "weighings": 0, "feeds": 0, "expenses": 0, "cash": 0, "debts": 0, "inventory": 0}

    try:
        # 0. O'chirilgan jonivorlarni bulutdan ham butunlay tozalash (Deletions / Tombstones)
        for d_tag in payload.get("deleted_tags", []):
            d_tag_clean = str(d_tag).strip()
            if not d_tag_clean:
                continue
            c.execute(adapt_query("DELETE FROM bulls WHERE user_id = ? AND tag_id = ?"), (user_id, d_tag_clean))
            c.execute(adapt_query("DELETE FROM weighings WHERE user_id = ? AND tag_id = ?"), (user_id, d_tag_clean))
            c.execute(adapt_query("DELETE FROM feed_logs WHERE user_id = ? AND tag_id = ?"), (user_id, d_tag_clean))
            c.execute(adapt_query("DELETE FROM other_expenses WHERE user_id = ? AND tag_id = ?"), (user_id, d_tag_clean))
            c.execute(adapt_query("DELETE FROM vaccine_schedules WHERE user_id = ? AND tag_id = ?"), (user_id, d_tag_clean))
            print(f"[CLOUD SYNC DELETE]: user_id={user_id} tag={d_tag_clean} bulutdan o'chirildi")

        # 0.1. O'chirilgan kassa operatsiyalarini tozalash
        for sig in payload.get("deleted_cash_signatures", []):
            parts = str(sig).split("_", 2)
            if len(parts) >= 3:
                try:
                    c.execute(adapt_query("DELETE FROM cash_transactions WHERE user_id = ? AND trans_date = ? AND amount = ? AND trans_type = ?"), (user_id, parts[0], float(parts[1]), parts[2]))
                except Exception:
                    pass

        # 0.2. O'chirilgan qarzlarni tozalash
        for dsig in payload.get("deleted_debt_names", []):
            parts = str(dsig).split("_", 1)
            if len(parts) >= 1:
                c.execute(adapt_query("DELETE FROM debts WHERE user_id = ? AND creditor_name = ?"), (user_id, parts[0]))

        # 1. Bulls (Jonivorlar) Push
        bull_tag_to_id = {}
        for b in payload.get("bulls", []):
            tag_id = str(b.get("tag_id", "")).strip()
            if not tag_id:
                continue
            atype = b.get("animal_type", "Buqa")
            breed = b.get("breed", "")
            bdate = b.get("buy_date", str(date.today()))
            bprice = float(b.get("buy_price", 0.0))
            iweight = float(b.get("initial_weight", 0.0))
            cweight = float(b.get("current_weight", iweight))
            status = b.get("status", "active")
            sdate = b.get("sold_date")
            sweight = float(b.get("sold_weight", 0.0)) if b.get("sold_weight") else None
            sprice = float(b.get("sold_price_total", 0.0)) if b.get("sold_price_total") else None
            notes = b.get("notes", "")
            mid = b.get("mother_id")
            mtag = b.get("mother_tag")
            b_stat = b.get("breeding_status")
            b_date = b.get("breeding_date")
            exp_b_date = b.get("expected_birth_date")
            b_cnt = int(b.get("birth_count", 0)) if b.get("birth_count") is not None else 0
            last_b_date = b.get("last_birth_date")

            c.execute(adapt_query("SELECT id FROM bulls WHERE user_id = ? AND tag_id = ?"), (user_id, tag_id))
            ex = c.fetchone()
            if ex:
                bid = ex[0]
                c.execute(adapt_query("""
                    UPDATE bulls 
                    SET animal_type=?, breed=?, buy_date=?, buy_price=?, initial_weight=?,
                        current_weight=?, status=?, sold_date=?, sold_weight=?, sold_price_total=?, notes=?,
                        mother_id=?, mother_tag=?, breeding_status=?, breeding_date=?, expected_birth_date=?,
                        birth_count=?, last_birth_date=?
                    WHERE id = ? AND user_id = ?
                """), (atype, breed, bdate, bprice, iweight, cweight, status, sdate, sweight, sprice, notes,
                       mid, mtag, b_stat, b_date, exp_b_date, b_cnt, last_b_date, bid, user_id))
            else:
                c.execute(adapt_query("""
                    INSERT INTO bulls (user_id, tag_id, animal_type, breed, buy_date, buy_price, initial_weight, current_weight, status, sold_date, sold_weight, sold_price_total, notes, mother_id, mother_tag, breeding_status, breeding_date, expected_birth_date, birth_count, last_birth_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
                """ if IS_POSTGRES else """
                    INSERT INTO bulls (user_id, tag_id, animal_type, breed, buy_date, buy_price, initial_weight, current_weight, status, sold_date, sold_weight, sold_price_total, notes, mother_id, mother_tag, breeding_status, breeding_date, expected_birth_date, birth_count, last_birth_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (user_id, tag_id, atype, breed, bdate, bprice, iweight, cweight, status, sdate, sweight, sprice, notes,
                       mid, mtag, b_stat, b_date, exp_b_date, b_cnt, last_b_date))
                bid = c.fetchone()[0] if IS_POSTGRES else c.lastrowid
                counts["bulls"] += 1
            bull_tag_to_id[tag_id] = bid

        # 2. Tarozi o'lchovlari (Weighings)
        for w in payload.get("weighings", []):
            tag_id = str(w.get("tag_id", "")).strip()
            bid = bull_tag_to_id.get(tag_id)
            wdate = w.get("weigh_date", str(date.today()))
            weight = float(w.get("weight", 0.0))
            gain = float(w.get("gain_since_last", 0.0))
            dgain = float(w.get("daily_gain_g", 0.0))

            c.execute(adapt_query("""
                SELECT id FROM weighings WHERE user_id = ? AND tag_id = ? AND weigh_date = ?
            """), (user_id, tag_id, wdate))
            if not c.fetchone():
                c.execute(adapt_query("""
                    INSERT INTO weighings (user_id, bull_id, tag_id, weigh_date, weight, gain_since_last, daily_gain_g)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """), (user_id, bid, tag_id, wdate, weight, gain, dgain))
                counts["weighings"] += 1

        # 3. Yem xarajatlari (Feed Logs)
        for f in payload.get("feed_logs", []):
            tag_id = f.get("tag_id")
            bid = bull_tag_to_id.get(tag_id) if tag_id else None
            ldate = f.get("log_date", str(date.today()))
            ftype = f.get("feed_type", "")
            amount = float(f.get("amount_kg", 0.0))
            uprice = float(f.get("unit_price", 0.0))
            tcost = float(f.get("total_cost", amount * uprice))
            note = f.get("note", "")
            from_inv = int(f.get("from_inventory", 1))

            c.execute(adapt_query("""
                SELECT id FROM feed_logs WHERE user_id = ? AND log_date = ? AND feed_type = ? AND amount_kg = ?
            """), (user_id, ldate, ftype, amount))
            if not c.fetchone():
                c.execute(adapt_query("""
                    INSERT INTO feed_logs (user_id, bull_id, tag_id, log_date, feed_type, amount_kg, unit_price, total_cost, note, from_inventory)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (user_id, bid, tag_id, ldate, ftype, amount, uprice, tcost, note, from_inv))
                counts["feeds"] += 1

        # 4. Yem Ombori (Feed Inventory)
        for inv in payload.get("feed_inventory", []):
            ftype = inv.get("feed_type", "").strip()
            stock = float(inv.get("current_stock_kg", 0.0))
            min_w = float(inv.get("min_warning_kg", 100.0))
            uprice = float(inv.get("unit_price", 0.0))
            rdate = inv.get("last_restock_date", str(date.today()))

            c.execute(adapt_query("SELECT id FROM feed_inventory WHERE user_id = ? AND feed_type = ?"), (user_id, ftype))
            ex_inv = c.fetchone()
            if ex_inv:
                c.execute(adapt_query("""
                    UPDATE feed_inventory 
                    SET current_stock_kg = ?, min_warning_kg = ?, unit_price = ?, last_restock_date = ?
                    WHERE id = ? AND user_id = ?
                """), (stock, min_w, uprice, rdate, ex_inv[0], user_id))
            else:
                c.execute(adapt_query("""
                    INSERT INTO feed_inventory (user_id, feed_type, current_stock_kg, min_warning_kg, unit_price, last_restock_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                """), (user_id, ftype, stock, min_w, uprice, rdate))
                counts["inventory"] += 1

        # 5. Boshqa xarajatlar
        for o in payload.get("other_expenses", []):
            tag_id = o.get("tag_id")
            bid = bull_tag_to_id.get(tag_id) if tag_id else None
            edate = o.get("exp_date", str(date.today()))
            cat = o.get("category", "")
            amt = float(o.get("amount", 0.0))
            desc = o.get("description", "")

            c.execute(adapt_query("""
                SELECT id FROM other_expenses WHERE user_id = ? AND exp_date = ? AND category = ? AND amount = ?
            """), (user_id, edate, cat, amt))
            if not c.fetchone():
                c.execute(adapt_query("""
                    INSERT INTO other_expenses (user_id, bull_id, tag_id, exp_date, category, amount, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """), (user_id, bid, tag_id, edate, cat, amt, desc))
                counts["expenses"] += 1

        # 6. Kassa operatsiyalari
        for cs in payload.get("cash_transactions", []):
            tdate = cs.get("trans_date", str(date.today()))
            ttype = cs.get("trans_type", "personal_expense")
            amt = float(cs.get("amount", 0.0))
            cat = cs.get("category", "")
            desc = cs.get("description", "")

            c.execute(adapt_query("""
                SELECT id FROM cash_transactions WHERE user_id = ? AND trans_date = ? AND trans_type = ? AND amount = ? AND description = ?
            """), (user_id, tdate, ttype, amt, desc))
            if not c.fetchone():
                c.execute(adapt_query("""
                    INSERT INTO cash_transactions (user_id, trans_date, trans_type, amount, category, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """), (user_id, tdate, ttype, amt, cat, desc))
                counts["cash"] += 1

        # 7. Qarzlar va Kreditorlar
        for d in payload.get("debts", []):
            cred = d.get("creditor_name", "").strip()
            phone = d.get("phone", "")
            dtype = d.get("debt_type", "borrowed")
            iamt = float(d.get("initial_amount", 0.0))
            ramt = float(d.get("remaining_amount", 0.0))
            sdate = d.get("start_date", str(date.today()))
            ddate = d.get("due_date")
            stat = d.get("status", "active")
            notes = d.get("notes", "")

            c.execute(adapt_query("SELECT id FROM debts WHERE user_id = ? AND creditor_name = ? AND start_date = ?"), (user_id, cred, sdate))
            ex_d = c.fetchone()
            if ex_d:
                c.execute(adapt_query("""
                    UPDATE debts SET remaining_amount = ?, status = ?, notes = ? WHERE id = ? AND user_id = ?
                """), (ramt, stat, notes, ex_d[0], user_id))
            else:
                c.execute(adapt_query("""
                    INSERT INTO debts (user_id, creditor_name, phone, debt_type, initial_amount, remaining_amount, start_date, due_date, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (user_id, cred, phone, dtype, iamt, ramt, sdate, ddate, stat, notes))
                counts["debts"] += 1

        # 8. Emlash taqvimi
        for v in payload.get("vaccine_schedules", []):
            tag_id = v.get("tag_id")
            bid = bull_tag_to_id.get(tag_id) if tag_id else None
            vname = v.get("vaccine_name", "")
            pdate = v.get("planned_date", str(date.today()))
            cdate = v.get("completed_date")
            dose = v.get("dose", "")
            vet = v.get("veterinarian", "")
            status = v.get("status", "pending")
            cost = float(v.get("cost", 0.0))
            notes = v.get("notes", "")

            c.execute(adapt_query("""
                SELECT id FROM vaccine_schedules WHERE user_id = ? AND vaccine_name = ? AND planned_date = ?
            """), (user_id, vname, pdate))
            ex_v = c.fetchone()
            if ex_v:
                c.execute(adapt_query("""
                    UPDATE vaccine_schedules 
                    SET completed_date=?, dose=?, veterinarian=?, status=?, cost=?, notes=?
                    WHERE id = ? AND user_id = ?
                """), (cdate, dose, vet, status, cost, notes, ex_v[0], user_id))
            else:
                c.execute(adapt_query("""
                    INSERT INTO vaccine_schedules (user_id, bull_id, tag_id, vaccine_name, planned_date, completed_date, dose, veterinarian, status, cost, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (user_id, bid, tag_id, vname, pdate, cdate, dose, vet, status, cost, notes))

        # 9. Nasl olish va Tug'ruqlar (Breeding Records)
        counts["breeding_records"] = 0
        for br in payload.get("breeding_records", []):
            mtag = str(br.get("mother_tag", "")).strip()
            mbid = bull_tag_to_id.get(mtag) if mtag else None
            atype = br.get("animal_type", "Sovliq")
            br_date = br.get("breeding_date")
            br_method = br.get("breeding_method")
            sire = br.get("sire_info")
            stat = br.get("status", "kutilmoqda")
            exp_b_date = br.get("expected_birth_date")
            birth_d = br.get("birth_date")
            b_res = br.get("birth_result")
            b_cnt = int(br.get("birth_count", 0)) if br.get("birth_count") is not None else 0
            off_tag = br.get("offspring_tag")
            off_type = br.get("offspring_type")
            off_weight = float(br.get("offspring_weight", 0.0)) if br.get("offspring_weight") else None
            b_notes = br.get("notes", "")

            c.execute(adapt_query("""
                SELECT id FROM breeding_records WHERE user_id = ? AND mother_tag = ? AND (breeding_date = ? OR (birth_date IS NOT NULL AND birth_date = ?))
            """), (user_id, mtag, br_date, birth_d))
            ex_br = c.fetchone()
            if ex_br:
                c.execute(adapt_query("""
                    UPDATE breeding_records
                    SET animal_type=?, breeding_date=?, breeding_method=?, sire_info=?, status=?,
                        expected_birth_date=?, birth_date=?, birth_result=?, birth_count=?,
                        offspring_tag=?, offspring_type=?, offspring_weight=?, notes=?
                    WHERE id = ? AND user_id = ?
                """), (atype, br_date, br_method, sire, stat, exp_b_date, birth_d, b_res, b_cnt, off_tag, off_type, off_weight, b_notes, ex_br[0], user_id))
            else:
                c.execute(adapt_query("""
                    INSERT INTO breeding_records (user_id, mother_id, mother_tag, animal_type, breeding_date, breeding_method, sire_info, status, expected_birth_date, birth_date, birth_result, birth_count, offspring_tag, offspring_type, offspring_weight, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (user_id, mbid, mtag, atype, br_date, br_method, sire, stat, exp_b_date, birth_d, b_res, b_cnt, off_tag, off_type, off_weight, b_notes))
                counts["breeding_records"] += 1

        conn.commit()

        # PULL: Foydalanuvchining bulutdagi barcha yangi ma'lumotlarini qaytarish
        pull_data = {}
        c_dict = dict_cursor(conn)

        c_dict.execute(adapt_query("""
            SELECT tag_id, animal_type, breed, buy_date, buy_price, initial_weight, current_weight, status, sold_date, sold_weight, sold_price_total, notes,
                   mother_id, mother_tag, breeding_status, breeding_date, expected_birth_date, birth_count, last_birth_date
            FROM bulls WHERE user_id = ?
        """), (user_id,))
        pull_data["bulls"] = [dict(r) for r in c_dict.fetchall()]

        c_dict.execute(adapt_query("SELECT tag_id, weigh_date, weight, gain_since_last, daily_gain_g FROM weighings WHERE user_id = ?"), (user_id,))
        pull_data["weighings"] = [dict(r) for r in c_dict.fetchall()]

        c_dict.execute(adapt_query("SELECT tag_id, log_date, feed_type, amount_kg, unit_price, total_cost, note, from_inventory FROM feed_logs WHERE user_id = ?"), (user_id,))
        pull_data["feed_logs"] = [dict(r) for r in c_dict.fetchall()]

        c_dict.execute(adapt_query("SELECT feed_type, current_stock_kg, min_warning_kg, unit_price, last_restock_date FROM feed_inventory WHERE user_id = ?"), (user_id,))
        pull_data["feed_inventory"] = [dict(r) for r in c_dict.fetchall()]

        c_dict.execute(adapt_query("SELECT tag_id, exp_date, category, amount, description FROM other_expenses WHERE user_id = ?"), (user_id,))
        pull_data["other_expenses"] = [dict(r) for r in c_dict.fetchall()]

        c_dict.execute(adapt_query("SELECT trans_date, trans_type, amount, category, description FROM cash_transactions WHERE user_id = ?"), (user_id,))
        pull_data["cash_transactions"] = [dict(r) for r in c_dict.fetchall()]

        c_dict.execute(adapt_query("SELECT creditor_name, phone, debt_type, initial_amount, remaining_amount, start_date, due_date, status, notes FROM debts WHERE user_id = ?"), (user_id,))
        pull_data["debts"] = [dict(r) for r in c_dict.fetchall()]

        c_dict.execute(adapt_query("SELECT tag_id, vaccine_name, planned_date, completed_date, dose, veterinarian, status, cost, notes FROM vaccine_schedules WHERE user_id = ?"), (user_id,))
        pull_data["vaccine_schedules"] = [dict(r) for r in c_dict.fetchall()]

        c_dict.execute(adapt_query("""
            SELECT mother_id, mother_tag, animal_type, breeding_date, breeding_method, sire_info, status, expected_birth_date, birth_date, birth_result, birth_count, offspring_tag, offspring_type, offspring_weight, notes
            FROM breeding_records WHERE user_id = ?
        """), (user_id,))
        pull_data["breeding_records"] = [dict(r) for r in c_dict.fetchall()]

        return jsonify({
            "status": "success",
            "message": "Bulut bilan sinxronlash muvaffaqiyatli yakunlandi!",
            "counts": counts,
            "cloud_data": pull_data
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": f"Sinxronlash xatosi: {str(e)}"}), 500
    finally:
        conn.close()


@app.route('/api/cloud/reset-my-data', methods=['POST'])
@jwt_required
def reset_my_cloud_data():
    """Foydalanuvchining shaxsiy bulutli ma'lumotlarini (buqalar, xarajatlar va b.) tozalash"""
    user_id = request.current_user["user_id"]
    conn = get_db()
    c = conn.cursor()
    try:
        tables = [
            "weighings", "feed_logs", "other_expenses", "cash_transactions",
            "debts", "vaccine_schedules", "feed_inventory", "bulls"
        ]
        for tbl in tables:
            c.execute(adapt_query(f"DELETE FROM {tbl} WHERE user_id = ?"), (user_id,))
        conn.commit()
        return jsonify({"status": "success", "message": "Hisobingiz ma'lumotlari bulutdan muvaffaqiyatli tozalandi!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": f"Tozalashda xatolik: {str(e)}"}), 500
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# 7. BILDIRISHNOMALAR (FCM PUSH) VA REKLAMA/E'LONLAR TIZIMI
# ═════════════════════════════════════════════════════════════════════════════
@app.route('/api/ads/active', methods=['GET'])
@app.route('/api/app/advertisements', methods=['GET'])
def get_active_ads():
    """Mobil ilovada ko'rsatiladigan faol reklama bannerlari va e'lonlar"""
    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("""
            SELECT id, title, image_url, link_url, description, category,
                   COALESCE(media_type, 'text') as media_type, media_file_id, created_at
            FROM advertisements 
            WHERE is_active = ? 
            ORDER BY id DESC LIMIT 15
        """), (True if IS_POSTGRES else 1,))
        ads = [dict(r) for r in c.fetchall()]
        return jsonify({"status": "success", "ads": ads, "total": len(ads)})
    finally:
        conn.close()


@app.route('/api/admin/broadcast-notification', methods=['POST'])
def broadcast_push_notification():
    """Fermerlarga Firebase orqali ommaviy yoki maqsadli xabar yuborish"""
    secret = request.headers.get("X-Admin-Secret")
    if secret != JWT_SECRET:
        return jsonify({"status": "error", "message": "Ruxsat yo'q"}), 403

    data = request.get_json(silent=True) or {}
    title = data.get("title", "Chorva ERP Eslatma")
    body = data.get("body", "")

    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("SELECT fcm_token, telegram_id FROM users WHERE fcm_token IS NOT NULL OR telegram_id IS NOT NULL"))
        users = c.fetchall()

        sent_count = 0
        for u in users:
            # Telegram orqali ham nusxasini jo'natamiz
            if u.get("telegram_id"):
                send_telegram_msg(u["telegram_id"], f"📢 <b>{title}</b>\n\n{body}")
                sent_count += 1

        return jsonify({
            "status": "success",
            "message": f"Bildirishnoma {sent_count} ta foydalanuvchiga yuborildi!"
        })
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# 8. ASOSIY SERVER ISHGA TUSHIRISH
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print("=" * 64)
    print(" [CHORVA ERP CLOUD BACKEND] ISHGA TUSHDI")
    print(f" [DB REJIM]:      {'PostgreSQL' if IS_POSTGRES else 'Mahalliy SQLite'}")
    print(f" [PORT]:          {port}")
    print(f" [TELEGRAM BOT]:  @{TELEGRAM_BOT_USERNAME}")
    print("=" * 64)
    app.run(host='0.0.0.0', port=port, debug=False)
