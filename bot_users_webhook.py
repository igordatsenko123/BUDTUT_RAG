import os
import json
import subprocess
# import pandas as pd # Закоментовано, якщо не використовується безпосередньо в цьому файлі
from datetime import datetime, timezone  # Додано timezone
import asyncio
from db import SessionLocal  # Припускаємо, що db.py та SessionLocal налаштовані
from sqlalchemy import select
from models import User  # Припускаємо, що models.py та User налаштовані
import re
from crud import insert_or_update_user  # Припускаємо, що crud.py та функція існують
import html
# Порядок імпортів для pydub та imageio_ffmpeg може бути важливим
import imageio_ffmpeg
from pydub import AudioSegment

# --- Telegram ---
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BotCommand
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes,
    CommandHandler, ConversationHandler, ApplicationBuilder, ExtBot,
    CallbackQueryHandler
)
from telegram.constants import ParseMode

# --- OpenAI ---
# Переконайтесь, що config.py існує та містить ці змінні
try:
    from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY
except ImportError:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN та OPENAI_API_KEY мають бути встановлені або в config.py, або як змінні середовища.")

from openai import OpenAI

# --- FastAPI & Uvicorn ---
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Response, status
from contextlib import asynccontextmanager

# === Клієнти та Налаштування ===
# Перевірка токенів на початку
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Не встановлено змінну TELEGRAM_BOT_TOKEN!")
if not OPENAI_API_KEY:
    raise ValueError("Не встановлено змінну OPENAI_API_KEY!")

WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL_BASE")
if not WEBHOOK_URL_BASE:
    # Для локального тестування можна встановити ngrok URL тут, але для продакшену це має бути змінна середовища
    # WEBHOOK_URL_BASE = "https://your-ngrok-or-railway-url.io" # Приклад
    raise ValueError("Не встановлено змінну середовища WEBHOOK_URL_BASE!")

WEBHOOK_PATH = f"/telegram/{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_URL_BASE.rstrip('/')}{WEBHOOK_PATH}"

client = OpenAI(api_key=OPENAI_API_KEY)

LOG_FILE = "chat_history.csv"

# Стани для ConversationHandler
NAME, SURNAME, PHONE, SPECIALTY, EXPERIENCE = range(5)

# Головне меню
menu_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💪 Навчальний курс",
                        web_app=WebAppInfo(url="https://igordatsenko123.github.io/TG_WEB_APP_AISAFETYCOACH/?v=8"))]
    ],
    resize_keyboard=True
)

print("DEBUG: Імпорти завершені")
print(f"DEBUG: Webhook URL буде встановлено на: {WEBHOOK_URL}")


# === Логування повідомлень ===
def log_message(user_id, username, msg_id, msg_type, role, content):
    print(f"DEBUG: Логуємо повідомлення від {username} ({user_id}) - {role}: {content}")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_entry = {
        "user_id": user_id, "username": username, "datetime": timestamp,
        "message_id": msg_id, "message_type": msg_type, "role": role, "content": content
    }
    try:
        # Для простоти і швидкості, можна писати напряму в CSV без pandas для кожного повідомлення
        file_exists = os.path.exists(LOG_FILE)
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            csv_writer = csv.DictWriter(f, fieldnames=new_entry.keys())
            if not file_exists:
                csv_writer.writeheader()
            csv_writer.writerow(new_entry)
    except Exception as e:
        print(f"ERROR: Помилка при логуванні в CSV: {e}")


# === Перевірка реєстрації ===
async def is_registered(user_id: int) -> bool:
    async with SessionLocal() as session:
        # SQLAlchemy 2.0+ рекомендує використовувати session.execute(select(...))
        # і потім .scalar_one_or_none() або аналогічні методи.
        # Переконайтесь, що ваш SessionLocal та User модель налаштовані для асинхронної роботи.
        # Для асинхронних операцій з БД часто потрібна транзакція:
        async with session.begin():  # Починаємо транзакцію (якщо потрібно)
            result = await session.execute(select(User).where(User.tg_id == user_id))
            user = result.scalar_one_or_none()
    return user is not None


# === Обробники Команд та Станів Анкети ===

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пиши нам тут:\nhttps://t.me/ai_safety_coach_support"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Функція start викликана для user_id={user_id}")

    # Перевіряємо, чи користувач вже в процесі заповнення анкети (за станом ConversationHandler)
    # Це більш надійний спосіб, ніж context.user_data.get("profile_started") для цієї логіки
    # Однак, ConversationHandler сам керує входом, тому ця перевірка тут може бути зайвою,
    # якщо /start єдиний спосіб почати цю конкретну розмову.

    if await is_registered(user_id):
        try:
            user_db_name = None
            async with SessionLocal() as session:
                async with session.begin():
                    result = await session.execute(select(User.first_name).where(User.tg_id == user_id))
                    user_db_name = result.scalar_one_or_none()

            if user_db_name:
                await update.message.reply_text(
                    f"З поверненням, <b>{html.escape(user_db_name)}</b>!\nГотовий відповідати на твої запитання:",
                    reply_markup=menu_keyboard,
                    parse_mode=ParseMode.HTML
                )
                return ConversationHandler.END  # Завершуємо розмову, якщо вона була активна
            else:
                # Користувач зареєстрований, але ім'я не знайдено - це дивно, починаємо анкету
                print(f"WARN: Користувач {user_id} зареєстрований, але ім'я не знайдено в БД. Починаємо анкету.")
                await update.message.reply_text(
                    "Привіт! Здається, нам потрібно оновити твої дані. Давай познайомимось 😊",
                    reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML
                )
        except Exception as e:
            print(f"ERROR: Помилка при перевірці зареєстрованого користувача {user_id}: {e}")
            await update.message.reply_text(
                "Вибачте, виникла помилка. Давайте спробуємо заповнити анкету. Як тебе звати?"
            )
        # У будь-якому випадку, якщо є проблема з зареєстрованим користувачем, або він не зареєстрований
        # і ми дійшли сюди, починаємо з запиту імені.
        context.user_data["profile_started"] = True  # Встановлюємо прапорець ТУТ
        print(f"DEBUG: Користувач {user_id} починає анкету. Стан NAME. profile_started=True")
        await update.message.reply_text("Напиши своє імʼя", parse_mode=ParseMode.HTML)
        return NAME
    else:
        # Користувач не зареєстрований
        print(f"DEBUG: Користувач {user_id} не зареєстрований. Починаємо анкету.")
        await update.message.reply_text(
            "Привіт! Я твій помічник з безпеки праці ⛑️ Я допоможу тобі із будь-яким питанням! Давай знайомитись 😊",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(0.5)
        context.user_data["profile_started"] = True  # Встановлюємо прапорець ТУТ
        print(f"DEBUG: Користувач {user_id} починає анкету. Стан NAME. profile_started=True")
        await update.message.reply_text("Напиши своє імʼя", parse_mode=ParseMode.HTML)
        return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    user_id = update.effective_user.id
    print(f"DEBUG: Функція get_name викликана для user_id={user_id}. Отримано ім'я: '{name}'")

    if name in ["📋 Профіль", "✏️ Оновити анкету"] or len(name) < 2:
        await update.message.reply_text("⚠️ Введіть справжнє імʼя.")
        return NAME

    context.user_data["name"] = name
    # context.user_data["profile_started"] = True # Цей прапорець вже має бути встановлений у start()
    print(f"DEBUG: Ім'я '{name}' збережено для user_id={user_id}. Перехід до стану SURNAME.")
    await update.message.reply_text("Окей! А тепер прізвище", reply_markup=ReplyKeyboardRemove())
    return SURNAME


# ... (решта ваших функцій-обробників: get_surname, get_phone, process_contact_info, etc.) ...
# Переконайтесь, що вони коректно повертають наступні стани або ConversationHandler.END
# І що вони встановлюють/очищують context.user_data["profile_started"] у відповідних місцях (в кінці анкети)

async def get_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    surname = update.message.text.strip()
    user_id = update.effective_user.id
    print(f"DEBUG: Функція get_surname викликана для user_id={user_id}. Отримано прізвище: '{surname}'")

    if surname in ["📋 Профіль", "✏️ Оновити анкету"] or len(surname) < 2:
        await update.message.reply_text("⚠️ Введіть справжнє прізвище.")
        return SURNAME

    context.user_data["surname"] = surname
    contact_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Поділитися номером телефону", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    user_name = context.user_data.get("name", "друже")
    await update.message.reply_text(
        f"Радий знайомству, <b>{html.escape(user_name)}</b>! Давай далі 💪",
        parse_mode=ParseMode.HTML
    )
    await update.message.reply_text(
        "Поділись своїм номером телефону, натиснувши кнопку нижче або просто напиши його.\n\n"
        "<i>Твої дані потрібні для створення твого унікального профілю, щоб надати тобі саме те, що тобі потрібно</i>",
        reply_markup=contact_keyboard, parse_mode=ParseMode.HTML
    )
    print(f"DEBUG: Прізвище '{surname}' збережено для user_id={user_id}. Перехід до стану PHONE.")
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_phone = update.message.text.strip()
    user_id = update.effective_user.id
    print(f"DEBUG: Функція get_phone (текст) викликана для user_id={user_id}. Отримано: {raw_phone}")
    digits_only = re.sub(r"\D", "", raw_phone)
    normalized = ""
    if digits_only.startswith("0") and len(digits_only) == 10:
        normalized = "+380" + digits_only[1:]
    elif digits_only.startswith("380") and len(digits_only) == 12:
        normalized = "+" + digits_only
    elif len(digits_only) == 9 and digits_only.startswith(
            ("39", "50", "63", "66", "67", "68", "73", "91", "92", "93", "94", "95", "96", "97", "98", "99")):
        normalized = "+380" + digits_only
    else:
        await update.message.reply_text(
            "⚠️ <b>Невірний формат номеру.</b>\n"
            "Будь ласка, введіть номер у форматі <code>+380XXXXXXXXX</code>, <code>0XXXXXXXXX</code>, або <code>XXXXXXXXX</code> (9 цифр, якщо це український номер).",
            parse_mode=ParseMode.HTML
        )
        return PHONE
    context.user_data["phone"] = normalized
    print(f"DEBUG: Телефон '{normalized}' збережено для user_id={user_id}. Виклик ask_specialty.")
    await update.message.reply_text("Окей, рухаємося далі ✅", reply_markup=ReplyKeyboardRemove())
    return await ask_specialty(update, context)


async def process_contact_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.effective_user.id
    print(f"DEBUG: Функція process_contact_info викликана для user_id={user_id}.")
    if contact.user_id != user_id:
        await update.message.reply_text("Будь ласка, поділись своїм власним контактом.")
        return PHONE
    phone_number = contact.phone_number
    normalized_phone = phone_number if phone_number.startswith('+') else '+' + phone_number
    context.user_data["phone"] = normalized_phone
    print(f"DEBUG: Контакт '{normalized_phone}' збережено для user_id={user_id}. Виклик ask_specialty.")
    await update.message.reply_text("Окей, рухаємося далі ✅", reply_markup=ReplyKeyboardRemove())
    return await ask_specialty(update, context)


async def ask_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Функція ask_specialty викликана для user_id={user_id}.")
    message_to_reply = update.callback_query.message if update.callback_query else update.message
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Зварювальник", callback_data="spec:Зварювальник")],
        [InlineKeyboardButton("Муляр", callback_data="spec:Муляр")],
        [InlineKeyboardButton("Монолітник", callback_data="spec:Монолітник")],
        [InlineKeyboardButton("Арматурник", callback_data="spec:Арматурник")],
        [InlineKeyboardButton("Інша спеціальність", callback_data="spec:other_spec")]
    ])
    await message_to_reply.reply_text("Тепер обери свою спеціальність:", reply_markup=keyboard)
    print(f"DEBUG: Запит спеціальності для user_id={user_id}. Перехід до стану SPECIALTY.")
    return SPECIALTY


async def handle_specialty_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    print(f"DEBUG: Функція handle_specialty_selection викликана для user_id={user_id}. Data: {data}")

    if data.startswith("spec:"):
        specialty_choice = data.split(":", 1)[1]
        if specialty_choice == "other_spec":
            await query.edit_message_text("✏️ Добре, напиши свою спеціальність вручну:")
            print(
                f"DEBUG: Користувач {user_id} обрав 'Інша спеціальність'. Залишаємося в стані SPECIALTY для текстового вводу.")
            return SPECIALTY  # Очікуємо текстовий ввід у цьому ж стані
        else:
            context.user_data["specialty"] = specialty_choice
            await query.edit_message_text(f"✅ Спеціальність: <b>{html.escape(specialty_choice)}</b>",
                                          parse_mode=ParseMode.HTML)
            print(f"DEBUG: Спеціальність '{specialty_choice}' збережено для user_id={user_id}. Виклик ask_experience.")
            return await ask_experience(update, context)
    return SPECIALTY


async def handle_manual_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    specialty = update.message.text.strip()
    user_id = update.effective_user.id
    print(f"DEBUG: Функція handle_manual_specialty викликана для user_id={user_id}. Отримано: '{specialty}'")

    if not specialty or len(specialty) < 2 or any(c in specialty for c in "!@#$%^&*(){}[]<>"):
        await update.message.reply_text("⚠️ Введіть коректну спеціальність (не менше 2 літер, без спецсимволів).")
        return SPECIALTY
    if specialty in ["📋 Профіль", "✏️ Оновити анкету"]:
        await update.message.reply_text("⚠️ Це виглядає як кнопка. Введіть свою спеціальність вручну.")
        return SPECIALTY

    context.user_data["specialty"] = specialty
    await update.message.reply_text(f"✅ Спеціальність збережено: <b>{html.escape(specialty)}</b>",
                                    parse_mode=ParseMode.HTML)
    print(
        f"DEBUG: Ручна спеціальність '{specialty}' збережено для user_id={user_id}. Виклик ask_experience_from_message.")
    return await ask_experience_from_message(update, context)


async def ask_experience_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Функція ask_experience_from_message викликана для user_id={user_id}.")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("<1 року", callback_data="exp:<1"),
         InlineKeyboardButton("1–2 роки", callback_data="exp:1-2")],
        [InlineKeyboardButton("3–5 років", callback_data="exp:3-5"),
         InlineKeyboardButton(">5 років", callback_data="exp:>5")],
    ])
    user_name = context.user_data.get("name", "друже")
    await update.message.reply_text(
        f"Чудово, <b>{html.escape(user_name)}</b>! Ще трошки! 🤗\nСкільки років ти працюєш за спеціальністю?",
        reply_markup=keyboard, parse_mode=ParseMode.HTML
    )
    print(f"DEBUG: Запит досвіду (з повідомлення) для user_id={user_id}. Перехід до стану EXPERIENCE.")
    return EXPERIENCE


async def ask_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Функція ask_experience (з callback) викликана для user_id={user_id}.")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("<1 року", callback_data="exp:<1"),
         InlineKeyboardButton("1–2 роки", callback_data="exp:1-2")],
        [InlineKeyboardButton("3–5 років", callback_data="exp:3-5"),
         InlineKeyboardButton(">5 років", callback_data="exp:>5")],
    ])
    user_name = context.user_data.get("name", "друже")
    message_to_reply = update.callback_query.message if update.callback_query else update.message
    await message_to_reply.reply_text(
        f"Чудово, <b>{html.escape(user_name)}</b>! Ще трошки! 🤗\nСкільки років ти працюєш за спеціальністю?",
        reply_markup=keyboard, parse_mode=ParseMode.HTML
    )
    print(f"DEBUG: Запит досвіду для user_id={user_id}. Перехід до стану EXPERIENCE.")
    return EXPERIENCE


async def handle_experience_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    print(f"DEBUG: Функція handle_experience_selection викликана для user_id={user_id}. Data: {data}")
    valid_experiences = ["<1", "1-2", "3-5", ">5"]

    if data.startswith("exp:"):
        experience = data.split(":")[1]
        if experience not in valid_experiences:
            await query.edit_message_text("⚠️ Невідомий варіант досвіду. Будь ласка, вибери зі списку.")
            return EXPERIENCE

        context.user_data["experience"] = experience
        await query.edit_message_text(f"✅ Досвід: <b>{html.escape(experience)}</b> років", parse_mode=ParseMode.HTML)

        tg_id = update.effective_user.id
        user_obj = update.effective_user
        try:
            print(f"DEBUG: Збереження користувача {tg_id} в БД. Дані: {context.user_data}")
            await insert_or_update_user(
                tg_id=tg_id,
                first_name=context.user_data.get("name"),
                last_name=context.user_data.get("surname"),
                phone=context.user_data.get("phone"),
                speciality=context.user_data.get("specialty"),
                experience=experience,
                company=None,  # Поле COMPANY видалено
                username=user_obj.username,
                updated_at=datetime.now(timezone.utc)  # Використовуємо timezone.utc
            )
            await query.message.reply_text(
                "✅ Готово! Твою анкету збережено.\n\n"
                "Тепер задавай мені будь-яке питання з <b>безпеки праці</b> або проходь курс "
                "<b>“Навчання з Охорони Праці”</b> — кнопка знизу екрана.\n\n"
                "Я завжди на звʼязку — чекаю на твої питання <b>24/7</b>! \U0001FAE1",
                reply_markup=menu_keyboard, parse_mode=ParseMode.HTML
            )
            print(f"DEBUG: Дані збережено для tg_id={tg_id}. Завершення діалогу.")
        except Exception as e:
            print(f"ERROR: Не вдалося зберегти анкету в базу для {tg_id}: {e}")
            await query.message.reply_text("⚠️ Вибач, сталася помилка при збереженні анкети.")

        context.user_data.clear()  # Очищуємо "profile_started" та інші дані
        return ConversationHandler.END
    return EXPERIENCE


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    print(f"DEBUG: Функція show_profile викликана для user_id={tg_id}")
    if not await is_registered(tg_id):
        print(f"DEBUG: Користувач {tg_id} не зареєстрований (для /profile). Пропонуємо /start.")
        await update.message.reply_text("Здається, ви ще не зареєстровані. Будь ласка, напишіть /start, щоб розпочати.",
                                        reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END  # Або просто return, якщо це не частина діалогу

    try:
        user_data_from_db = None
        async with SessionLocal() as session:
            async with session.begin():
                result = await session.execute(select(User).where(User.tg_id == tg_id))
                user_data_from_db = result.scalar_one_or_none()

        if user_data_from_db is None:
            await update.message.reply_text(
                "Профіль не знайдено, хоча ви мали бути зареєстровані. Будь ласка, пройдіть реєстрацію через /start.")
            return ConversationHandler.END

        profile_text = (
            f"👤 <b>Твоя анкета:</b>\n"
            f"<b>Ім'я:</b> {html.escape(user_data_from_db.first_name or 'N/A')}\n"
            f"<b>Призвіще:</b> {html.escape(user_data_from_db.last_name or 'N/A')}\n"
            f"<b>Телефон:</b> {html.escape(user_data_from_db.phone or 'N/A')}\n"
            f"<b>Спеціальність:</b> {html.escape(user_data_from_db.speciality or 'N/A')}\n"
            f"<b>Досвід:</b> {html.escape(user_data_from_db.experience or 'N/A')}\n"
        )
        await update.message.reply_text(text=profile_text, parse_mode=ParseMode.HTML, reply_markup=menu_keyboard)
        print(f"DEBUG: Профіль показано для user_id={tg_id}.")
    except Exception as e:
        print(f"ERROR: Не вдалося завантажити профіль для {tg_id}: {e}")
        await update.message.reply_text("Вибачте, сталася помилка при завантаженні профілю.")
    return ConversationHandler.END


async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Функція update_profile викликана для user_id={user_id}")
    if not await is_registered(user_id):
        print(f"DEBUG: Користувач {user_id} не зареєстрований (для update_profile). Пропонуємо /start.")
        await update.message.reply_text("Здається, ви ще не зареєстровані. Будь ласка, напишіть /start, щоб розпочати.",
                                        reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END  # Важливо завершити, якщо це точка входу

    first_name = update.effective_user.first_name or "друже"
    await update.message.reply_text(f"Привіт, {html.escape(first_name)}! Давай оновимо анкету.")
    await asyncio.sleep(0.5)
    context.user_data["profile_started"] = True  # Встановлюємо прапорець для оновлення
    print(f"DEBUG: Користувач {user_id} оновлює профіль. Стан NAME. profile_started=True")
    await update.message.reply_text("Напиши своє імʼя")
    return NAME


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Функція cancel викликана для user_id={user_id}")
    context.user_data.clear()  # Очищуємо "profile_started" та інші дані
    await update.message.reply_text("Анкету скасовано.", reply_markup=menu_keyboard)
    print(f"DEBUG: Анкета скасована для user_id={user_id}. Діалог завершено.")
    return ConversationHandler.END


# --- ВИПРАВЛЕНО: handle_message ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id
    print(
        f"🚀 Загальний handle_message: '{text}' від user_id={user_id}. profile_started={context.user_data.get('profile_started')}")

    # Якщо ConversationHandler активний (тобто profile_started=True),
    # цей обробник не повинен нічого робити, ConversationHandler сам розбереться.
    # Ця перевірка потрібна, щоб handle_message не перехоплював повідомлення,
    # призначені для станів ConversationHandler.
    if context.user_data.get("profile_started"):
        print("DEBUG: Користувач в активній розмові (анкеті) — загальний handle_message пропускає обробку.")
        return  # Дуже важливо: не обробляти, якщо анкета активна

    # Якщо розмова не активна, обробляємо як звичайне повідомлення
    if text == "📋 Профіль":
        print(f"DEBUG: Кнопка 'Профіль' натиснута user_id={user_id} (поза анкетою).")
        return await show_profile(update, context)  # show_profile перевірить реєстрацію

    if not await is_registered(user_id):
        print(f"DEBUG: Користувач {user_id} не зареєстрований (загальний handle_message). Пропонуємо /start.")
        await update.message.reply_text(
            "Здається, ми ще не знайомі. Будь ласка, напишіть /start, щоб я міг вас зареєструвати та допомогти.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    # Користувач зареєстрований і не в анкеті - обробляємо як питання
    user = update.effective_user
    username = user.username or user.first_name
    log_message(user.id, username, update.message.message_id, "text", "question", text)

    try:
        from qa_engine import get_answer
        answer = get_answer(text)
        print(f"💬 Відповідь бота для {user_id}: {answer[:50]}...")
        await update.message.reply_text(text=answer, parse_mode=ParseMode.HTML, reply_markup=menu_keyboard)
    except ImportError:
        print("ERROR: Модуль qa_engine не знайдено!")
        await update.message.reply_text("Вибачте, мій модуль відповідей зараз недоступний.", reply_markup=menu_keyboard)
    except Exception as e:
        print(f"ERROR: Помилка при отриманні відповіді від qa_engine для {user_id}: {e}")
        await update.message.reply_text("Вибачте, сталася помилка при обробці вашого запиту.",
                                        reply_markup=menu_keyboard)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(
        f"DEBUG: Обробка голосового повідомлення від user_id={user_id}. profile_started={context.user_data.get('profile_started')}")

    if context.user_data.get("profile_started"):
        print("DEBUG: Користувач в активній розмові (анкеті) — handle_voice пропускає обробку.")
        return

    if not await is_registered(user_id):
        print(f"DEBUG: Користувач {user_id} не зареєстрований (для голосового). Пропонуємо /start.")
        await update.message.reply_text(
            "Здається, ми ще не знайомі. Будь ласка, напишіть /start, щоб я міг вас зареєструвати.",
            reply_markup=ReplyKeyboardRemove())
        return
    # ... (решта логіки handle_voice як у вас) ...
    voice = update.message.voice
    user = update.message.from_user
    username = user.username or user.first_name
    input_ogg = f"voice_{user_id}.ogg";
    output_wav = f"voice_{user_id}.wav"
    try:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(input_ogg)
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        audio = AudioSegment.from_file(input_ogg, format="ogg")
        audio = audio.set_frame_rate(16000).set_channels(1).export(output_wav, format="wav")
        with open(output_wav, "rb") as f:
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
        recognized_text = response.text
        log_message(user.id, username, update.message.message_id, "voice", "question", recognized_text)
        from qa_engine import get_answer
        answer = get_answer(recognized_text)
        await update.message.reply_text(text=answer, parse_mode=ParseMode.HTML, reply_markup=menu_keyboard)
    except FileNotFoundError:
        await update.message.reply_text("Помилка обробки аудіо: ffmpeg не знайдено.", reply_markup=menu_keyboard)
    except Exception as e:
        print(f"ERROR: Помилка голосового для {user_id}: {e}"); await update.message.reply_text(
            "Помилка обробки голосового.", reply_markup=menu_keyboard)
    finally:
        for fpath in [input_ogg, output_wav]:
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except OSError as e_os:
                    print(f"ERROR: Не вдалося видалити {fpath}: {e_os}")


async def set_bot_commands(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Розпочати роботу / Оновити профіль"),
        BotCommand("profile", "Переглянути мій профіль"),
        BotCommand("support", "Зв'язатися з підтримкою"),
        BotCommand("cancel", "Скасувати поточну дію (анкету)")
    ])


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🔁 Lifespan запускається: ініціалізація Telegram App...")
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.state.telegram_app = application

    # ConversationHandler має бути доданий ПЕРШИМ або з нижчим номером групи,
    # щоб він перехоплював повідомлення для своїх станів до загальних обробників.
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("update_profile", update_profile),
            MessageHandler(filters.Regex('^✏️ Оновити анкету$'), update_profile),
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
            PHONE: [
                MessageHandler(filters.CONTACT, process_contact_info),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)
            ],
            SPECIALTY: [
                CallbackQueryHandler(handle_specialty_selection, pattern="^spec:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_specialty)
            ],
            EXPERIENCE: [CallbackQueryHandler(handle_experience_selection, pattern="^exp:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,  # Важливо для анкет
        # map_to_parent={ # Якщо потрібно вийти з діалогу і передати керування іншому ConversationHandler (не ваш випадок зараз)
        #     ConversationHandler.END: ConversationHandler.END
        # }
    )
    application.add_handler(conv_handler, group=0)  # Додаємо з групою 0

    # Окремі команди, які мають працювати завжди
    application.add_handler(CommandHandler("support", support_command), group=1)
    application.add_handler(CommandHandler("profile", show_profile), group=1)

    # Обробник для текстової кнопки "Профіль" (якщо вона не частина діалогу)
    application.add_handler(MessageHandler(filters.Regex('^📋 Профіль$'), show_profile), group=1)

    # Загальні обробники повідомлень (текст, голос) - мають йти останніми або з вищою групою
    # Вони спрацюють, тільки якщо ConversationHandler не активний або повідомлення не для нього
    application.add_handler(MessageHandler(
        filters.VOICE & ~filters.UpdateType.EDITED_MESSAGE & ~filters.UpdateType.CHANNEL_POST,
        handle_voice
    ), group=1)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE & ~filters.UpdateType.CHANNEL_POST,
        handle_message
    ), group=1)

    # CallbackQueryHandlers, які є частиною ConversationHandler, вже визначені всередині нього.
    # Якщо є глобальні inline-кнопки, їх обробники додаються тут.
    # application.add_handler(CallbackQueryHandler(some_global_callback_handler))

    await application.initialize()
    await set_bot_commands(application)
    await application.start()
    try:
        print(f"DEBUG: Встановлюємо webhook на URL: {WEBHOOK_URL}")
        await application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
        print("✅ Webhook встановлено успішно.")
    except Exception as e:
        print(f"ERROR: Не вдалося встановити webhook: {e}")
    yield
    print("❌ Lifespan завершується: зупиняємо Telegram App...")
    await application.stop()
    try:
        print("DEBUG: Видаляємо webhook...")
        if await application.bot.delete_webhook():
            print("✅ Webhook видалено успішно.")
        else:
            print("WARN: Webhook не було видалено.")
    except Exception as e:
        print(f"ERROR: Не вдалося видалити webhook: {e}")
    await application.shutdown()


fastapi_app = FastAPI(lifespan=lifespan)


@fastapi_app.post(WEBHOOK_PATH)
async def telegram_webhook_endpoint(request: Request):
    application = request.app.state.telegram_app
    try:
        data = await request.json(); print("DEBUG: Отримано дані від Telegram:", data)
    except json.JSONDecodeError:
        print("ERROR: Не вдалося розпарсити JSON"); raise HTTPException(status_code=400, detail="Invalid JSON")
    update = Update.de_json(data, application.bot)
    if not update: print("ERROR: Не вдалося створити Update"); return Response(status_code=200)
    print(f"DEBUG: Обробляємо update_id: {update.update_id}")
    try:
        await application.process_update(update); print(f"DEBUG: Успішно оброблено update_id: {update.update_id}")
    except Exception as e:
        print(f"ERROR: Помилка при обробці update_id {update.update_id}: {e}"); return Response(status_code=200)
    return Response(status_code=200)


@fastapi_app.get("/")
async def root(): return {"message": "FastAPI server for Telegram Bot is running (Webhook Mode)"}


if __name__ == "__main__":
    print("DEBUG: Запуск FastAPI через Uvicorn (Webhook Mode)")
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)