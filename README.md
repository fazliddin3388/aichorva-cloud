# 🌐 AI CHORVA CLOUD — Render & Telegram Bot Serveri (@AIchorvabot)

Ushbu papka **AI Chorva** loyihasining **bulutli, ko'p foydalanuvchili (Multi-tenant)** backend serveri hisoblanadi. 

U [Render.com](https://dashboard.render.com/) orqali **mutlaqo bepul** ishga tushirishga, **0 so'm xarajat bilan Telegram orqali telefon raqamni tasdiqlashga** hamda **O'zbekistonning 60+ shahar va tumanlari uchun kundalik namoz taqvimi va azon eslatmalarini yuborishga** to'liq moslashtirilgan.

---

## 🎯 Asosiy Afzalliklari:
1. **0 so'm SMS xarajat:** Fermerlar SMS kutib o'tirmaydi va siz SMS provayderlarga pul to'lamaysiz. Barcha tasdiqlash Telegram-dagi rasmiy `[ 📱 Telefon raqamni ulashish ]` tugmasi orqali 1 soniyada bepul bajariladi.
2. **🕌 Namoz Vaqtlari & Azon Eslatmalari:**
   - 12 ta viloyat va 60+ shahar/tumanlar bo'yicha aniq kunlik taqvim.
   - Birlamchi islomapi.uz va zaxira Aladhan API (100% uzluksiz ishlaydi).
   - Bot har bir namoz vaqtida avtomatik azon xabarnomasini yuboradi.
   - Mobil ilovada esa foydalanuvchi xohishiga ko'ra yoqiladi yoki o'chiriladi ("xoxlasa chiqadi, xoxlasa chiqmaydi")!
3. **Ko'p foydalanuvchilik (Multi-tenant):** Har bir fermer o'z shaxsiy hisobiga ega bo'ladi, ma'lumotlar bir-biriga aralashmaydi.
4. **Doimiy saqlanish:** Foydalanuvchi telefonini yo'qotsa yoki yangilasayotganda ham ma'lumotlar bulutdan to'liq tiklanadi.
5. **Reklama va Bildirishnomalar:** Fermerlarga ozuqa, go'sht bozorlari, vaksinalar bo'yicha maqsadli reklama bannerlari va xabarlar chiqarish imkoniyati.

---

## 🚀 QADAM-BA-QADAM ISHGA TUSHIRISH QO'LLANMASI:

### 1-QADAM: Telegram Bot Sozlamalari
Botingiz allaqachon tayyor:
* **Bot Username:** `@AIchorvabot` (https://t.me/AIchorvabot)
* **Bot Token:** `8863497497:AAE3VAD84pR6Av4nzBaJmGjhe6Thh397OJU`
* **Admin ID:** `225011967`

---

### 2-QADAM: Ushbu `cloud/` papkasini GitHub-ga yuklash
1. [GitHub.com](https://github.com/) ga kiring va yangi repozitoriy oching (masalan: `aichorva-cloud`).
2. Kompyuteringiz terminalida (shu `cloud/` papkasi ichida) quyidagi buyruqlarni bajaring:
```bash
git init
git add .
git commit -m "AI Chorva Cloud & Prayer Server"
git branch -M main
git remote add origin https://github.com/USERNAME/aichorva-cloud.git
git push -u origin main
```

---

### 3-QADAM: Render.com da bepul Web Service ochish
1. [dashboard.render.com](https://dashboard.render.com/) ga kiring (GitHub orqali kirish mumkin).
2. **"New +"** tugmasini bosing -> **"Web Service"** ni tanlang.
3. 2-qadamda ochgan GitHub repozitoriyangizni (`aichorva-cloud`) tanlang.
4. Quyidagi parametrlarni kiriting:
   * **Name:** `aichorva-api` (yoki o'zingizga yoqqan nom)
   * **Region:** `Frankfurt (EU Central)` yoki `Singapore`
   * **Branch:** `main`
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`
   * **Instance Type:** `Free` (bepul)
5. **Environment Variables** (Muhit o'zgaruvchilari) bo'limiga quyidagilarni qo'shing:
   * `CHORVA_BOT_TOKEN` = `8863497497:AAE3VAD84pR6Av4nzBaJmGjhe6Thh397OJU`
   * `PRAYER_BOT_TOKEN` = `8685776741:AAGFbM6DapVTTcCEczoue01lOj2nB4ag440`
   * `ADMIN_ID` = `225011967`
   * `JWT_SECRET` = `chorva_secret_key_2026_uz`
6. Pastdagi **"Create Web Service"** tugmasini bosing!
7. Render 1-2 daqiqada serverni o'rnatib ishga tushiradi va sizga bepul HTTPS manzil beradi:
   👉 Masalan: `https://aichorva-api.onrender.com`

---

### 4-QADAM (Ixtiyoriy, tavsiya etiladi): Bepul PostgreSQL bazasi ulash
Render ichida **"New +"** -> **"PostgreSQL"** tanlang:
* Bepul (Free) rejani tanlang.
* Yaratilgandan so'ng uning **"Internal Database URL"** manzilini nusxalang va yuqoridagi Web Service-ingizning `DATABASE_URL` parametriga qo'ying.
* Shunda ma'lumotlar Render-da umrbod mustahkam bazada saqlanadi!

---

### 5-QADAM: Mobil Ilovani Bulutga Ulash
Fermerlar ilovasida Sozlamalardagi Kompyuter IP o'rniga sizning Render domeningiz yoziladi:
👉 `https://chorva-api.onrender.com`

Fermer ilovada **"Telegram orqali kirish"** tugmasini bosganda, unga Telegram ochilib, raqamini tasdiqlaydi va barcha ma'lumotlar bulutga avtomatik sinxronlanadi!
