import os
import json
import subprocess
import pandas as pd
from datetime import datetime
import asyncio
from db import SessionLocal
from sqlalchemy import select
from models import User
import re
from crud import insert_or_update_user
import html
from pydub import AudioSegment
import imageio_ffmpeg

# --- Telegram ---
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes,
    CommandHandler, ConversationHandler, ApplicationBuilder, CallbackQueryHandler
)

# --- OpenAI ---
from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY
from openai import OpenAI

# --- FastAPI & Uvicorn ---
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Response, status
from contextlib import asynccontextmanager

# === Клієнти та Налаштування ===
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Не встановлено змінну TELEGRAM_BOT_TOKEN!")
if not OPENAI_API_KEY:
    raise ValueError("Не встановлено змінну OPENAI_API_KEY!")

WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL_BASE")
if not WEBHOOK_URL_BASE:
    raise ValueError("Не встановлено змінну середовища WEBHOOK_URL_BASE!")

WEBHOOK_PATH = f"/telegram/{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_URL_BASE}{WEBHOOK_PATH}"

client = OpenAI(api_key=OPENAI_API_KEY)
LOG_FILE = "chat_history.csv"

NAME, SURNAME, PHONE, SPECIALTY, EXPERIENCE = range(5)

menu_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💪 Навчальний курс", web_app=WebAppInfo(url="https://igordatsenko123.github.io/TG_WEB_APP_AISAFETYCOACH/?v=8"))]
    ],
    resize_keyboard=True
)

print("DEBUG: Імпорти завершені")
print(f"DEBUG: Webhook URL буде встановлено на: {WEBHOOK_URL}")

# === Логування ===
def log_message(user_id, username, msg_id, msg_type, role, content):
    print(f"DEBUG: Логуємо повідомлення від {username} ({user_id}) - {role}: {content}")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_entry = {
        "user_id": user_id,
        "username": username,
        "datetime": timestamp,
        "message_id": msg_id,
        "message_type": msg_type,
        "role": role,
        "content": content
    }
    try:
        if os.path.exists(LOG_FILE):
            df = pd.read_csv(LOG_FILE)
            df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
        else:
            df = pd.DataFrame([new_entry])
        df.to_csv(LOG_FILE, index=False)
    except Exception as e:
        print(f"ERROR: Помилка при логуванні: {e}")

# === Перевірка реєстрації ===
async def is_registered(user_id: int) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == user_id))
        user = result.scalar_one_or_none()
        return user is not None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Команда /start от user_id={user_id}")

    # 🛑 Запобігаємо повторному запуску анкети
    if context.user_data.get("profile_started"):
        print("DEBUG: Анкета вже почата — пропускаємо повторний запуск.")
        return

    if await is_registered(user_id):
        try:
            async with SessionLocal() as session:
                result = await session.execute(select(User).where(User.tg_id == user_id))
                user = result.scalar_one_or_none()

                if user and user.first_name:
                    await update.message.reply_text(
                        f"З поверненням, <b>{html.escape(user.first_name)}</b>!\nГотовий відповідати на твої запитання:",
                        reply_markup=menu_keyboard,
                        parse_mode=ParseMode.HTML
                    )
                    return ConversationHandler.END
                else:
                    raise ValueError("Дані користувача не знайдено")
        except Exception as e:
            print(f"ERROR: Не вдалося завантажити профіль для {user_id}: {e}")
            await update.message.reply_text(
                "Вибачте, виникла помилка з вашим профілем. Давайте заповнимо анкету знову. Як тебе звати?"
            )
            context.user_data["profile_started"] = True
            return NAME
    else:
        await update.message.reply_text(
            "Привіт! Я твій помічник з безпеки праці ⛑️ Я допоможу тобі із будь-яким питанням! Давай знайомитись 😊",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(1)
        await update.message.reply_text("Напиши своє імʼя", parse_mode=ParseMode.HTML)
        context.user_data["profile_started"] = True
        return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()

    if name in ["📋 Профіль", "✏️ Оновити анкету"] or len(name) < 2:
        await update.message.reply_text("⚠️ Введіть справжнє імʼя.")
        return NAME

    context.user_data["name"] = name
    await update.message.reply_text("Окей! А тепер прізвище", reply_markup=ReplyKeyboardRemove())
    return SURNAME

async def get_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    surname = update.message.text.strip()

    if surname in ["📋 Профіль", "✏️ Оновити анкету"] or len(surname) < 2:
        await update.message.reply_text("⚠️ Введіть справжнє прізвище.")
        return SURNAME

    context.user_data["surname"] = surname

    contact_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Поділитися номером телефону", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    user_name = context.user_data.get("name", "друже")
    await update.message.reply_text(
        f"Радий знайомству, <b>{html.escape(user_name)}</b>! Давай далі 💪",
        parse_mode=ParseMode.HTML
    )

    await update.message.reply_text(
        "Поділись своїм номером телефону, натиснувши кнопку нижче або просто напиши його.\n\n"
        "<i>Твої дані потрібні для створення твого унікального профілю, щоб надати тобі саме те, що тобі потрібно</i>",
        reply_markup=contact_keyboard,
        parse_mode=ParseMode.HTML
    )
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_phone = update.message.text.strip()
    print(f"DEBUG: Отримано телефон (текстом): {raw_phone}")

    digits_only = re.sub(r"\D", "", raw_phone)

    if digits_only.startswith("0") and len(digits_only) == 10:
        normalized = "+380" + digits_only[1:]
    elif digits_only.startswith("380") and len(digits_only) == 12:
        normalized = "+" + digits_only
    elif digits_only.startswith(("67", "68", "50", "63")):
        normalized = "+380" + digits_only
    else:
        await update.message.reply_text(
            "⚠️ <b>Невірний формат номеру.</b>\n"
            "Приклад коректного номеру: <code>+380671234567</code>, <code>0671234567</code>, або <code>67 123 45 67</code>",
            parse_mode=ParseMode.HTML
        )
        return PHONE

    context.user_data["phone"] = normalized
    print(f"DEBUG: Нормалізований номер: {normalized}")
    await update.message.reply_text("Окей, рухаємося далі ✅", reply_markup=ReplyKeyboardRemove())
    return await ask_specialty(update, context)

async def process_contact_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.effective_user.id

    if contact.user_id != user_id:
        await update.message.reply_text("Будь ласка, поділись своїм власним контактом.")
        return PHONE

    phone_number = contact.phone_number
    print(f"DEBUG: Отримано контакт (через кнопку): {phone_number} від user_id={user_id}")

    digits_only = re.sub(r"\D", "", phone_number)
    if digits_only.startswith("380") and len(digits_only) == 12:
        normalized = "+" + digits_only
    elif len(digits_only) == 10 and digits_only.startswith("0"):
        normalized = "+380" + digits_only[1:]
    elif len(digits_only) == 9:
        normalized = "+380" + digits_only
    else:
        print("⚠️ Невірний номер після обробки:", digits_only)
        await update.message.reply_text(
            "⚠️ Виникла проблема з номером телефону. Введи його вручну у форматі: <code>+380XXXXXXXXX</code>",
            parse_mode=ParseMode.HTML
        )
        return PHONE

    context.user_data["phone"] = normalized
    await update.message.reply_text("Окей, рухаємося далі ✅", reply_markup=ReplyKeyboardRemove())
    return await ask_specialty(update, context)

async def ask_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Зварювальник", callback_data="spec:Зварювальник")],
        [InlineKeyboardButton("Муляр", callback_data="spec:Муляр")],
        [InlineKeyboardButton("Монолітник", callback_data="spec:Монолітник")],
        [InlineKeyboardButton("Арматурник", callback_data="spec:Арматурник")]
    ])

    await update.message.reply_text(
        "Тепер обери свою спеціальність",
        reply_markup=keyboard
    )
    return SPECIALTY

async def handle_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    specialty = query.data.split("spec:")[1]
    context.user_data["speciality"] = specialty

    await query.edit_message_text(
        f"Обрано спеціальність: <b>{html.escape(specialty)}</b>\n\nСкільки років досвіду маєш у цій сфері?",
        parse_mode=ParseMode.HTML
    )
    return EXPERIENCE


async def handle_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    experience = update.message.text.strip()

    if len(experience) < 1 or not re.match(r"^[\w\s.,-]{1,50}$", experience):
        await update.message.reply_text("⚠️ Введи, будь ласка, скільки років досвіду маєш (наприклад: 2 роки або понад 10).")
        return EXPERIENCE

    context.user_data["experience"] = experience
    await update.message.reply_text("Добре. А тепер напиши назву компанії, де ти працюєш або останнє місце роботи:")
    return COMPANY


async def handle_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    company = update.message.text.strip()

    if len(company) < 2:
        await update.message.reply_text("⚠️ Введи, будь ласка, справжню назву компанії.")
        return COMPANY

    context.user_data["company"] = company

    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    now = datetime.utcnow()

    try:
        async with SessionLocal() as session:
            new_user = User(
                tg_id=user_id,
                first_name=context.user_data.get("name"),
                last_name=context.user_data.get("surname"),
                phone=context.user_data.get("phone"),
                speciality=context.user_data.get("speciality"),
                experience=context.user_data.get("experience"),
                company=context.user_data.get("company"),
                username=username,
                updated_at=now
            )
            session.add(new_user)
            await session.commit()

            await update.message.reply_text(
                "✅ <b>Анкету заповнено!</b>\nМожеш ставити будь-які питання щодо техніки безпеки, СІЗ або норм праці 🦺",
                reply_markup=menu_keyboard,
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        print(f"ERROR: Не вдалося зберегти користувача {user_id}: {e}")
        await update.message.reply_text(
            "⚠️ Вибач, сталася помилка при збереженні анкети. Спробуй ще раз пізніше."
        )

    return ConversationHandler.END
