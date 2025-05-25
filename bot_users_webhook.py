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

NAME, SURNAME, PHONE, SPECIALTY, EXPERIENCE, COMPANY = range(6)

menu_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📚 Навчальний курс", web_app=WebAppInfo(url="https://igordatsenko123.github.io/TG_WEB_APP_AISAFETYCOACH/?v=4"))]
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

async def handle_user_question_with_thinking(update: Update, context: ContextTypes.DEFAULT_TYPE, get_answer_func):
    """
    Обрабатывает вопрос пользователя с отложенным сообщением "Степанич думає...",
    если ответ не отправлен в течение 5 секунд.
    """
    question = update.message.text

    async def send_thinking_message():
        await asyncio.sleep(5)
        if not response_event.is_set():
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Степанич думає...",
                parse_mode=ParseMode.HTML
            )

    async def get_answer_and_respond():
        try:
            answer = get_answer_func(question)
            await update.message.reply_text(answer, parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text("Вибач, сталася помилка при обробці запиту.")
        finally:
            response_event.set()

    response_event = asyncio.Event()
    await asyncio.gather(
        send_thinking_message(),
        get_answer_and_respond()
    )

# === Перевірка реєстрації ===
async def is_registered(user_id: int) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == user_id))
        user = result.scalar_one_or_none()
        return user is not None

# === Анкета та Обробники (Ваш код без змін) ===
# Тут йдуть ваші функції: start, get_name, get_surname, get_phone,
# get_specialty, cancel, show_profile, update_profile, handle_message, handle_voice
# Важливо: Вони мають бути визначені ДО того, як вони додаються як хендлери в lifespan
# (Код функцій з вашого попереднього повідомлення сюди)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Команда /start от user_id={user_id}")

    if await is_registered(user_id):
        try:
            async with SessionLocal() as session:
                result = await session.execute(select(User).where(User.tg_id == user_id))
                user = result.scalar_one_or_none()

                if user and user.first_name:
                    await update.message.reply_text(
                        f"З поверненням, {user.first_name}!\nГотовий відповідати на твої запитання:",
                        reply_markup=menu_keyboard
                    )
                    return ConversationHandler.END
                else:
                    raise ValueError("Дані користувача не знайдено")

        except Exception as e:
            print(f"ERROR: Не вдалося завантажити профіль для {user_id}: {e}")
            await update.message.reply_text(
                "Вибачте, виникла помилка з вашим профілем. Давайте заповнимо анкету знову. Як тебе звати?"
            )
            return NAME
    else:
        await update.message.reply_text("Привіт! Давай для початку познайомимося. Як тебе звати?")
        return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Получено имя: {update.message.text}")
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Призвіще?")
    return SURNAME

async def get_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["surname"] = update.message.text

    contact_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Поділитися номером телефону", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await update.message.reply_text(
        "Дякую. Тепер, будь ласка, поділіться номером телефону або введіть його вручну у форматі:\n"
        "`+380 (XX) XXX XX XX`",
        reply_markup=contact_keyboard,
        parse_mode=ParseMode.MARKDOWN
    )
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_phone = update.message.text.strip()
    print(f"DEBUG: Отримано телефон (текстом): {raw_phone}")

    # Видаляємо всі символи, крім цифр
    digits_only = re.sub(r"\D", "", raw_phone)

    # Нормалізуємо номер:
    if digits_only.startswith("0") and len(digits_only) == 10:
        normalized = "+380" + digits_only[1:]
    elif digits_only.startswith("380") and len(digits_only) == 12:
        normalized = "+" + digits_only
    elif digits_only.startswith("67") or digits_only.startswith("68") or digits_only.startswith("50") or digits_only.startswith("63"):
        # Без коду країни — вважаємо валідним
        normalized = "+380" + digits_only
    else:
        await update.message.reply_text(
            "⚠️ Невірний формат номеру.\n"
            "Приклад коректного номеру: `+380 (67) 123 45 67`, `0671234567`, або `67 123 45 67`",
            parse_mode=ParseMode.MARKDOWN
        )
        return PHONE

    context.user_data["phone"] = normalized
    print(f"DEBUG: Нормалізований номер: {normalized}")

    await update.message.reply_text(
        "Спеціальність?",
        reply_markup=ReplyKeyboardRemove()
    )
    return await ask_specialty(update, context)




async def process_contact_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.effective_user.id

    # Важлива перевірка: користувач має поділитися СВОЇМ контактом
    if contact.user_id != user_id:
        await update.message.reply_text(
            "Будь ласка, поділіться вашим власним контактом.",
            # Можна знову надіслати клавіатуру для запиту контакту, якщо потрібно
        )
        # Залишаємося в тому ж стані, щоб дозволити повторну спробу або текстове введення
        return PHONE

    phone_number = contact.phone_number
    print(f"DEBUG: Отримано контакт (через кнопку): {phone_number} від user_id={user_id}")
    context.user_data["phone"] = phone_number

    await update.message.reply_text(
        f"Дякую, ваш номер {phone_number} збережено. Тепер вкажіть вашу спеціальність?",
        reply_markup=ReplyKeyboardRemove()  # Прибираємо клавіатуру "Поділитися номером"
    )
    return await ask_specialty(update, context)

async def ask_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Зварювальник", callback_data="spec:Зварювальник")],
        [InlineKeyboardButton("Монтажник", callback_data="spec:Монтажник")],
        [InlineKeyboardButton("Слюсар", callback_data="spec:Слюсар")],
        [InlineKeyboardButton("Череззаборногуперкидатор", callback_data="spec:Череззаборногуперкидатор")],
        [InlineKeyboardButton("Роздолбай", callback_data="spec:Роздолбай")],
        [InlineKeyboardButton("Інша спеціальність", callback_data="spec:other")]
    ])

    await update.message.reply_text(
        "Виберіть свою спеціальність:",
        reply_markup=keyboard
    )
    return SPECIALTY

async def handle_specialty_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("spec:"):
        specialty = data.replace("spec:", "")
        if specialty == "other":
            await query.edit_message_text("✏️ Напишіть вручну вашу спеціальність:")
            return SPECIALTY  # Ждем текстовое сообщение
        else:
            context.user_data["specialty"] = specialty
            await query.edit_message_text(f"✅ Спеціальність: {specialty}")
            return await ask_experience(update, context)

async def handle_manual_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    specialty = update.message.text.strip()
    context.user_data["specialty"] = specialty
    await update.message.reply_text(f"✅ Спеціальність збережено: {specialty}")
    return await ask_experience(update, context)


async def ask_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("0–2 роки", callback_data="exp:0-2"),
         InlineKeyboardButton("3–5 років", callback_data="exp:3-5")],
        [InlineKeyboardButton("6–10 років", callback_data="exp:6-10"),
         InlineKeyboardButton("11+ років", callback_data="exp:11+")],
    ])

    chat = update.effective_chat
    await context.bot.send_message(
        chat_id=chat.id,
        text="Скільки у вас досвіду роботи?",
        reply_markup=keyboard
    )
    return EXPERIENCE



async def handle_experience_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("exp:"):
        experience = data.split(":")[1]
        context.user_data["experience"] = experience

        await query.edit_message_text(f"✅ Досвід: {experience} років")
        await query.message.reply_text("Вкажіть назву компанії, в якій ви працюєте (або працювали):")
        return COMPANY



async def get_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["company"] = update.message.text
    tg_id = update.effective_user.id
    user_obj = update.effective_user
    try:
        await insert_or_update_user(
            tg_id=tg_id,
            first_name=context.user_data.get("name"),
            last_name=context.user_data.get("surname"),
            phone=context.user_data.get("phone"),
            speciality=context.user_data.get("specialty"),
            experience=context.user_data.get("experience"),
            company=context.user_data.get("company"),
            username=user_obj.username,
            updated_at=datetime.utcnow()
        )
        await update.message.reply_text("Дякую! Анкету збережено. Тепер давай продовжимо спілкування 😊", reply_markup=menu_keyboard)
        print(f"DEBUG: Дані збережено для tg_id={tg_id}")
    except Exception as e:
        print(f"ERROR: Не вдалося зберегти анкету в базу для {tg_id}: {e}")
        await update.message.reply_text("Вибач, сталася помилка при збереженні анкети.")

    context.user_data.clear()
    return ConversationHandler.END

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    try:
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.tg_id == tg_id))
            user = result.scalar_one_or_none()

            if user is None:
                await update.message.reply_text("Ти ще не зареєстрований. Напиши /start.")
                return ConversationHandler.END

            profile_text = (
                f"👤 <b>Твоя анкета:</b>\n"
                f"<b>Ім'я:</b> {user.first_name or 'N/A'}\n"
                f"<b>Призвіще:</b> {user.last_name or 'N/A'}\n"
                f"<b>Телефон:</b> {user.phone or 'N/A'}\n"
                f"<b>Спеціальність:</b> {user.speciality or 'N/A'}\n"
                f"<b>Досвід:</b> {user.experience or 'N/A'}\n"
                f"<b>Компанія:</b> {user.company or 'N/A'}"
            )

            await update.message.reply_text(profile_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        print(f"ERROR: Не вдалося завантажити профіль для {tg_id}: {e}")
        await update.message.reply_text("Вибачте, сталася помилка при завантаженні профілю.")




async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_registered(user_id):
        await update.message.reply_text("Ти ще не зареєстрований. Напиши /start.")
        return ConversationHandler.END

    print("DEBUG: Оновлення профілю")
    await update.message.reply_text("Оновимо анкету. Як тебе звати?")
    return NAME


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Анкету скасовано.", reply_markup=menu_keyboard)
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    print("🚀 Отримано текстове повідомлення:", update.message.text)
    user_id = update.effective_user.id
    text = update.message.text

    if text == "📋 Профіль":
        return await show_profile(update, context)

    if not await is_registered(user_id):
        await update.message.reply_text("Спочатку треба заповнити анкету. Напиши /start.")
        return

    user = update.effective_user
    username = user.username or user.first_name
    log_message(user.id, username, update.message.message_id, "text", "question", text)

    try:
        from qa_engine import get_answer
        await handle_user_question_with_thinking(update, context, get_answer)
    except ImportError:
        print("ERROR: Модуль qa_engine не знайдено!")
        await update.message.reply_text("Вибачте, мій модуль відповідей зараз недоступний.")
    except Exception as e:
        print(f"ERROR: Помилка при отриманні відповіді від qa_engine: {e}")
        await update.message.reply_text("Вибачте, сталася помилка при обробці вашого запиту.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print("DEBUG: Обробка голосового повідомлення")
    if not await is_registered(user_id):
        await update.message.reply_text("Спочатку треба заповнити анкету. Напиши /start.")
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

        print("DEBUG: Конвертація через ffmpeg")
        process = subprocess.run(
            ["ffmpeg", "-y", "-i", input_ogg, "-acodec", "pcm_s16le", "-ar", "16000", output_wav],
            capture_output=True, text=True, check=True
        )
        print("DEBUG: ffmpeg stdout:", process.stdout)
        print("DEBUG: ffmpeg stderr:", process.stderr)
        print(f"DEBUG: Converted file saved to {output_wav}")

        with open(output_wav, "rb") as f:
            print("DEBUG: Отправка в Whisper API")
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
        recognized_text = response.text
        print(f"DEBUG: Роспізнаний текст: {recognized_text}")

        log_message(user.id, username, update.message.message_id, "voice", "question", recognized_text)

        from qa_engine import get_answer
        await handle_user_question_with_thinking(update, context, get_answer)
    except FileNotFoundError:
        print("ERROR: ffmpeg не знайдено. Переконайтесь, що він встановлений та є в PATH.")
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


# --- Lifespan для ініціалізації та зупинки бота ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🔁 Lifespan запускається: ініціалізація Telegram App...")
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.state.telegram_app = application

    # --- ВИДАЛІТЬ ЦІ РЯДКИ ІМПОРТУ ---
    # from main_handlers import start, get_name, get_surname, get_phone, get_specialty, cancel
    # from main_handlers import show_profile, update_profile, handle_message, handle_voice
    # --- КІНЕЦЬ ВИДАЛЕННЯ ---

    # Оскільки функції start, get_name і т.д. визначені в цьому ж файлі,
    # вони вже доступні тут за своїми іменами.

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start), # Використовуємо 'start' напряму
            CommandHandler("update_profile", update_profile),
            MessageHandler(filters.Regex('^✏️ Оновити анкету$'), update_profile), # Використовуємо 'update_profile' напряму
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
            # --- ОНОВЛЕНО СТАН PHONE ---
            PHONE: [
                MessageHandler(filters.CONTACT, process_contact_info), # Обробник для отриманого контакту
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)  # Обробник для текстового введення номера
            ],
            # --- КІНЕЦЬ ОНОВЛЕННЯ ---
            SPECIALTY: [CallbackQueryHandler(handle_specialty_selection, pattern="^spec:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_specialty)],
            EXPERIENCE: [CallbackQueryHandler(handle_experience_selection, pattern="^exp:")],
            COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_company)],
        },
        fallbacks=[CommandHandler("cancel", cancel)], # Використовуємо 'cancel' напряму
        per_message=False
    )
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex('^📋 Профіль$'), show_profile)) # Використовуємо 'show_profile' напряму
    application.add_handler(CommandHandler("profile", show_profile)) # Те саме
    application.add_handler(MessageHandler(filters.VOICE, handle_voice)) # Використовуємо 'handle_voice' напряму
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)) # Використовуємо 'handle_message' напряму
    application.add_handler(CallbackQueryHandler(handle_experience_selection, pattern="^exp:"))
    application.add_handler(CallbackQueryHandler(handle_specialty_selection, pattern="^spec:"))

    await application.initialize()
    await application.start()
    try:
        print(f"DEBUG: Встановлюємо webhook на URL: {WEBHOOK_URL}")
        # !!! ЗВЕРНІТЬ УВАГУ: Ви раніше використовували WEBHOOK_SECRET_TOKEN.
        # Якщо він потрібен, його слід додати сюди.
        await application.bot.set_webhook(
            url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES
            # secret_token=WEBHOOK_SECRET_TOKEN # Розкоментуйте, якщо використовуєте секретний токен
        )
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
