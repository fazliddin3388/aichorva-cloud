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
from datetime import datetime, timedelta, date
from functools import wraps

from flask import Flask, request, jsonify, make_response
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

    def get_db():
        conn = sqlite3.connect(LOCAL_DB_FILE)
        conn.row_factory = sqlite3.Row
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
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=6)
    except Exception as e:
        print(f"[TG MSG ERR]: {e}")


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


ADMIN_STATE = {}  # {chat_id: 'waiting_broadcast'}

def get_telegram_main_menu(is_admin=False, is_prayer_bot=False):
    """Botning doimiy asosiy menyu tugmalari (Admin uchun maxsus boshqaruv tugmalari bilan)"""
    if is_prayer_bot:
        kb = [
            [{"text": "🕌 Namoz vaqtlari"}, {"text": "📍 Hudud tanlash"}],
            [{"text": "🔔 Eslatmalar"}, {"text": "🐂 AI Chorva ilovasi"}],
        ]
        if is_admin:
            kb.append([{"text": "📣 Reklama yuborish"}, {"text": "📊 Baza statistikasi"}])
    else:
        kb = [
            [{"text": "🕌 Namoz vaqtlari"}, {"text": "📍 Hudud tanlash"}],
            [{"text": "🔔 Eslatmalar"}, {"text": "🐂 AI Chorva"}],
        ]
        if is_admin:
            kb.append([{"text": "📣 Reklama yuborish"}, {"text": "📊 Baza statistikasi"}])
        kb.append([{"text": "📱 Telefon raqamni ulashish", "request_contact": True}])
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
        msg = cb.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        msg_id = msg.get("message_id")

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

    # 2. Xabar (Message) kelganda
    msg = update.get("message")
    if not msg:
        return

    chat_id = msg.get("chat", {}).get("id")
    from_user = msg.get("from", {})
    user_id = from_user.get("id")
    text = (msg.get("text") or "").strip()
    contact = msg.get("contact")

    is_admin = (int(user_id) == ADMIN_ID) if user_id else False

    # 0. Admin holatini bekor qilish
    if text == "/cancel":
        ADMIN_STATE.pop(chat_id, None)
        send_telegram_msg(chat_id, "Bekor qilindi.", reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
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
        send_telegram_msg(chat_id, report, reply_markup=get_telegram_main_menu(True, is_prayer_bot), bot_token=active_token)
        return

    # 2. Admin reklama buyrug'i
    if is_admin and text in ("📣 Reklama yuborish", "/reklama", "/elon", "/broadcast"):
        ADMIN_STATE[chat_id] = "waiting_broadcast"
        instr = (
            "📢 <b>REKLAMA VA E'LON TARQATISH (ADMIN)</b>\n\n"
            "Foydalanuvchilarga yubormoqchi bo'lgan e'lon, reklama yoki yangilik matnini kiriting.\n\n"
            "✨ <b>Qayerlarda ko'rinadi:</b>\n"
            " ├ 1. Barcha Namoz boti va AI Chorva a'zolariga Telegramda DARHOL yetib boradi.\n"
            " └ 2. AI Chorva mobil ilovasi bosh sahifasida ko'rkam e'lon bo'lib chiqadi!\n\n"
            "<i>Bekor qilish uchun /cancel deb yozing.</i>"
        )
        send_telegram_msg(chat_id, instr, reply_markup={"keyboard": [[{"text": "/cancel"}]], "resize_keyboard": True}, bot_token=active_token)
        return

    # 3. Admin statistika buyrug'i
    if is_admin and text in ("📊 Baza statistikasi", "/statistika"):
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
                "╔════════════════════════════╗\n"
                "   📊 <b>TIZIM BAZASI STATISTIKASI</b>\n"
                "╚════════════════════════════╝\n\n"
                f"🕌 <b>Namoz taqvimi obunachilari:</b> <b>{total_prayer} ta</b>\n"
                f"👥 <b>Fermerlar (Foydalanuvchilar):</b> <b>{total_users} ta</b>\n"
                f"🐂 <b>Hisobdagi jonivorlar:</b> <b>{total_bulls} ta</b>\n"
                f"📢 <b>Faol e'lon va reklamalar:</b> <b>{total_ads} ta</b>\n\n"
                "🟢 <i>Ikkala Telegram bot va mobil API 100% barqaror ishlamoqda.</i>"
            )
            send_telegram_msg(chat_id, stat_text, reply_markup=get_telegram_main_menu(True, is_prayer_bot), bot_token=active_token)
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
                " └ 🐂 <b>AI Chorva</b> zamonaviy fermerlik mobil ilovasi bilan to'liq bog'langan\n\n"
                "👇 <i>Quyidagi menyu tugmalaridan birini tanlang:</i>"
            )
        else:
            welcome_text = (
                "╔════════════════════════════╗\n"
                "   🐂 <b>AI CHORVA & NAMOZ BOTI</b>\n"
                "╚════════════════════════════╝\n\n"
                f"👋 <b>Assalomu alaykum, {from_user.get('first_name', 'Hurmatli foydalanuvchi')}!</b>\n\n"
                "<b>AI Chorva</b> — zamonaviy chorvachilik tizimi va har kunlik aniq namoz taqvimi hamrohingizga xush kelibsiz!\n\n"
                "✨ <b>Asosiy imkoniyatlar:</b>\n"
                " ├ 🕌 <b>Aniq namoz taqvimi</b> — O'zbekistonning 60+ shahar va tumanlari\n"
                " ├ 🔔 <b>Azon eslatmasi</b> — Har bir namoz vaqtida avtomatik bildirishnoma\n"
                " ├ 📱 <b>AI Chorva Ilovasi</b> — 0 so'm SMS xarajat bilan telefonni tasdiqlash\n"
                " └ 📊 <b>Aqlli hisob-kitob</b> — Ferma, jonivorlar vazni va yem tahlili\n\n"
                "👇 <i>Quyidagi menyu tugmalaridan birini tanlang:</i>"
            )
        send_telegram_msg(chat_id, welcome_text, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        return

    # Namoz vaqtlari tugmasi
    if text in ("🕌 Namoz vaqtlari", "/namoz"):
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

    # Hudud tanlash
    if text in ("📍 Hudud tanlash", "📍 Hududni o'zgartirish"):
        send_telegram_msg(chat_id, "📍 <b>O'zbekiston viloyatini tanlang:</b>", reply_markup=get_regions_inline_keyboard(), bot_token=active_token)
        return

    # Eslatmalar
    if text == "🔔 Eslatmalar":
        conn = get_db()
        c = conn.cursor()
        notif_state = True
        try:
            c.execute(adapt_query("SELECT notifications FROM prayer_users WHERE telegram_id = ?"), (user_id,))
            row = c.fetchone()
            if row:
                notif_state = bool(row[0])
        finally:
            conn.close()

        status_txt = "✅ <b>Yoqilgan</b> (Azon vaqtida xabar yuboriladi)" if notif_state else "❌ <b>O'chirilgan</b>"
        btn_txt = "🔔 Eslatmani o'chirish ❌" if notif_state else "🔔 Eslatmani yoqish ✅"
        kb = {"inline_keyboard": [[{"text": btn_txt, "callback_data": "tgl_notif"}]]}
        send_telegram_msg(chat_id, f"🔔 <b>Azon bildirishnomalari:</b> {status_txt}\n\nO'zgartirish uchun pastdagi tugmani bosing:", reply_markup=kb, bot_token=active_token)
        return

    # AI Chorva ilovasi haqida
    if text in ("🐂 AI Chorva", "🐂 AI Chorva ilovasi", "ℹ️ Ilova haqida"):
        info_text = (
            "╔════════════════════════════╗\n"
            "   🐂 <b>AI CHORVA MOBIL ILOVASI</b>\n"
            "╚════════════════════════════╝\n\n"
            "<b>AI Chorva</b> — O'zbekiston chorvadorlari va fermerlari uchun yaratilgan eng mukammal mobil ilova!\n\n"
            "💡 <b>Imkoniyatlar:</b>\n"
            " • Jonivorlar hisobi, vazn dinamikasi va kunlik semirish (og'im)\n"
            " • Ombor (Sklad), ratsion va kunlik yem taqsimoti\n"
            " • Kassa, sarmoya, qarzlar va sof foyda hisobi\n"
            " • Zotlar rentabelligi va Zootexnik AI tavsiyalari\n"
            " • 🕌 Ilovada Namoz vaqtlari vidjeti (sozlamalardan o'zingiz yoqishingiz yoki o'chirishingiz mumkin!)\n"
            " • 100% Oflayn rejimda ham to'liq ishlash\n\n"
            "📲 <b>Ilovaga kirish va avtorizatsiya:</b>\n"
            "Rasmiy bot: @AIchorvabot orqali telefon raqamingizni 1 bosishda tasdiqlab kirishingiz mumkin!"
        )
        send_telegram_msg(chat_id, info_text, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
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

        raw_phone = contact.get("phone_number", "").replace("+", "").strip()
        phone = "+" + raw_phone if not raw_phone.startswith("+") else raw_phone
        first_name = from_user.get("first_name", "")
        username = from_user.get("username", "")

        auth_code = "".join(random.choices(string.digits, k=6))

        conn = get_db()
        c = conn.cursor()
        try:
            # Foydalanuvchini tekshiramiz yoki yangi ochamiz
            c.execute(adapt_query("SELECT id, full_name, farm_name FROM users WHERE phone = ?"), (phone,))
            user_row = c.fetchone()
            if not user_row:
                c.execute(adapt_query("""
                    INSERT INTO users (phone, full_name, telegram_id, telegram_username, is_verified)
                    VALUES (?, ?, ?, ?, ?) RETURNING id
                """ if IS_POSTGRES else """
                    INSERT INTO users (phone, full_name, telegram_id, telegram_username, is_verified)
                    VALUES (?, ?, ?, ?, 1)
                """), (phone, first_name, user_id, username, True if IS_POSTGRES else 1))
                if IS_POSTGRES:
                    uid = c.fetchone()[0]
                else:
                    uid = c.lastrowid
            else:
                uid = user_row[0]
                c.execute(adapt_query("UPDATE users SET telegram_id = ?, telegram_username = ?, is_verified = ? WHERE id = ?"),
                          (user_id, username, True if IS_POSTGRES else 1, uid))

            # Sessiyani tasdiqlaymiz
            jwt_token = generate_jwt(uid, phone)
            c.execute(adapt_query("""
                UPDATE auth_sessions 
                SET phone = ?, auth_code = ?, verified = ?, jwt_token = ?, user_id = ?
                WHERE telegram_id = ? OR phone = ?
            """), (phone, auth_code, True if IS_POSTGRES else 1, jwt_token, uid, user_id, phone))
            conn.commit()

            success_msg = (
                f"✅ <b>Telefon raqamingiz muvaffaqiyatli tasdiqlandi!</b>\n\n"
                f"📞 Raqam: <code>{phone}</code>\n"
                f"🔑 Bir martalik tasdiqlash kodingiz: <b>{auth_code}</b>\n\n"
                f"<i>Ushbu 6 xonali kodni AI Chorva ilovasiga kiriting yoki ilovangiz avtomatik ochiladi!</i>"
            )
            send_telegram_msg(chat_id, success_msg, reply_markup=get_telegram_main_menu(is_admin, is_prayer_bot), bot_token=active_token)
        except Exception as e:
            conn.rollback()
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
                        # Ikkala bot orqali ham eslatma jo'natamiz (foydalanuvchi qaysi botda bo'lsa ham yetib boradi)
                        if PRAYER_BOT_TOKEN:
                            send_telegram_msg(u["telegram_id"], azon_text, bot_token=PRAYER_BOT_TOKEN)
                        if CHORVA_BOT_TOKEN:
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
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{CHORVA_BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            resp = requests.get(url, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    handle_telegram_update(upd, bot_token=CHORVA_BOT_TOKEN)
        except Exception:
            time.sleep(3)
        time.sleep(0.5)


# 2. Asl Namoz Vaqtlari Boti Polling oqimi
def prayer_bot_polling_thread():
    if not PRAYER_BOT_TOKEN:
        return
    print("[TELEGRAM] Asl Namoz Vaqtlari Boti Polling ishga tushmoqda...")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{PRAYER_BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            resp = requests.get(url, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    handle_telegram_update(upd, bot_token=PRAYER_BOT_TOKEN)
        except Exception:
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
