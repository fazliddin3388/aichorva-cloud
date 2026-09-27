"""
=============================================================================
CHORVA ERP CLOUD — Ko'p Foydalanuvchili Bulutli Backend & API
=============================================================================
Xususiyatlari:
1. Render.com va bulutli serverlar uchun to'liq moslashtirilgan.
2. PostgreSQL (Render / Neon / Supabase) va SQLite qo'llab-quvvatlaydi.
3. 100% BEPUL Telegram Bot orqali telefon raqamni tasdiqlash (0 so'm SMS xarajat).
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
                version_name VARCHAR(64) DEFAULT 'v1.7',
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
                version_name TEXT DEFAULT 'v1.7',
                changelog TEXT,
                uploaded_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


        conn.commit()
        print("[DB INIT] Bulutli ma'lumotlar bazasi jadvallari muvaffaqiyatli tayyorlandi!")
    except Exception as e:
        conn.rollback()
        print(f"[DB INIT ERR]: {e}")

    finally:
        conn.close()


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
                files = {"document": (os.path.basename(document), f_obj, "application/vnd.android.package-archive")}
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


ADMIN_STATE = {}    # {chat_id: 'waiting_broadcast' | 'replying_12345' | 'waiting_apk'}
USER_STATE = {}     # {user_id: 'waiting_support'}
ADMIN_MSG_MAP = {}  # {admin_sent_msg_id: user_id}

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
            # 👑 Bosh Admin uchun to'liq boshqaruv menyusi (ro'yxatdan o'tish yoki adminga murojaat ko'rinmaydi)
            kb = [
                [{"text": "👑 ADMIN BOSHQARUV PANELI"}],
                [{"text": "📥 Ilovani yuklab olish (APK)"}, {"text": "🐂 AI Chorva haqida"}],
                [{"text": "👤 Mening profilim"}, {"text": "📊 Baza statistikasi"}],
                [{"text": "📣 Reklama / E'lon yuborish"}, {"text": "📦 Yangi APK yuklash"}],
                [{"text": "❓ Qo'llanma va Yordam"}],
            ]
        else:
            # 🌾 Oddiy fermer (foydalanuvchi) ko'rinishi
            kb = [
                [{"text": "📱 Telefon raqamni ulashish", "request_contact": True}],
                [{"text": "📥 Ilovani yuklab olish (APK)"}, {"text": "🐂 AI Chorva haqida"}],
                [{"text": "👤 Mening profilim"}, {"text": "✍️ Adminga murojaat"}],
                [{"text": "❓ Qo'llanma va Yordam"}],
            ]
    return {
        "keyboard": kb,
        "resize_keyboard": True
    }


def get_admin_panel_menu(is_prayer_bot=False):
    """Faqat Admin uchun maxsus boshqaruv paneli menyusi"""
    if is_prayer_bot:
        kb = [
            [{"text": "📣 Reklama / E'lon yuborish"}, {"text": "📊 Baza statistikasi"}],
            [{"text": "🔔 Azon eslatmasini sinash"}, {"text": "🔙 Asosiy menyuga qaytish"}],
        ]
    else:
        kb = [
            [{"text": "📣 Reklama / E'lon yuborish"}, {"text": "📊 Baza statistikasi"}],
            [{"text": "📦 Yangi APK yuklash"}, {"text": "👥 Foydalanuvchilar ro'yxati"}],
            [{"text": "🔔 Azon eslatmasini sinash"}, {"text": "🔙 Asosiy menyuga qaytish"}],
        ]
    return {
        "keyboard": kb,
        "resize_keyboard": True
    }







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

            version_name = version_match.group(0) if version_match else "v1.7"
            changelog = cap or f"Yangi rasmiy APK ilovasi ({f_name})"
            size_mb = round(f_size / (1024 * 1024), 2) if f_size else 0.0

            if not file_id:
                send_telegram_msg(
                    chat_id,
                    "⚠️ <b>Xatolik:</b> Telegram fayl identifikatorini (file_id) aniqlab bo'lmadi. Iltimos faylni qaytadan yuboring.",
                    reply_markup=get_telegram_main_menu(True, is_prayer_bot),
                    bot_token=active_token
                )
                return

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
                            version_name TEXT DEFAULT 'v1.7',
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
                            version_name VARCHAR(64) DEFAULT 'v1.7',
                            changelog TEXT,
                            uploaded_by BIGINT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                c.execute(adapt_query("""
                    INSERT INTO app_releases (file_id, file_name, file_size, version_name, changelog, uploaded_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                """), (file_id, f_name, f_size, version_name, changelog, user_id))
                conn.commit()
                print(f"[APK SUCCESS]: Saved new APK {f_name} ({size_mb} MB) version={version_name} file_id={file_id}")
            except Exception as e:
                print(f"[APK SAVE ERR]: {e}")
                traceback.print_exc()
            finally:
                conn.close()

            # Server diskida ham ChorvaERP.apk sifatida saqlab qo'yish (fon rejimida)
            try:
                threading.Thread(target=cache_apk_locally, args=(file_id, active_token), daemon=True).start()
            except Exception:
                pass

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
                "✅ <b>Serverda muvaffaqiyatli saqlandi!</b>\n\n"
                "Endi barcha foydalanuvchilar (va siz) botdagi <b>«📥 Ilovani yuklab olish (APK)»</b> "
                "tugmasini bosganda aynan siz hozir yuklagan ushbu yangi fayl yuboriladi!"
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
            send_telegram_msg(chat_id, "Javob matni bo'sh bo'lishi mumkin emas.", reply_markup=get_telegram_main_menu(True, is_prayer_bot), bot_token=active_token)
            return

        user_notification = (
            "╭────────────────────────╮\n"
            "   📬  <b>ADMINDAN JAVOB KELDI!</b>\n"
            "╰────────────────────────╯\n\n"
            f"{ans_text}\n\n"
            "────────────────────────\n"
            "💬 <i>Yana savolingiz bo'lsa, «✍️ Adminga murojaat» tugmasi orqali yozishingiz mumkin.</i>"
        )
        send_telegram_msg(reply_target_user, user_notification, bot_token=CHORVA_BOT_TOKEN)

        send_telegram_msg(
            chat_id,
            f"✅ <b>Javobingiz foydalanuvchiga (ID: <code>{reply_target_user}</code>) muvaffaqiyatli yetkazildi!</b>",
            reply_markup=get_telegram_main_menu(True, is_prayer_bot),
            bot_token=active_token
        )
        return

    # 0.2. Foydalanuvchi adminga murojaat/savol yozyaptimi?
    if USER_STATE.get(user_id) == "waiting_support":
        USER_STATE.pop(user_id, None)
        user_msg = text or msg.get("caption") or ""
        if not user_msg:
            send_telegram_msg(chat_id, "Murojaat matni bo'sh bo'lishi mumkin emas.", reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
            return

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
            f"💬 <b>Savol / Murojaat:</b>\n"
            f"«<i>{user_msg}</i>»"
        )
        reply_kb = {
            "inline_keyboard": [
                [{"text": "💬 Javob berish", "callback_data": f"reply_{user_id}"}]
            ]
        }
        res = send_telegram_msg(ADMIN_ID, admin_card, reply_markup=reply_kb, bot_token=CHORVA_BOT_TOKEN)
        if res and res.get("message_id"):
            ADMIN_MSG_MAP[res["message_id"]] = user_id

        client_confirm = (
            "✅ <b>Murojaatingiz adminga muvaffaqiyatli yetkazildi!</b>\n\n"
            "Admin tez orada savolingizni ko'rib chiqib, javob beradi. "
            "Javob xabari to'g'ridan-to'g'ri shu botingizga yetib keladi."
        )
        send_telegram_msg(chat_id, client_confirm, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return


    # 1. Agar admin reklama/e'lon yuborayotgan bo'lsa
    if is_admin and ADMIN_STATE.get(chat_id) == "waiting_broadcast":
        ADMIN_STATE.pop(chat_id, None)
        ad_text = text or msg.get("caption") or ""
        if not ad_text:
            send_telegram_msg(chat_id, "Xabar matni bo'sh bo'lishi mumkin emas.", reply_markup=get_telegram_main_menu(True, is_prayer_bot), bot_token=active_token)
            return

        # 1.1. Mobil ilova uchun e'lonlar bazasiga saqlaymiz
        conn = get_db()
        c = conn.cursor()
        first_line = ad_text.split("\n")[0][:60]
        try:
            c.execute(adapt_query("""
                INSERT INTO advertisements (title, description, category, is_active)
                VALUES (?, ?, 'broadcast', ?)
            """), (first_line, ad_text, True if IS_POSTGRES else 1))
            conn.commit()
        except Exception as e:
            print(f"[SAVE AD ERR]: {e}")

        # 1.2. Barcha Telegram foydalanuvchilariga tarqatamiz (Ikkala bot a'zolariga o'z botlaridan jo'natish)
        chorva_recipients = set()
        prayer_recipients = set()
        try:
            c_dict = dict_cursor(conn)
            c_dict.execute(adapt_query("SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL"))
            for r in c_dict.fetchall():
                if r["telegram_id"]: chorva_recipients.add(r["telegram_id"])

            c_dict.execute(adapt_query("SELECT telegram_id FROM prayer_users WHERE telegram_id IS NOT NULL"))
            for r in c_dict.fetchall():
                if r["telegram_id"]: prayer_recipients.add(r["telegram_id"])
        finally:
            conn.close()

        sent_count = 0
        broadcast_msg = f"📢 <b>RASMIY E'LON:</b>\n\n{ad_text}"

        # 1. Asl Namoz boti a'zolariga
        if PRAYER_BOT_TOKEN:
            for rid in prayer_recipients:
                try:
                    send_telegram_msg(rid, broadcast_msg, bot_token=PRAYER_BOT_TOKEN)
                    sent_count += 1
                    time.sleep(0.04)
                except Exception:
                    pass

        # 2. AI Chorva boti a'zolariga
        if CHORVA_BOT_TOKEN:
            for rid in (chorva_recipients - prayer_recipients):
                try:
                    send_telegram_msg(rid, broadcast_msg, bot_token=CHORVA_BOT_TOKEN)
                    sent_count += 1
                    time.sleep(0.04)
                except Exception:
                    pass

        report = (
            f"✅ <b>E'lon / Reklama muvaffaqiyatli tarqatildi!</b>\n\n"
            f"👥 Telegram orqali yetkazildi: <b>{sent_count} ta</b> foydalanuvchiga\n"
            f"📱 <b>AI Chorva</b> mobil ilovasiga ham yangi e'lon sifatida joylandi!"
        )
        send_telegram_msg(chat_id, report, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
        return

    # 2. Admin reklama buyrug'i
    if is_admin and text in ("📣 Reklama / E'lon yuborish", "📣 Reklama yuborish", "/reklama", "/elon", "/broadcast"):
        ADMIN_STATE[chat_id] = "waiting_broadcast"
        instr = (
            "╭────────────────────────╮\n"
            "   📢  <b>REKLAMA VA E'LON TARQATISH</b>\n"
            "╰────────────────────────╯\n\n"
            "Foydalanuvchilarga yubormoqchi bo'lgan e'lon yoki reklama matnini kiriting.\n\n"
            "✨ <b>Xabar qayerlarga yetkaziladi:</b>\n"
            " ├ 1. Barcha Namoz boti va AI Chorva Telegram obunachilariga DARHOL boradi;\n"
            " └ 2. AI Chorva mobil ilovasi bosh sahifasida qulay e'lon kartochkasi bo'lib chiqadi!\n\n"
            "<i>Bekor qilish uchun: «❌ Bekor qilish» tugmasini bosing.</i>"
        )
        send_telegram_msg(chat_id, instr, reply_markup={"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}, bot_token=active_token)
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

        if session_id:
            conn = get_db()
            c = conn.cursor()
            try:
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
                welcome_text = (
                    "╔════════════════════════════╗\n"
                    "   👑 <b>BOSH ADMIN BOSHQARUVI</b>\n"
                    "╚════════════════════════════╝\n\n"
                    f"👋 <b>Assalomu alaykum, Bosh Admin — {from_user.get('first_name', 'Fazliddin')}!</b>\n\n"
                    "Siz <b>AI Chorva</b> tizimining boshqaruvchisiz. Tizim sizni to'liq tanidi!\n\n"
                    "👑 <b>Admin boshqaruv imkoniyatlari:</b>\n"
                    " ├ 👑 <b>Admin Paneli:</b> Reklama, statistika va yangi versiyalar\n"
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
                    "📲 <b>Ilovaga 0 so'm SMS xarajat bilan kirish:</b>\n"
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
                " • 📣 <b>Reklama / E'lon yuborish:</b> Botlar va ilovaga bir vaqtda xabar tarqatish\n"
                " • 📊 <b>Baza statistikasi:</b> Foydalanuvchilar, fermerlar va jonivorlar soni\n"
                " • 📦 <b>Yangi APK yuklash:</b> Mobil ilovani yangilash\n"
                " • 👥 <b>Foydalanuvchilar ro'yxati:</b> Ro'yxatdan o'tgan fermerlar\n"
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

    if is_admin and text in ("👥 Foydalanuvchilar ro'yxati", "👥 Foydalanuvchilar", "/users"):
        conn = get_db()
        c = dict_cursor(conn)
        try:
            c.execute(adapt_query("SELECT id, phone, full_name, farm_name, is_verified FROM users ORDER BY id DESC LIMIT 15"))
            rows = c.fetchall()
            if rows:
                u_list = "📋 <b>Oxirgi ro'yxatdan o'tgan fermerlar:</b>\n\n"
                for u in rows:
                    u_list += f"▫️ <b>#{u['id']}</b> | <b>{u['full_name'] or 'Nomsiz'}</b>\n    📞 <code>{u['phone']}</code> | 🏡 {u['farm_name'] or 'Mavjud emas'}\n"
            else:
                u_list = "Hozircha ro'yxatdan o'tgan fermerlar mavjud emas."
            send_telegram_msg(chat_id, u_list, reply_markup=get_admin_panel_menu(is_prayer_bot), bot_token=active_token)
        finally:
            conn.close()
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
        conn = get_db()
        c = dict_cursor(conn)
        latest_apk = None
        try:
            c.execute(adapt_query("SELECT file_id, file_name, file_size, version_name, changelog FROM app_releases ORDER BY id DESC LIMIT 1"))
            latest_apk = c.fetchone()
        finally:
            conn.close()

        if latest_apk and latest_apk.get("file_id"):
            file_id = latest_apk["file_id"]
            f_name = latest_apk.get("file_name") or "ChorvaERP.apk"
            f_size = round((latest_apk.get("file_size") or 0) / (1024 * 1024), 2)
            v_name = latest_apk.get("version_name") or "v1.7"
            ch_log = latest_apk.get("changelog") or ""

            cap = (
                "╭────────────────────────╮\n"
                "   📲  <b>AI CHORVA RASMIY APK</b>\n"
                "╰────────────────────────╯\n\n"
                f"📁 <b>Fayl:</b> <code>{f_name}</code>\n"
                f"🏷 <b>Versiya:</b> <b>{v_name}</b>\n"
                f"📦 <b>Hajmi:</b> <b>{f_size} MB</b>\n"
            )
            if ch_log and ch_log != v_name:
                cap += f"📝 <b>Izoh / Yangiliklar:</b>\n<i>{ch_log}</i>\n"
            cap += (
                "\n────────────────────────\n"
                "💡 <b>O'rnatish yo'riqnomasi:</b>\n"
                "1️⃣ Yuqoridagi fayl ustiga bosib, telefoningizga o'rnating;\n"
                "2️⃣ Ilovani ochgach, ushbu botdagi <b>«📱 Telefon raqamni ulashish»</b> tugmasi orqali olingan kod bilan tizimga kiring!"
            )
            res = send_telegram_document(chat_id, file_id, caption=cap, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
            if res:
                return

        # 2. Agar Telegram file_id bilan yuborish o'tmasa, server diskidagi mahalliy ChorvaERP.apk ni tekshiramiz
        local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk")
        if os.path.exists(local_path):
            f_size = round(os.path.getsize(local_path) / (1024 * 1024), 2)
            cap = (
                "╭────────────────────────╮\n"
                "   📲  <b>AI CHORVA RASMIY APK</b>\n"
                "╰────────────────────────╯\n\n"
                "📁 <b>Fayl:</b> <code>ChorvaERP.apk</code>\n"
                f"📦 <b>Hajmi:</b> <b>{f_size} MB</b>\n"
                "🏷 <b>Versiya:</b> <b>Rasmiy Barqaror</b>\n\n"
                "💡 <b>O'rnatish yo'riqnomasi:</b>\n"
                "1️⃣ Yuqoridagi fayl ustiga bosib, telefoningizga o'rnating;\n"
                "2️⃣ Ilovani ochgach, ushbu botdagi <b>«📱 Telefon raqamni ulashish»</b> tugmasi orqali olingan kod bilan tizimga kiring!"
            )
            res2 = send_telegram_document(chat_id, local_path, caption=cap, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
            if res2:
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
            "<i>Fayl kelishi bilan u darhol serverda saqlanadi va barcha foydalanuvchilar yuklab olishi uchun avtomatik faollashadi!</i>\n\n"
            "<i>Bekor qilish uchun: «❌ Bekor qilish» tugmasini bosing.</i>"
        )
        send_telegram_msg(chat_id, prompt_apk, reply_markup={"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}, bot_token=active_token)
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
            "└ Pastdagi <b>«📱 Telefon raqamni ulashish»</b> tugmasini bosing. Bot sizga 6 xonali maxsus kod beradi. Shu kodni ilovaga kiritib, 0 so'm xarajat bilan kirasiz!\n\n"
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
        USER_STATE[user_id] = "waiting_support"
        prompt = (
            "╭────────────────────────╮\n"
            "   ✍️  <b>ADMINGA MUROJAAT</b>\n"
            "╰────────────────────────╯\n\n"
            "AI Chorva bo'yicha savolingiz, taklifingiz yoki tushunmagan joyingiz bo'lsa, "
            "batafsil yozib yuboring.\n\n"
            "📩 Xabaringiz to'g'ridan-to'g'ri adminga boradi va admin javob berishi bilan javob shu yerga keladi!\n\n"
            "<i>Bekor qilish uchun: «❌ Bekor qilish» tugmasini bosing.</i>"
        )
        send_telegram_msg(chat_id, prompt, reply_markup={"keyboard": [[{"text": "❌ Bekor qilish"}]], "resize_keyboard": True}, bot_token=active_token)
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


@app.route('/download/ChorvaERP.apk', methods=['GET'])
@app.route('/api/app/download', methods=['GET'])
def download_latest_apk():
    """Mobil ilovani to'g'ridan-to'g'ri brauzer orqali yuklab olish"""
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk")
    if os.path.exists(local_path):
        return send_file(local_path, as_attachment=True, download_name="ChorvaERP.apk", mimetype="application/vnd.android.package-archive")
    return redirect("https://github.com/fazliddin3388/aichorva-cloud/releases", code=302)


@app.route('/api/app/latest', methods=['GET'])
def get_latest_app_release():
    """Eng so'nggi mobil ilova versiyasi haqida ma'lumot"""
    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("SELECT id, file_name, file_size, version_name, changelog, created_at FROM app_releases ORDER BY id DESC LIMIT 1"))
        row = c.fetchone()
        local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChorvaERP.apk")
        has_local = os.path.exists(local_path)
        return jsonify({
            "status": "success",
            "release": dict(row) if row else None,
            "has_local_apk": has_local,
            "download_url": "/download/ChorvaERP.apk"
        })
    finally:
        conn.close()


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

    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("SELECT verified, jwt_token, auth_code, user_id, phone, expires_at FROM auth_sessions WHERE session_id = ?"), (session_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Sessiya topilmadi yoki eskirgan"}), 404

        # Sessiya muddatini tekshirish (15 daqiqa)
        if row.get("expires_at"):
            exp_dt = row["expires_at"]
            if isinstance(exp_dt, str):
                try:
                    exp_dt = datetime.strptime(exp_dt, "%Y-%m-%d %H:%M:%S.%f")
                except Exception:
                    pass
            if isinstance(exp_dt, datetime) and exp_dt < datetime.utcnow():
                return jsonify({"status": "error", "message": "Tasdiqlash kodi muddati tugagan. Qaytadan urinib ko'ring."}), 400

        # Kod to'g'riligini tekshirish
        if not row.get("auth_code") or not row.get("user_id"):
            return jsonify({"status": "error", "message": "Iltimos, avval Telegram botda telefon raqamingizni ulashing!"}), 400

        if row["auth_code"] == code:
            u_cur = dict_cursor(conn)
            u_cur.execute(adapt_query("SELECT id, phone, full_name, farm_name FROM users WHERE id = ?"), (row["user_id"],))
            user_data = u_cur.fetchone()
            token = row["jwt_token"] or generate_jwt(row["user_id"], row["phone"])

            # 🛡️ XAVFSIZLIK FILTRI 2: Kodni bir martalik qilish (qayta ishlatib bo'lmasligi uchun tozalash)
            c.execute(adapt_query("UPDATE auth_sessions SET auth_code = NULL WHERE session_id = ?"), (session_id,))
            conn.commit()

            return jsonify({
                "status": "success",
                "token": token,
                "user": dict(user_data) if user_data else {"id": row["user_id"], "phone": row["phone"]}
            })
        return jsonify({"status": "error", "message": "Noto'g'ri tasdiqlash kodi"}), 400
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

            c.execute(adapt_query("SELECT id FROM bulls WHERE user_id = ? AND tag_id = ?"), (user_id, tag_id))
            ex = c.fetchone()
            if ex:
                bid = ex[0]
                c.execute(adapt_query("""
                    UPDATE bulls 
                    SET animal_type=?, breed=?, buy_date=?, buy_price=?, initial_weight=?,
                        current_weight=?, status=?, sold_date=?, sold_weight=?, sold_price_total=?, notes=?
                    WHERE id = ? AND user_id = ?
                """), (atype, breed, bdate, bprice, iweight, cweight, status, sdate, sweight, sprice, notes, bid, user_id))
            else:
                c.execute(adapt_query("""
                    INSERT INTO bulls (user_id, tag_id, animal_type, breed, buy_date, buy_price, initial_weight, current_weight, status, sold_date, sold_weight, sold_price_total, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
                """ if IS_POSTGRES else """
                    INSERT INTO bulls (user_id, tag_id, animal_type, breed, buy_date, buy_price, initial_weight, current_weight, status, sold_date, sold_weight, sold_price_total, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (user_id, tag_id, atype, breed, bdate, bprice, iweight, cweight, status, sdate, sweight, sprice, notes))
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

        conn.commit()

        # PULL: Foydalanuvchining bulutdagi barcha yangi ma'lumotlarini qaytarish
        pull_data = {}
        c_dict = dict_cursor(conn)

        c_dict.execute(adapt_query("SELECT tag_id, animal_type, breed, buy_date, buy_price, initial_weight, current_weight, status, sold_date, sold_weight, sold_price_total, notes FROM bulls WHERE user_id = ?"), (user_id,))
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


# ═════════════════════════════════════════════════════════════════════════════
# 7. BILDIRISHNOMALAR (FCM PUSH) VA REKLAMA/E'LONLAR TIZIMI
# ═════════════════════════════════════════════════════════════════════════════
@app.route('/api/ads/active', methods=['GET'])
def get_active_ads():
    """Mobil ilovada ko'rsatiladigan faol reklama bannerlari va e'lonlar"""
    conn = get_db()
    c = dict_cursor(conn)
    try:
        c.execute(adapt_query("SELECT id, title, image_url, link_url, description, category FROM advertisements WHERE is_active = ? ORDER BY id DESC LIMIT 10"), (True if IS_POSTGRES else 1,))
        ads = [dict(r) for r in c.fetchall()]
        return jsonify({"status": "success", "ads": ads})
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
