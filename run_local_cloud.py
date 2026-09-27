"""
CHORVA ERP CLOUD — Lokal Sinov Skripti
Kompyuterda serverni sinash uchun ishga tushiring:
python run_local_cloud.py
"""
import os
import sys

# Standart muhit o'zgaruvchilari
os.environ.setdefault("PORT", "5000")
os.environ.setdefault("JWT_SECRET", "test-secret-key-123")

from server import app

if __name__ == "__main__":
    print("=" * 60)
    print(" [CHORVA CLOUD LOCAL TEST]")
    print(" Manzil: http://localhost:5000")
    print(" Baza:   chorva_cloud.db (SQLite)")
    print(" To'xtatish uchun: Ctrl + C")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
