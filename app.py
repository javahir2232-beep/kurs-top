"""Kurstop.uz - bitta faylli sayt (Flask). Sayt HTML kodi ham shu fayl ichida.

Render'da: PostgreSQL (DATABASE_URL). Kompyuterda: SQLite (kurstop.db).
Mahalliy ishga tushirish:  pip install -r requirements.txt  &&  python app.py
"""
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from flask import Flask, Response, g, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DATABASE_URL)
DB_PATH = os.environ.get("DB_PATH", "kurstop.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
SEED_DEMO = os.environ.get("SEED_DEMO", "1") == "1"

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row

    IntegrityErrors = (psycopg.IntegrityError,)
else:
    IntegrityErrors = (sqlite3.IntegrityError,)

app = Flask(__name__)
# Render proksi orqasida ishlaydi: haqiqiy IP manzilni olish uchun
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tutors (
    id {PK},
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    location TEXT NOT NULL,
    format TEXT NOT NULL,
    price INTEGER NOT NULL,
    experience TEXT DEFAULT '',
    badge TEXT,
    base_rating REAL DEFAULT 0,
    base_reviews INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    UNIQUE (name, subject)
);
CREATE TABLE IF NOT EXISTS bookings (
    id {PK},
    tutor_id INTEGER NOT NULL REFERENCES tutors(id),
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    note TEXT DEFAULT '',
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id {PK},
    tutor_id INTEGER NOT NULL REFERENCES tutors(id),
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    text TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (tutor_id, phone)
);
CREATE TABLE IF NOT EXISTS tutor_applications (
    id {PK},
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    subject TEXT NOT NULL,
    created_at TEXT NOT NULL
)
""".replace("{PK}", "SERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT")

# (name, subject, location, format, price, experience, badge, base_rating, base_reviews)
# Namuna ma'lumot. Haqiqiy repetitorlar bilan almashtiring (README ga qarang).
SEED = [
    ('Dilnoza Rahimova', 'Matematika', 'Toshkent', 'onlayn', 120000, '6 yil tajriba', 'Top Repetitor', 4.9, 42),
    ('Malika Karimova', 'Ingliz tili', 'Samarqand', 'gibrid', 150000, '8 yil tajriba (IELTS 8.5)', 'Mashhur', 5.0, 58),
    ('Jahongir Olimov', 'Fizika', "Farg'ona", 'oflayn', 100000, '4 yil tajriba', None, 4.8, 29),
    ('Elena Smirnova', 'Ona tili', 'Toshkent', 'onlayn', 110000, '5 yil tajriba', None, 4.9, 35),
    ('Sardor Qodirov', 'Kimyo', 'Namangan', 'oflayn', 90000, '3 yil tajriba', None, 4.7, 19),
    ("Gulnora Yo'ldosheva", 'Biologiya', 'Buxoro', 'onlayn', 100000, '7 yil tajriba', 'Tavsiya etiladi', 4.9, 41),
]


# ---------- Sayt sahifasi (HTML) ----------
INDEX_HTML = r'''<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Kurstop.uz — Malakali repetitorlarni qidirish va topish platformasi</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com/3.4.17"></script>
    <!-- FontAwesome Icons CDN -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- Google Fonts: Inter -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Inter', 'sans-serif'],
                    },
                    colors: {
                        brand: {
                            50: '#eef2ff',
                            100: '#e0e7ff',
                            500: '#6366f1',
                            600: '#4f46e5',
                            700: '#4338ca',
                            900: '#312e81',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        .glass-card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
        }
        .animate-fade-in {
            animation: fadeIn 0.3s ease-out forwards;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen flex flex-col justify-between">

    <!-- HEADER / NAVIGATION -->
    <header class="sticky top-0 z-40 bg-white/80 backdrop-blur-md border-b border-slate-200">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex items-center justify-between h-16">
                <!-- Logo -->
                <div class="flex items-center gap-3 cursor-pointer" onclick="resetFilters()">
                    <div class="w-10 h-10 rounded-xl bg-brand-600 text-white flex items-center justify-center font-black text-xl shadow-md shadow-brand-500/20">
                        K
                    </div>
                    <div>
                        <span class="text-2xl font-extrabold bg-gradient-to-r from-brand-600 to-indigo-800 bg-clip-text text-transparent">
                            Kurstop.uz
                        </span>
                        <span class="hidden sm:inline-block text-xs font-semibold px-2 py-0.5 rounded-full bg-brand-50 text-brand-700 border border-brand-100 ml-2">
                            Beta
                        </span>
                    </div>
                </div>

                <!-- Navigation Links / Actions -->
                <div class="flex items-center gap-3 sm:gap-4">
                    <span class="hidden md:inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200">
                        <i class="fa-solid fa-headset text-emerald-500"></i>
                        24/7 Qo'llab-quvvatlash
                    </span>
                    <button onclick="openRegisterModal()" class="inline-flex items-center gap-2 bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition duration-200 shadow-sm shadow-brand-500/30">
                        <i class="fa-solid fa-chalkboard-user"></i>
                        <span class="hidden sm:inline">Repetitor bo'lib qo'shilish</span>
                        <span class="sm:hidden">Qo'shilish</span>
                    </button>
                </div>
            </div>
        </div>
    </header>

    <!-- HERO SECTION -->
    <section class="relative bg-gradient-to-b from-indigo-900 via-brand-900 to-slate-900 text-white py-16 lg:py-20 overflow-hidden">
        <div class="absolute inset-0 opacity-10 bg-[radial-gradient(#fff_1px,transparent_1px)] [background-size:16px_16px]"></div>
        
        <div class="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <h1 class="text-3xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-tight max-w-4xl mx-auto mb-4">
                Kelajagingiz uchun eng yaxshi <span class="text-indigo-300">repetitorlarni</span> toping
            </h1>
            <p class="text-slate-300 text-base sm:text-lg max-w-2xl mx-auto mb-8 font-light">
                Fanlar, hududlar va mos narxlar bo'yicha eng saralangan repetitorlar katalogi. O'zingizga maqul o'qituvchini soniyalar ichida tanlang.
            </p>

            <!-- SEARCH & FILTER BOX -->
            <div class="glass-card max-w-4xl mx-auto rounded-2xl p-4 sm:p-5 shadow-2xl text-slate-800 border border-white/20">
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                    
                    <!-- Search Input -->
                    <div class="relative">
                        <i class="fa-solid fa-magnifying-glass absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"></i>
                        <input type="text" id="searchInput" oninput="applyFilters()" placeholder="O'qituvchi ismi yoki fan..." class="w-full pl-10 pr-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 font-medium">
                    </div>

                    <!-- Subject Filter -->
                    <div class="relative">
                        <i class="fa-solid fa-book-open absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"></i>
                        <select id="subjectFilter" onchange="applyFilters()" class="w-full pl-10 pr-8 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 font-medium appearance-none cursor-pointer">
                            <option value="">Barcha fanlar</option>
                            <option value="Matematika">Matematika</option>
                            <option value="Ingliz tili">Ingliz tili</option>
                            <option value="Fizika">Fizika</option>
                            <option value="Ona tili">Ona tili va Adabiyot</option>
                            <option value="Kimyo">Kimyo</option>
                            <option value="Biologiya">Biologiya</option>
                            <option value="Tarix">Tarix</option>
                        </select>
                        <i class="fa-solid fa-chevron-down absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 text-xs pointer-events-none"></i>
                    </div>

                    <!-- Location Filter -->
                    <div class="relative">
                        <i class="fa-solid fa-location-dot absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"></i>
                        <select id="locationFilter" onchange="applyFilters()" class="w-full pl-10 pr-8 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 font-medium appearance-none cursor-pointer">
                            <option value="">Barcha hududlar</option>
                            <option value="Toshkent">Toshkent shahri</option>
                            <option value="Samarqand">Samarqand</option>
                            <option value="Farg'ona">Farg'ona</option>
                            <option value="Andijon">Andijon</option>
                            <option value="Namangan">Namangan</option>
                            <option value="Buxoro">Buxoro</option>
                        </select>
                        <i class="fa-solid fa-chevron-down absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 text-xs pointer-events-none"></i>
                    </div>

                    <!-- Format Filter -->
                    <div class="relative">
                        <i class="fa-solid fa-laptop-house absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"></i>
                        <select id="formatFilter" onchange="applyFilters()" class="w-full pl-10 pr-8 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 font-medium appearance-none cursor-pointer">
                            <option value="">Barcha formatlar</option>
                            <option value="onlayn">Onlayn</option>
                            <option value="oflayn">Oflayn</option>
                            <option value="gibrid">Gibrid</option>
                        </select>
                        <i class="fa-solid fa-chevron-down absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 text-xs pointer-events-none"></i>
                    </div>

                </div>
            </div>
        </div>
    </section>

    <!-- MAIN CATALOG SECTION -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 flex-grow w-full">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
            <div>
                <h2 class="text-2xl font-bold text-slate-900">Topilgan repetitorlar</h2>
                <p class="text-sm text-slate-500" id="resultCount">Jami 6 ta ta'lim beruvchi ko'rsatilmoqda</p>
            </div>

            <!-- Sorting -->
            <div class="flex items-center gap-2 self-end sm:self-auto">
                <span class="text-xs font-semibold text-slate-500">Saralash:</span>
                <select id="sortSelect" onchange="applyFilters()" class="bg-white border border-slate-200 text-xs font-semibold py-2 px-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500">
                    <option value="default">Tavsiya etilgan</option>
                    <option value="rating">Yuqori reyting</option>
                    <option value="price-low">Arzonroq</option>
                    <option value="price-high">Qimmatroq</option>
                </select>
            </div>
        </div>

        <!-- TUTOR GRID -->
        <div id="tutorsContainer" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <!-- Tutors loaded via JavaScript -->
        </div>

        <!-- EMPTY STATE -->
        <div id="emptyState" class="hidden text-center py-16 bg-white rounded-2xl border border-slate-200 shadow-sm">
            <div class="w-16 h-16 bg-slate-100 text-slate-400 rounded-full flex items-center justify-center mx-auto mb-4 text-2xl">
                <i class="fa-solid fa-user-slash"></i>
            </div>
            <h3 class="text-lg font-bold text-slate-800 mb-1">Hech qanday repetitor topilmadi</h3>
            <p class="text-sm text-slate-500 mb-6 max-w-md mx-auto">Qidiruv yoki filtr parametrlarini o'zgartirib ko'ring.</p>
            <button onclick="resetFilters()" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-lg transition">
                Filtrlarni tozalash
            </button>
        </div>
    </main>

    <!-- HOW IT WORKS -->
    <section class="bg-white border-t border-slate-200 py-14">
        <div class="max-w-5xl mx-auto px-4 sm:px-6 text-center">
            <h2 class="text-2xl font-bold text-slate-900 mb-2">Qanday ishlaydi?</h2>
            <p class="text-sm text-slate-500 mb-10">Uch oddiy qadamda o'zingizga mos repetitorni toping</p>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-6 text-left">
                <div class="p-5 rounded-2xl bg-slate-50 border border-slate-200">
                    <div class="w-11 h-11 rounded-xl bg-brand-600 text-white flex items-center justify-center mb-3"><i class="fa-solid fa-magnifying-glass"></i></div>
                    <h3 class="font-bold text-slate-900 mb-1">1. Qidiring</h3>
                    <p class="text-xs text-slate-500">Fan, hudud, format va narx bo'yicha filtrlang.</p>
                </div>
                <div class="p-5 rounded-2xl bg-slate-50 border border-slate-200">
                    <div class="w-11 h-11 rounded-xl bg-emerald-600 text-white flex items-center justify-center mb-3"><i class="fa-solid fa-star"></i></div>
                    <h3 class="font-bold text-slate-900 mb-1">2. Solishtiring</h3>
                    <p class="text-xs text-slate-500">Reyting, izohlar va tajribaga qarab tanlang.</p>
                </div>
                <div class="p-5 rounded-2xl bg-slate-50 border border-slate-200">
                    <div class="w-11 h-11 rounded-xl bg-amber-500 text-white flex items-center justify-center mb-3"><i class="fa-solid fa-calendar-check"></i></div>
                    <h3 class="font-bold text-slate-900 mb-1">3. Yoziling</h3>
                    <p class="text-xs text-slate-500">Ariza qoldiring, repetitor o'zi bog'lanadi.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- FOOTER -->
    <footer class="bg-slate-900 text-slate-400 py-10 border-t border-slate-800">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center sm:text-left flex flex-col sm:flex-row justify-between items-center gap-4">
            <div>
                <span class="text-xl font-bold text-white">Kurstop.uz</span>
                <p class="text-xs text-slate-500 mt-1">© 2026 Kurstop Inc. Barcha huquqlar himoyalangan.</p>
            </div>
            <div class="flex items-center gap-6 text-sm font-medium">
                <span class="hover:text-white transition cursor-pointer">Biz haqimizda</span>
                <span class="hover:text-white transition cursor-pointer">Xizmat ko'rsatish shartlari</span>
                <span class="hover:text-white transition cursor-pointer">Aloqa</span>
            </div>
        </div>
    </footer>

    <!-- MODAL 1: BOOK LESSON -->
    <div id="bookModal" class="fixed inset-0 z-50 hidden bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
        <div class="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl relative animate-fade-in">
            <button onclick="closeModal('bookModal')" class="absolute top-4 right-4 w-8 h-8 rounded-full bg-slate-100 text-slate-500 hover:bg-slate-200 flex items-center justify-center transition">
                <i class="fa-solid fa-xmark"></i>
            </button>

            <div class="flex items-center gap-3 mb-4">
                <div class="w-10 h-10 rounded-xl bg-brand-50 text-brand-600 flex items-center justify-center font-bold">
                    <i class="fa-solid fa-calendar-check"></i>
                </div>
                <div>
                    <h3 class="text-lg font-bold text-slate-900">Darsga yozilish</h3>
                    <p class="text-xs text-slate-500" id="modalTutorName">Repetitor bilan bog'lanish</p>
                </div>
            </div>

            <form onsubmit="handleBookSubmit(event)" class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Ism va Familiyangiz</label>
                    <input type="text" id="studentName" required placeholder="Masalan: Jamshid Aliyev" class="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-brand-500 outline-none">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Telefon raqamingiz</label>
                    <input type="tel" id="studentPhone" required placeholder="+998 (90) 123-45-67" class="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-brand-500 outline-none">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Izoh yoki Qulay vaqt (ixtiyoriy)</label>
                    <textarea id="studentNote" rows="2" placeholder="Masalan: Kechki soat 18:00 dan keyin ma'qul" class="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-brand-500 outline-none resize-none"></textarea>
                </div>
                <button type="submit" class="w-full py-3 bg-brand-600 hover:bg-brand-700 text-white font-bold text-sm rounded-xl transition shadow-md shadow-brand-500/20">
                    Arizani yuborish
                </button>
            </form>
        </div>
    </div>

    <!-- MODAL 2: REGISTER AS TUTOR -->
    <div id="registerModal" class="fixed inset-0 z-50 hidden bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
        <div class="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl relative animate-fade-in">
            <button onclick="closeModal('registerModal')" class="absolute top-4 right-4 w-8 h-8 rounded-full bg-slate-100 text-slate-500 hover:bg-slate-200 flex items-center justify-center transition">
                <i class="fa-solid fa-xmark"></i>
            </button>

            <div class="flex items-center gap-3 mb-4">
                <div class="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold">
                    <i class="fa-solid fa-user-plus"></i>
                </div>
                <div>
                    <h3 class="text-lg font-bold text-slate-900">Repetitor bo'lish</h3>
                    <p class="text-xs text-slate-500">O'quvchilar oqimiga ega bo'ling</p>
                </div>
            </div>

            <form onsubmit="handleRegisterSubmit(event)" class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">To'liq ism-familiyangiz</label>
                    <input type="text" id="tutorRegisterName" required placeholder="Masalan: Akmal Ro'ziyev" class="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Telefon raqam</label>
                    <input type="tel" id="tutorRegisterPhone" required placeholder="+998 (90) 123-45-67" class="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-700 mb-1">Dars beradigan faningiz</label>
                    <input type="text" id="tutorRegisterSubject" required placeholder="Masalan: Matematika, Fizika" class="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
                </div>
                <button type="submit" class="w-full py-3 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-sm rounded-xl transition shadow-md shadow-emerald-500/20">
                    Ariza qoldirish
                </button>
            </form>
        </div>
    </div>

    <!-- MODAL 3: REVIEWS -->
    <div id="reviewModal" class="fixed inset-0 z-50 hidden bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
        <div class="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl relative animate-fade-in max-h-[90vh] overflow-y-auto">
            <button onclick="closeModal('reviewModal')" class="absolute top-4 right-4 w-8 h-8 rounded-full bg-slate-100 text-slate-500 hover:bg-slate-200 flex items-center justify-center transition">
                <i class="fa-solid fa-xmark"></i>
            </button>
            <h3 id="reviewTitle" class="text-lg font-bold text-slate-900 pr-8">Izohlar</h3>
            <p id="reviewSummary" class="text-sm text-slate-500 mb-4"></p>
            <div id="reviewList" class="space-y-3 mb-5"></div>
            <div id="reviewLocked" class="hidden p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800"></div>
            <form id="reviewForm" onsubmit="handleReviewSubmit(event)" class="hidden space-y-3 border-t border-slate-100 pt-4">
                <div class="text-xs font-bold text-slate-700">Bahoyingiz</div>
                <div class="flex gap-1">
                    <button type="button" id="star1" onclick="pickStars(1)">★</button>
                    <button type="button" id="star2" onclick="pickStars(2)">★</button>
                    <button type="button" id="star3" onclick="pickStars(3)">★</button>
                    <button type="button" id="star4" onclick="pickStars(4)">★</button>
                    <button type="button" id="star5" onclick="pickStars(5)">★</button>
                </div>
                <textarea id="reviewText" required rows="3" maxlength="300" placeholder="Dars qanday o'tdi? Qisqa izoh yozing" class="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-amber-400 outline-none resize-none"></textarea>
                <button type="submit" class="w-full py-3 bg-amber-500 hover:bg-amber-600 text-white font-bold text-sm rounded-xl transition">Bahoni yuborish</button>
            </form>
        </div>
    </div>

    <!-- TOAST NOTIFICATION -->
    <div id="toast" class="fixed bottom-5 right-5 z-50 hidden bg-slate-900 text-white px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3 animate-fade-in border border-slate-700">
        <i id="toastIcon" class="fa-solid fa-circle-check text-emerald-400"></i>
        <span id="toastMessage" class="text-xs font-medium">Amaliyot muvaffaqiyatli bajarildi!</span>
    </div>

    <!-- JAVASCRIPT LOGIC -->
    <script>
        // Ma'lumotlar serverdan (/api/tutors) yuklanadi
        let sampleTutors = [];

        let selectedTutor = null;
        const avatarColors = ['linear-gradient(135deg,#6366f1,#4338ca)','linear-gradient(135deg,#10b981,#047857)','linear-gradient(135deg,#f59e0b,#b45309)','linear-gradient(135deg,#ec4899,#be185d)','linear-gradient(135deg,#06b6d4,#0e7490)','linear-gradient(135deg,#8b5cf6,#6d28d9)'];

        // RENDER TUTORS
        function renderTutors(list) {
            const container = document.getElementById('tutorsContainer');
            const emptyState = document.getElementById('emptyState');
            const resultCount = document.getElementById('resultCount');

            container.innerHTML = '';
            resultCount.textContent = `Jami ${list.length} ta ta'lim beruvchi ko'rsatilmoqda`;

            if (list.length === 0) {
                emptyState.classList.remove('hidden');
                return;
            } else {
                emptyState.classList.add('hidden');
            }

            list.forEach((tutor, idx) => {
                const st = stats(tutor);
                const card = document.createElement('div');
                card.className = "bg-white rounded-2xl p-5 border border-slate-200 shadow-sm hover:shadow-xl transition duration-300 flex flex-col justify-between group";

                card.innerHTML = `
                    <div>
                        ${idx === 0 && list.length > 1 && ['default','rating'].includes(document.getElementById('sortSelect').value) ? '<div class="inline-block mb-3 text-[10px] font-extrabold px-2.5 py-1 rounded-full bg-amber-100 text-amber-800 border border-amber-200">🏆 Eng yuqori reyting</div>' : ''}
                        <div class="flex items-start gap-4 mb-4">
                            <div class="relative">
                                <div class="w-16 h-16 rounded-xl text-white flex items-center justify-center font-extrabold text-xl shadow-sm" style="background:${avatarColors[tutor.id % avatarColors.length]}">${tutor.name.split(' ').map(w=>w[0]).slice(0,2).join('')}</div>
                                <span class="absolute -bottom-1 -right-1 w-4 h-4 bg-emerald-500 border-2 border-white rounded-full" title="Aktiv"></span>
                            </div>
                            <div class="flex-grow">
                                <div class="flex items-center justify-between">
                                    <h3 class="font-bold text-slate-900 group-hover:text-brand-600 transition">${tutor.name}</h3>
                                    ${tutor.badge ? `<span class="text-[10px] font-extrabold px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">${tutor.badge}</span>` : ''}
                                </div>
                                <p class="text-xs font-semibold text-brand-600">${tutor.subject}</p>
                                <div class="flex items-center gap-1.5 text-xs text-slate-500 mt-1">
                                    <i class="fa-solid fa-star text-amber-400"></i>
                                    <span class="font-bold text-slate-800">${st.rating.toFixed(1)}</span>
                                    <span>(${st.reviews} izoh)</span>
                                </div>
                            </div>
                        </div>

                        <!-- Details -->
                        <div class="space-y-2 py-3 border-y border-slate-100 text-xs text-slate-600 mb-4">
                            <div class="flex items-center justify-between">
                                <span class="text-slate-400"><i class="fa-solid fa-location-dot w-4"></i> Hudud:</span>
                                <span class="font-semibold text-slate-700">${tutor.location}</span>
                            </div>
                            <div class="flex items-center justify-between">
                                <span class="text-slate-400"><i class="fa-solid fa-graduation-cap w-4"></i> Tajriba:</span>
                                <span class="font-semibold text-slate-700">${tutor.experience}</span>
                            </div>
                            <div class="flex items-center justify-between">
                                <span class="text-slate-400"><i class="fa-solid fa-laptop w-4"></i> Format:</span>
                                <span class="font-semibold uppercase text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-700">${tutor.format}</span>
                            </div>
                        </div>
                    </div>

                    <div class="flex gap-2 mb-3">
                        <button onclick="openReviews(${tutor.id})" class="flex-1 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-lg transition">Izohlar (${st.reviews})</button>
                        <button onclick="openReviews(${tutor.id}, true)" class="flex-1 py-2 bg-amber-50 hover:bg-amber-100 text-amber-700 border border-amber-200 text-xs font-bold rounded-lg transition">★ Baho berish</button>
                    </div>
                    <div class="flex items-center justify-between pt-2">
                        <div>
                            <span class="text-xs text-slate-400 block">1 ta dars narxi:</span>
                            <span class="text-base font-extrabold text-slate-900">${tutor.price.toLocaleString()} so'mdan</span>
                        </div>
                        <button onclick="openBookModal(${tutor.id})" class="px-4 py-2.5 bg-slate-900 hover:bg-brand-600 text-white text-xs font-bold rounded-xl transition shadow-sm">
                            Bog'lanish
                        </button>
                    </div>
                `;

                container.appendChild(card);
            });
        }

        // API VA REYTING
        let pickedStars = 0;
        let myTokens = {};
        try { myTokens = JSON.parse(localStorage.getItem('kurstop_tokens') || '{}'); } catch (err) {}
        function saveTokens() { try { localStorage.setItem('kurstop_tokens', JSON.stringify(myTokens)); } catch (err) {} }
        function esc(s) { return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

        async function api(path, body) {
            const opts = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {};
            const res = await fetch('/api' + path, opts);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || 'Xatolik yuz berdi');
            return data;
        }

        async function loadTutors() {
            try { sampleTutors = await api('/tutors'); }
            catch (err) { showToast("Serverga ulanib bo'lmadi"); }
            applyFilters();
        }

        function stats(t) { return { rating: t.rating, reviews: t.reviews }; }
        function ratingScore(t) { return (t.rating * t.reviews + 4.0 * 10) / (t.reviews + 10); }

        async function openReviews(id, rate) {
            selectedTutor = sampleTutors.find(t => t.id === id);
            pickStars(0);
            document.getElementById('reviewText').value = '';
            await renderReviews();
            document.getElementById('reviewModal').classList.remove('hidden');
            if (rate) setTimeout(() => document.getElementById('reviewModal').firstElementChild.scrollTo({ top: 9999, behavior: 'smooth' }), 80);
        }

        async function renderReviews() {
            const t = selectedTutor;
            let list = [];
            try { list = await api('/tutors/' + t.id + '/reviews'); } catch (err) {}
            document.getElementById('reviewTitle').textContent = t.name + ' haqida izohlar';
            document.getElementById('reviewSummary').textContent = '\u2605 ' + t.rating.toFixed(1) + ' \u00b7 ' + t.reviews + ' ta baho';
            document.getElementById('reviewList').innerHTML = list.length ? list.map(r => `<div class="p-3 rounded-xl bg-slate-50 border border-slate-100"><div class="flex items-center justify-between mb-1"><span class="text-xs font-bold text-slate-800">${esc(r.name)}</span><span class="text-amber-500 text-xs">${'\u2605'.repeat(r.stars)}<span class="text-slate-300">${'\u2605'.repeat(5 - r.stars)}</span></span></div><p class="text-xs text-slate-600">${esc(r.text)}</p></div>`).join('') : '<p class="text-xs text-slate-400">Hozircha izoh yo\'q. Birinchi bo\'lib baho bering!</p>';
            const locked = document.getElementById('reviewLocked');
            const form = document.getElementById('reviewForm');
            form.classList.add('hidden');
            locked.classList.add('hidden');
            if (myTokens[t.id]) {
                form.classList.remove('hidden');
            } else {
                locked.textContent = 'Baho berish uchun avval shu repetitorga ariza yuboring. Bu soxta izohlarning oldini oladi.';
                locked.classList.remove('hidden');
            }
        }

        function pickStars(n) {
            pickedStars = n;
            for (let i = 1; i <= 5; i++) {
                document.getElementById('star' + i).className = 'text-3xl transition ' + (i <= n ? 'text-amber-400' : 'text-slate-300');
            }
        }

        async function handleReviewSubmit(e) {
            e.preventDefault();
            if (!pickedStars) { showToast('Iltimos, yulduzcha tanlang'); return; }
            const id = selectedTutor.id;
            try {
                await api('/reviews', { tutor_id: id, token: myTokens[id], stars: pickedStars, text: document.getElementById('reviewText').value });
                delete myTokens[id];
                saveTokens();
                await loadTutors();
                selectedTutor = sampleTutors.find(t => t.id === id);
                await renderReviews();
                showToast('Bahoyingiz uchun rahmat!');
            } catch (err) {
                showToast(err.message);
            }
        }

        // FILTER & SORT
        function applyFilters() {
            const search = document.getElementById('searchInput').value.toLowerCase();
            const subject = document.getElementById('subjectFilter').value;
            const location = document.getElementById('locationFilter').value;
            const format = document.getElementById('formatFilter').value;
            const sort = document.getElementById('sortSelect').value;

            let filtered = sampleTutors.filter(tutor => {
                const matchesSearch = tutor.name.toLowerCase().includes(search) || tutor.subject.toLowerCase().includes(search);
                const matchesSubject = !subject || tutor.subject === subject;
                const matchesLocation = !location || tutor.location === location;
                const matchesFormat = !format || tutor.format === format;

                return matchesSearch && matchesSubject && matchesLocation && matchesFormat;
            });

            if (sort === 'default' || sort === 'rating') {
                filtered.sort((a, b) => ratingScore(b) - ratingScore(a));
            } else if (sort === 'price-low') {
                filtered.sort((a, b) => a.price - b.price);
            } else if (sort === 'price-high') {
                filtered.sort((a, b) => b.price - a.price);
            }

            renderTutors(filtered);
        }

        function resetFilters() {
            document.getElementById('searchInput').value = '';
            document.getElementById('subjectFilter').value = '';
            document.getElementById('locationFilter').value = '';
            document.getElementById('formatFilter').value = '';
            document.getElementById('sortSelect').value = 'default';
            applyFilters();
        }

        // MODAL HANDLERS
        function openBookModal(id) {
            selectedTutor = sampleTutors.find(t => t.id === id);
            document.getElementById('modalTutorName').textContent = selectedTutor.name + " bilan bog'lanish";
            document.getElementById('bookModal').classList.remove('hidden');
        }

        function openRegisterModal() {
            document.getElementById('registerModal').classList.remove('hidden');
        }

        function closeModal(id) {
            document.getElementById(id).classList.add('hidden');
        }

        // FORM SUBMISSIONS
        async function handleBookSubmit(e) {
            e.preventDefault();
            const form = e.target;
            try {
                const r = await api('/bookings', {
                    tutor_id: selectedTutor.id,
                    name: document.getElementById('studentName').value,
                    phone: document.getElementById('studentPhone').value,
                    note: document.getElementById('studentNote').value
                });
                myTokens[selectedTutor.id] = r.token;
                saveTokens();
                closeModal('bookModal');
                showToast("Arizangiz qabul qilindi! Tez orada repetitor siz bilan bog'lanadi. Endi uni baholashingiz mumkin.");
                form.reset();
            } catch (err) {
                showToast(err.message);
            }
        }

        async function handleRegisterSubmit(e) {
            e.preventDefault();
            const form = e.target;
            try {
                await api('/tutor-applications', {
                    name: document.getElementById('tutorRegisterName').value,
                    phone: document.getElementById('tutorRegisterPhone').value,
                    subject: document.getElementById('tutorRegisterSubject').value
                });
                closeModal('registerModal');
                showToast("Anketangiz qabul qilindi! Moderatorlarimiz siz bilan bog'lanishadi.");
                form.reset();
            } catch (err) {
                showToast(err.message);
            }
        }

        // TOAST NOTIFICATION
        function showToast(message) {
            const toast = document.getElementById('toast');
            document.getElementById('toastMessage').textContent = message;
            toast.classList.remove('hidden');
            setTimeout(() => {
                toast.classList.add('hidden');
            }, 4000);
        }

        // PHONE FORMAT +998 (XX) XXX-XX-XX
        function formatPhone(el) {
            let d = el.value.replace(/\D/g, '');
            if (d.startsWith('998')) d = d.slice(3);
            d = d.slice(0, 9);
            let out = '+998';
            if (d.length > 0) out += ' (' + d.slice(0, 2);
            if (d.length >= 2) out += ')';
            if (d.length > 2) out += ' ' + d.slice(2, 5);
            if (d.length > 5) out += '-' + d.slice(5, 7);
            if (d.length > 7) out += '-' + d.slice(7, 9);
            el.value = d.length ? out : '';
        }
        ['studentPhone', 'tutorRegisterPhone'].forEach(id => {
            document.getElementById(id).addEventListener('input', e => formatPhone(e.target));
        });

        // CLOSE MODALS: Escape key or click outside
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') { closeModal('bookModal'); closeModal('registerModal'); closeModal('reviewModal'); }
        });
        ['bookModal', 'registerModal', 'reviewModal'].forEach(id => {
            document.getElementById(id).addEventListener('click', e => { if (e.target.id === id) closeModal(id); });
        });

        // INITIAL LOAD
        loadTutors();
    </script>
</body>
</html>'''


# ---------- Ma'lumotlar bazasi (PostgreSQL yoki SQLite) ----------
class DB:
    def __init__(self):
        if USE_PG:
            self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            self.conn = sqlite3.connect(DB_PATH)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql, params=()):
        if USE_PG:
            sql = sql.replace("?", "%s")
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def insert(self, sql, params=()):
        """INSERT qiladi va yangi qator id sini qaytaradi."""
        if USE_PG:
            return self.execute(sql + " RETURNING id", params).fetchone()["id"]
        return self.execute(sql, params).lastrowid

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db():
    if "db" not in g:
        g.db = DB()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = DB()
    try:
        if USE_PG:  # bir nechta jarayon bir vaqtda ishga tushsa, to'qnashmasligi uchun
            db.execute("SELECT pg_advisory_lock(7349)")
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                db.execute(stmt)
        count = db.execute("SELECT COUNT(*) AS c FROM tutors").fetchone()["c"]
        if SEED_DEMO and count == 0:
            for row in SEED:
                db.execute(
                    "INSERT INTO tutors (name, subject, location, format, price, experience, badge,"
                    " base_rating, base_reviews) VALUES (?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT DO NOTHING",
                    row,
                )
        db.commit()
    finally:
        db.close()


# ---------- yordamchi funksiyalar ----------
def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def err(message, code=400):
    return jsonify(error=message), code


def clean_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("998"):
        digits = digits[3:]
    return digits if len(digits) == 9 else None


def clean_text(value, limit):
    return str(value or "").strip()[:limit]


def notify(text):
    """Telegram'ga xabar yuboradi (agar sozlangan bo'lsa)."""
    if not (TG_TOKEN and TG_CHAT):
        return

    def run():
        try:
            data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode()
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data, timeout=10
            )
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


_hits = {}


@app.before_request
def rate_limit():
    """Spamdan himoya: bitta IP soatiga 30 ta POST."""
    if request.method != "POST" or request.path.startswith("/api/admin"):
        return None
    ip = request.remote_addr or "?"
    t = time.time()
    hits = [x for x in _hits.get(ip, []) if t - x < 3600]
    if len(hits) >= 30:
        _hits[ip] = hits
        return err("Juda ko'p so'rov. Birozdan keyin urinib ko'ring.", 429)
    hits.append(t)
    _hits[ip] = hits
    return None


def require_admin():
    key = request.headers.get("X-Admin-Key") or request.args.get("key", "")
    if not ADMIN_KEY or not hmac.compare_digest(key.encode(), ADMIN_KEY.encode()):
        return err("Ruxsat yo'q", 403)
    return None


# ---------- sahifalar ----------
@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.get("/healthz")
def healthz():
    return "ok"


ADMIN_HTML = r"""<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Kurstop admin</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:0 auto;padding:16px;color:#0f172a}
input,button,select{font:inherit;padding:8px;margin:4px 0}input,select{width:100%;box-sizing:border-box}
button{background:#4f46e5;color:#fff;border:0;border-radius:8px;padding:9px 14px}
.card{border:1px solid #e2e8f0;border-radius:10px;padding:10px;margin:8px 0;font-size:14px}h2{margin-top:24px}</style></head><body>
<h1>Kurstop admin</h1>
<input id="key" type="password" placeholder="ADMIN_KEY"><button onclick="loadAll()">Kirish</button>
<p id="msg"></p>
<h2>Arizalar</h2><div id="bookings"></div>
<h2>Repetitor anketalari</h2><div id="apps"></div>
<h2>Repetitor qo'shish</h2>
<input id="n" placeholder="Ism familiya"><input id="s" placeholder="Fan"><input id="l" placeholder="Shahar">
<select id="f"><option>onlayn</option><option>oflayn</option><option>gibrid</option></select>
<input id="p" type="number" placeholder="1 ta dars narxi (so'm)"><input id="e" placeholder="Tajriba (masalan: 5 yil tajriba)">
<button onclick="addTutor()">Qo'shish</button>
<script>
const $=id=>document.getElementById(id);
async function call(path,opt){const r=await fetch('/api/admin'+path,{...opt,headers:{'X-Admin-Key':$('key').value,'Content-Type':'application/json'}});const d=await r.json();if(!r.ok)throw new Error(d.error||'Xatolik');return d}
function show(id,list,fmt){const box=$(id);box.textContent='';list.forEach(x=>{const d=document.createElement('div');d.className='card';d.textContent=fmt(x);box.appendChild(d)});if(!list.length)box.textContent="Hozircha yo'q"}
async function loadAll(){try{show('bookings',await call('/bookings'),b=>b.created_at.slice(0,16)+' | '+b.tutor+' | '+b.name+' | +998'+b.phone+(b.note?' | '+b.note:''));show('apps',await call('/applications'),a=>a.created_at.slice(0,16)+' | '+a.name+' | '+a.subject+' | +998'+a.phone);$('msg').textContent=''}catch(e){$('msg').textContent=e.message}}
async function addTutor(){try{await call('/tutors',{method:'POST',body:JSON.stringify({name:$('n').value,subject:$('s').value,location:$('l').value,format:$('f').value,price:$('p').value,experience:$('e').value})});$('msg').textContent="Qo'shildi!"}catch(e){$('msg').textContent=e.message}}
</script></body></html>"""


@app.get("/admin")
def admin_page():
    return ADMIN_HTML


# ---------- ochiq API ----------
@app.get("/api/tutors")
def list_tutors():
    rows = get_db().execute(
        """SELECT t.*, COALESCE(r.cnt, 0) AS cnt, COALESCE(r.total, 0) AS total
           FROM tutors t
           LEFT JOIN (SELECT tutor_id, COUNT(*) AS cnt, SUM(stars) AS total
                      FROM reviews GROUP BY tutor_id) r ON r.tutor_id = t.id
           WHERE t.active = 1"""
    ).fetchall()
    out = []
    for r in rows:
        n = r["base_reviews"] + r["cnt"]
        rating = (r["base_rating"] * r["base_reviews"] + r["total"]) / n if n else 0
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "subject": r["subject"],
                "location": r["location"],
                "format": r["format"],
                "price": r["price"],
                "experience": r["experience"],
                "badge": r["badge"],
                "rating": round(float(rating), 2),
                "reviews": int(n),
            }
        )
    # eng yuqori reyting tepada (baho + izohlar soni hisobga olinadi)
    out.sort(key=lambda t: (t["rating"] * t["reviews"] + 40) / (t["reviews"] + 10), reverse=True)
    return jsonify(out)


@app.get("/api/tutors/<int:tutor_id>/reviews")
def tutor_reviews(tutor_id):
    rows = get_db().execute(
        "SELECT name, stars, text, created_at FROM reviews WHERE tutor_id = ? ORDER BY id DESC LIMIT 50",
        (tutor_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/bookings")
def create_booking():
    data = request.get_json(silent=True) or {}
    db = get_db()
    try:
        tutor_id = int(data.get("tutor_id"))
    except (TypeError, ValueError):
        return err("Repetitor topilmadi", 404)
    tutor = db.execute("SELECT * FROM tutors WHERE id = ? AND active = 1", (tutor_id,)).fetchone()
    name = clean_text(data.get("name"), 80)
    phone = clean_phone(data.get("phone"))
    if not tutor:
        return err("Repetitor topilmadi", 404)
    if len(name) < 2:
        return err("Ismingizni kiriting")
    if not phone:
        return err("Telefon raqami noto'g'ri")
    token = secrets.token_urlsafe(16)
    note = clean_text(data.get("note"), 300)
    db.insert(
        "INSERT INTO bookings (tutor_id, name, phone, note, token, created_at) VALUES (?,?,?,?,?,?)",
        (tutor["id"], name, phone, note, token, now()),
    )
    db.commit()
    notify(f"Yangi ariza\nRepetitor: {tutor['name']}\nIsm: {name}\nTel: +998{phone}\nIzoh: {note}")
    return jsonify(token=token), 201


@app.post("/api/reviews")
def create_review():
    data = request.get_json(silent=True) or {}
    db = get_db()
    try:
        tutor_id = int(data.get("tutor_id"))
        stars = int(data.get("stars"))
    except (TypeError, ValueError):
        return err("Yulduzcha tanlang")
    booking = db.execute(
        "SELECT * FROM bookings WHERE token = ? AND tutor_id = ?",
        (str(data.get("token") or ""), tutor_id),
    ).fetchone()
    if not booking:
        return err("Baho berish uchun avval repetitorga ariza yuboring", 403)
    if not 1 <= stars <= 5:
        return err("Baho 1 dan 5 gacha bo'lishi kerak")
    text = clean_text(data.get("text"), 300)
    first_name = booking["name"].split()[0]
    try:
        db.insert(
            "INSERT INTO reviews (tutor_id, booking_id, name, phone, stars, text, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (booking["tutor_id"], booking["id"], first_name, booking["phone"], stars, text, now()),
        )
        db.commit()
    except IntegrityErrors:
        db.rollback()
        return err("Siz bu repetitorni allaqachon baholagansiz", 409)
    return jsonify(ok=True), 201


@app.post("/api/tutor-applications")
def tutor_application():
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get("name"), 80)
    subject = clean_text(data.get("subject"), 80)
    phone = clean_phone(data.get("phone"))
    if len(name) < 2 or len(subject) < 2:
        return err("Ism va fanni kiriting")
    if not phone:
        return err("Telefon raqami noto'g'ri")
    db = get_db()
    db.insert(
        "INSERT INTO tutor_applications (name, phone, subject, created_at) VALUES (?,?,?,?)",
        (name, phone, subject, now()),
    )
    db.commit()
    notify(f"Yangi repetitor anketasi\nIsm: {name}\nFan: {subject}\nTel: +998{phone}")
    return jsonify(ok=True), 201


# ---------- admin API (ADMIN_KEY kerak) ----------
@app.get("/api/admin/bookings")
def admin_bookings():
    denied = require_admin()
    if denied:
        return denied
    rows = get_db().execute(
        """SELECT b.id, t.name AS tutor, b.name, b.phone, b.note, b.created_at
           FROM bookings b JOIN tutors t ON t.id = b.tutor_id ORDER BY b.id DESC LIMIT 500"""
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/admin/applications")
def admin_applications():
    denied = require_admin()
    if denied:
        return denied
    rows = get_db().execute("SELECT * FROM tutor_applications ORDER BY id DESC LIMIT 500").fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/admin/tutors")
def admin_add_tutor():
    """Yangi repetitor qo'shish. JSON: name, subject, location, format, price, experience, badge"""
    denied = require_admin()
    if denied:
        return denied
    d = request.get_json(silent=True) or {}
    try:
        values = (
            clean_text(d["name"], 80),
            clean_text(d["subject"], 60),
            clean_text(d["location"], 60),
            clean_text(d["format"], 20),
            int(d["price"]),
            clean_text(d.get("experience"), 60),
            clean_text(d.get("badge"), 40) or None,
        )
    except (KeyError, ValueError, TypeError):
        return err("name, subject, location, format, price majburiy")
    if not all(values[:4]):
        return err("name, subject, location, format majburiy")
    db = get_db()
    try:
        new_id = db.insert(
            "INSERT INTO tutors (name, subject, location, format, price, experience, badge)"
            " VALUES (?,?,?,?,?,?,?)",
            values,
        )
        db.commit()
    except IntegrityErrors:
        db.rollback()
        return err("Bunday repetitor (ism va fan) allaqachon bor", 409)
    return jsonify(id=new_id), 201


@app.post("/api/admin/tutors/<int:tutor_id>/hide")
def admin_hide_tutor(tutor_id):
    denied = require_admin()
    if denied:
        return denied
    db = get_db()
    db.execute("UPDATE tutors SET active = 0 WHERE id = ?", (tutor_id,))
    db.commit()
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG") == "1")
