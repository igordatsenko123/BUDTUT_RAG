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
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes,
    CommandHandler, ConversationHandler, ApplicationBuilder, ExtBot
)
from telegram.constants import ParseMode
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler
from telegram import WebAppInfo

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
#WEBHOOK_URL_BASE="https://2b8e-176-37-33-23.ngrok-free.app"
if not WEBHOOK_URL_BASE:
    raise ValueError("Не встановлено змінну середовища WEBHOOK_URL_BASE!")

WEBHOOK_PATH = f"/telegram/{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_URL_BASE}{WEBHOOK_PATH}"

client = OpenAI(api_key=OPENAI_API_KEY)


LOG_FILE = "chat_history.csv"

NAME, SURNAME, PHONE, SPECIALTY, EXPERIENCE = range(5)

menu_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💪 Навчальний курс", web_app=WebAppInfo(url="https://safe-weld-path.lovable.app/module"))]
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

# === Анкета та Обробники
from telegram import ReplyKeyboardRemove

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пиши нам тут:\nhttps://t.me/ai_safety_coach_support"
    )
async def entry_point_for_new_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(
        f"DEBUG: entry_point_for_new_user_text: Received update. Message text: '{update.message.text if update.message else 'No message'}'")
    """
    Цей entry_point для ConversationHandler спрацьовує на текстові повідомлення.
    Він починає анкету, якщо користувач незареєстрований і анкета ще не почата.
    """
    user_id = update.effective_user.id

    is_prof_started = context.user_data.get("profile_started")
    user_is_registered = await is_registered(user_id)
    print(f"DEBUG: entry_point_for_new_user_text: profile_started={is_prof_started}, is_registered={user_is_registered}")

    if is_prof_started or user_is_registered:
        print(f"DEBUG: entry_point_for_new_user_text: Condition met, returning None.")
        return None # Важливо для передачі керування іншим обробникам

    # Якщо анкета вже активна (наприклад, через /start) АБО користувач вже зареєстрований,
    # цей entry_point не повинен втручатися. Повернення None дозволить
    # ConversationHandler передати обробку іншим хендлерам (включаючи основний handle_message).
    if context.user_data.get("profile_started") or await is_registered(user_id):
        return None # Важливо для передачі керування іншим обробникам

    # Користувач не зареєстрований, і анкета ще не почата. Починаємо.
    print(f"DEBUG: entry_point_for_new_user_text: User {user_id} is new. Initiating survey.")
    await update.message.reply_text(
        "Привіт! Я твій помічник з <b>безпеки праці </b> Я допоможу тобі із будь-яким питанням! Давай знайомитись 😊",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML
    )
    await asyncio.sleep(1)
    await update.message.reply_text("Напиши своє імʼя", parse_mode=ParseMode.HTML)
    context.user_data["profile_started"] = True
    return NAME # Повертаємо початковий стан для ConversationHandler

async def check_and_interrupt_if_profile_started(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Перевіряє, чи користувач перебуває в анкеті.
    Якщо так — повідомляє про переривання та очищає context.user_data.
    Повертає True, якщо анкету було перервано.
    """
    if context.user_data.get("profile_started"):
        await update.message.reply_text(
            "⚠️ Анкету перервано. Якщо хочеш — почни заново з /start або /update_profile.",
            reply_markup=menu_keyboard
        )
        context.user_data.clear()
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if args:
        source_id = args[0]
        print(f"DEBUG: Користувач {user_id} перейшов по посиланню з параметром: {source_id}")
        context.user_data["ref_source"] = source_id

        # Якщо юзер вже є — оновимо тільки ref_source
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.tg_id == user_id))
            user = result.scalar_one_or_none()
            if user and user.ref_source != source_id:
                print(f"DEBUG: Оновлюємо ref_source для {user_id} → {source_id}")
                user.ref_source = source_id
                await session.commit()
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

async def handle_specialty_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("spec:"):
        specialty = data.replace("spec:", "")
        context.user_data["specialty"] = specialty
        await query.edit_message_text(f"✅ Спеціальність: <b>{html.escape(specialty)}</b>", parse_mode=ParseMode.HTML)
        return await ask_experience(update, context)



async def ask_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("<1 року", callback_data="exp:<1"),
         InlineKeyboardButton("1–2 роки", callback_data="exp:1-2")],
        [InlineKeyboardButton("3–5 років", callback_data="exp:3-5"),
         InlineKeyboardButton(">5 років", callback_data="exp:>5")],
    ])

    chat = update.effective_chat
    user_name = context.user_data.get("name", "друже")

    await context.bot.send_message(
        chat_id=chat.id,
        text=f"Чудово, <b>{html.escape(user_name)}</b>! Ще трошки! 🤗",
        parse_mode=ParseMode.HTML
    )

    await asyncio.sleep(1)

    await context.bot.send_message(
        chat_id=chat.id,
        text="Скільки років ти працюєш за спеціальністю?",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return EXPERIENCE

async def handle_experience_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
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
            await insert_or_update_user(
                tg_id=tg_id,
                first_name=context.user_data.get("name"),
                last_name=context.user_data.get("surname"),
                phone=context.user_data.get("phone"),
                speciality=context.user_data.get("specialty"),
                experience=experience,
                username=user_obj.username,
                updated_at=datetime.utcnow(),
                ref_source=context.user_data.get("ref_source")
            )

            await query.message.reply_text(
                "✅ Готово! Тепер задавай мені будь-яке питання з безпеки праці або проходь курс <b>Навчання з Охорони Праці</b> — кнопка знизу екрана",
                parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(1)  # ⏱️ Затримка в 1 секунду

            await query.message.reply_text(
                "Я завжди на звʼязку — чекаю на твої питання 24/7! \U0001FAE1",
                reply_markup=menu_keyboard,
                parse_mode = ParseMode.HTML
            )
            context.user_data.pop("profile_started", None)  # Видаляємо прапор
            context.user_data.clear()
            return ConversationHandler.END
        except Exception as e:
            print(f"ERROR: Не вдалося зберегти анкету в базу: {e}")
            await query.message.reply_text("⚠️ Вибач, сталася помилка при збереженні анкети.")
            context.user_data.pop("profile_started", None)  # Видаляємо прапор
            context.user_data.clear()
            return ConversationHandler.END




async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    try:
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.tg_id == tg_id))
            user = result.scalar_one_or_none()

            if user is None:
                print(f"DEBUG: Користувач {tg_id} не знайдений у базі — запускаємо start()")
                return await start(update, context)

            profile_text = (
                f"👤 <b>Твоя анкета:</b>\n"
                f"<b>Ім'я:</b> {user.first_name or 'N/A'}\n"
                f"<b>Призвіще:</b> {user.last_name or 'N/A'}\n"
                f"<b>Телефон:</b> {user.phone or 'N/A'}\n"
                f"<b>Спеціальність:</b> {user.speciality or 'N/A'}\n"
                f"<b>Досвід:</b> {user.experience or 'N/A'}\n"
            )

            # Показываем профиль и одновременно обновляем клавиатуру
            await update.message.reply_text(
                text=profile_text,
                parse_mode=ParseMode.HTML,
                reply_markup=menu_keyboard  # ← актуальная клавиатура здесь
            )

    except Exception as e:
        print(f"ERROR: Не вдалося завантажити профіль для {tg_id}: {e}")
        await update.message.reply_text("Вибачте, сталася помилка при завантаженні профілю.")

    #return ConversationHandler.END
    return



async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_registered(user_id):
        print(f"DEBUG: Користувач {tg_id} не знайдений у базі — запускаємо start()")
        return await start(update, context)

    print("DEBUG: Оновлення профілю")

    first_name = update.effective_user.first_name or "друже"

    await update.message.reply_text(f"Привіт, {html.escape(first_name)}! Давай оновимо анкету.")
    await asyncio.sleep(1)  # ⏱️ Затримка в 1 секунду

    await update.message.reply_text("Напиши своє імʼя")
    return NAME



async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Анкету скасовано.", reply_markup=menu_keyboard)
    return ConversationHandler.END

async def handle_user_question_with_thinking(update: Update, context: ContextTypes.DEFAULT_TYPE, get_answer_func):

    question = update.message.text

    try:
        answer = get_answer_func(question)
        await update.message.reply_text(answer, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text("Вибач, сталася помилка при обробці запиту.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_and_interrupt_if_profile_started(update, context):
        return

    print(f"DEBUG: handle_message: TOP LEVEL. Received update. Message text: '{update.message.text if update.message and update.message.text else 'Non-text or no message'}'")

    if not update.message or not update.message.text:
        print("DEBUG: handle_message: No message or no text in message. Returning.")
        return

    # 🔒 Перевірка: якщо користувач у процесі анкети — не обробляємо повідомлення
    if context.user_data.get("profile_started"):
        print("DEBUG: Користувач проходить анкету — handle_message пропущено.")
        return

    print("🚀 Отримано текстове повідомлення:", update.message.text)
    user_id = update.effective_user.id
    text = update.message.text

    if text == "📋 Профіль":
        return await show_profile(update, context)

    user_is_registered = await is_registered(user_id)
    print(f"DEBUG: handle_message: is_registered={user_is_registered} for user_id={user_id}")

    if not user_is_registered:
        print(f"DEBUG: handle_message: User {user_id} is not registered. Prompting to /start.")
        await update.message.reply_text(
            "Спочатку треба зареєструватися. Будь ласка, введи команду /start, щоб розпочати."
        )
        return


    user = update.effective_user
    username = user.username or user.first_name
    log_message(user.id, username, update.message.message_id, "text", "question", text)

    try:
        from qa_engine import get_answer
        answer = get_answer(text)

        await update.message.reply_text(
            text=answer,
            parse_mode=ParseMode.HTML,
            reply_markup=menu_keyboard
        )

    except ImportError:
        print("ERROR: Модуль qa_engine не знайдено!")
        await update.message.reply_text("Вибачте, мій модуль відповідей зараз недоступний.")
    except Exception as e:
        print(f"ERROR: Помилка при отриманні відповіді від qa_engine: {e}")
        await update.message.reply_text("Вибачте, сталася помилка при обробці вашого запиту.")



async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if await check_and_interrupt_if_profile_started(update, context):
        return

    user_id = update.effective_user.id
    print("DEBUG: Обробка голосового повідомлення")

    # 🔒 Перевірка: якщо користувач у процесі анкети — не обробляємо голос
    if context.user_data.get("profile_started"):
        print("DEBUG: Користувач проходить анкету — handle_voice пропущено.")
        return

    if not await is_registered(user_id):
        print(f"DEBUG: Користувач {user_id} не зареєстрований — запускаємо start()")
        await update.message.reply_text(
            "Здається, ви ще не зареєстровані. Будь ласка, використайте команду /start, щоб розпочати."
        )
        return

    voice = update.message.voice
    user = update.message.from_user
    username = user.username or user.first_name

    input_ogg = f"voice_{user_id}.ogg"
    output_wav = f"voice_{user_id}.wav"

    try:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(input_ogg)
        print(f"DEBUG: Voice file downloaded to {input_ogg}")

        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        audio = AudioSegment.from_file(input_ogg, format="ogg")
        audio = audio.set_frame_rate(16000).set_channels(1)
        audio.export(output_wav, format="wav")
        print(f"DEBUG: Converted file saved to {output_wav}")

        with open(output_wav, "rb") as f:
            print("DEBUG: Отправка в Whisper API")
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
        recognized_text = response.text
        print(f"DEBUG: Роспізнаний текст: {recognized_text}")

        log_message(user.id, username, update.message.message_id, "voice", "question", recognized_text)

        from qa_engine import get_answer
        answer = get_answer(recognized_text)

        await update.message.reply_text(
            text=answer,
            parse_mode=ParseMode.HTML,
            reply_markup=menu_keyboard
        )

    except FileNotFoundError:
        print("ERROR: ffmpeg не знайдено.")
        await update.message.reply_text("Помилка обробки аудіо: ffmpeg не знайдено.")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: ffmpeg failed: {e}")
        print(f"ERROR: ffmpeg stdout: {e.stdout}")
        print(f"ERROR: ffmpeg stderr: {e.stderr}")
        await update.message.reply_text("Не вдалося обробити голосове повідомлення (помилка конвертації).")
    except ImportError:
        print("ERROR: Модуль qa_engine не знайдено!")
        await update.message.reply_text("Вибачте, мій модуль відповідей зараз недоступний.")
    except Exception as e:
        print(f"ERROR: Помилка під час обробки голосового повідомлення: {e}")
        await update.message.reply_text("Виникла помилка під час обробки вашого голосового запиту.")
    finally:
        for fpath in [input_ogg, output_wav]:
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                    print(f"DEBUG: Removed temp file {fpath}")
                except OSError as e:
                    print(f"ERROR: Could not remove temp file {fpath}: {e}")



from telegram import BotCommand

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("support", "поскаржитися"),
        BotCommand("profile", "показати профіль"),
        BotCommand("update_profile", "редагувати профіль"),
    ])
async def handle_interruption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("profile_started"):
        await update.message.reply_text(
            "⚠️ Анкетування перервано. Якщо хочеш — можеш <b>почати заново</b> командою /start або /update_profile",
            parse_mode=ParseMode.HTML,
            reply_markup=menu_keyboard
        )
        # Скидаємо флаг анкети та стан
        context.user_data["profile_started"] = False
        return ConversationHandler.END
    return ConversationHandler.END


# --- Lifespan для ініціалізації та зупинки бота ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🔁 Lifespan запускається: ініціалізація Telegram App...")

    # 1. Ініціалізація Telegram Application
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.state.telegram_app = application

    # 2. Хендлер анкети (поетапне опитування)
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            #MessageHandler(filters.TEXT & ~filters.COMMAND, entry_point_for_new_user_text),
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
            SPECIALTY: [CallbackQueryHandler(handle_specialty_selection, pattern="^spec:")],
            EXPERIENCE: [CallbackQueryHandler(handle_experience_selection, pattern="^exp:")],
        },

        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, handle_interruption)  # <-- новий хендлер
        ],
        per_message=False
    )
    application.add_handler(conv_handler)

    # 3. Команди / функціональні хендлери
    #application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("profile", show_profile))
    #application.add_handler(CommandHandler("update_profile", update_profile))

    # 4. Хендлери на текстові кнопки
    application.add_handler(MessageHandler(filters.Regex('^📋 Профіль$'), show_profile))
    # Обробка голосу — лише якщо не в середині анкети
    application.add_handler(
        MessageHandler(
            filters.VOICE & ~filters.UpdateType.EDITED & ~filters.UpdateType.CHANNEL_POST,
            handle_voice
        )
    )

    # Обробка тексту — лише якщо не команда і не в стані анкети
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.EDITED & ~filters.UpdateType.CHANNEL_POST,
            handle_message
        )
    )

    # 5. Callback-хендлери (для кнопок типу InlineKeyboard)
    #application.add_handler(CallbackQueryHandler(handle_experience_selection, pattern="^exp:"))
    #application.add_handler(CallbackQueryHandler(handle_specialty_selection, pattern="^spec:"))

    # 6. Запуск
    await application.initialize()
    await set_bot_commands(application)
    await application.start()

    # 7. Встановлення webhook
    try:
        print(f"DEBUG: Встановлюємо webhook на URL: {WEBHOOK_URL}")
        await application.bot.set_webhook(
            url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES
            # secret_token=WEBHOOK_SECRET_TOKEN
        )
        print("✅ Webhook встановлено успішно.")
    except Exception as e:
        print(f"ERROR: Не вдалося встановити webhook: {e}")

    yield

    # 8. Завершення
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


# === FastAPI Додаток ===
fastapi_app = FastAPI(lifespan=lifespan)

@fastapi_app.post(WEBHOOK_PATH)
async def telegram_webhook_endpoint(request: Request):
    application = request.app.state.telegram_app
    try:
        data = await request.json()
        print("DEBUG: Отримано дані від Telegram:", data)
    except json.JSONDecodeError:
        print("ERROR: Не вдалося розпарсити JSON від Telegram")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON data")
    update = Update.de_json(data, application.bot)
    if not update:
        print("ERROR: Не вдалося створити об'єкт Update з даних")
        return Response(status_code=status.HTTP_200_OK)
    print(f"DEBUG: Обробляємо update_id: {update.update_id}")
    try:
        await application.process_update(update)
        print(f"DEBUG: Успішно оброблено update_id: {update.update_id}")
    except Exception as e:
        print(f"ERROR: Помилка при обробці update_id {update.update_id}: {e}")
        return Response(status_code=status.HTTP_200_OK)
    return Response(status_code=status.HTTP_200_OK)

@fastapi_app.get("/")
async def root():
    return {"message": "FastAPI server for Telegram Bot is running (Webhook Mode)"}

if __name__ == "__main__":
    print("DEBUG: Запуск FastAPI через Uvicorn (Webhook Mode)")
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
