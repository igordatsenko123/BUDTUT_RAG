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

# === Анкета та Обробники
from telegram import ReplyKeyboardRemove

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пиши нам тут:\nhttps://t.me/ai_safety_coach_support"
    )

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
            return NAME
    else:
        await update.message.reply_text(
            "Привіт! Я твій помічник з безпеки праці ⛑️ Я допоможу тобі із будь-яким питанням! Давай знайомитись 😊\nНапиши своє імʼя",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.HTML
        )
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


    return await ask_specialty(update, context, remove_keyboard=True)


async def process_contact_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.effective_user.id

    if contact.user_id != user_id:
        await update.message.reply_text("Будь ласка, поділись своїм власним контактом.")
        return PHONE

    phone_number = contact.phone_number
    print(f"DEBUG: Отримано контакт (через кнопку): {phone_number} від user_id={user_id}")

    digits_only = re.sub(r"\\D", "", phone_number)
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


    return await ask_specialty(update, context, remove_keyboard=True)

async def ask_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE, remove_keyboard=False):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Зварювальник", callback_data="spec:Зварювальник")],
        [InlineKeyboardButton("Муляр", callback_data="spec:Муляр")],
        [InlineKeyboardButton("Монолітник", callback_data="spec:Монолітник")],
        [InlineKeyboardButton("Арматурник", callback_data="spec:Арматурник")],
        [InlineKeyboardButton("Інша спеціальність", callback_data="spec:other")]
    ])

    await update.message.reply_text(
        "Добре! Обери свою спеціальність",
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
            await query.edit_message_text("✏️ Напиши вручну свою спеціальність:")
            return SPECIALTY
        else:
            context.user_data["specialty"] = specialty
            await query.edit_message_text(f"✅ Спеціальність: <b>{html.escape(specialty)}</b>", parse_mode=ParseMode.HTML)
            return await ask_experience(update, context)

async def handle_manual_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    specialty = update.message.text.strip()

    # Базовая валидация
    if not specialty or len(specialty) < 2 or any(c in specialty for c in "!@#$%^&*(){}[]<>"):
        await update.message.reply_text(
            "⚠️ Введ коректну спеціальність (не менше 2 літер, без спецсимволів)."
        )
        return SPECIALTY

    if specialty in ["📋 Профіль", "✏️ Оновити анкету"]:
        await update.message.reply_text(
            "⚠️ Це виглядає як кнопка. Введи свою спеціальність вручну."
        )
        return SPECIALTY

    context.user_data["specialty"] = specialty
    await update.message.reply_text(
        f"✅ Спеціальність збережено: <b>{html.escape(specialty)}</b>",
        parse_mode=ParseMode.HTML
    )
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
        text=f"Чудово, <b>{html.escape(user_name)}</b>! Ще трошки! 🤗\nСкільки років ти працюєш за спеціальністю?",
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
                updated_at=datetime.utcnow()
            )

            await query.message.reply_text(
                "✅ Готово! Тепер задавай мені будь-яке питання з безпеки праці або проходь курс “Навчання з Охорони Праці” — кнопка знизу екрана",
                parse_mode=ParseMode.HTML
            )
            await query.message.reply_text(
                "Я завжди на звʼязку — чекаю на твої питання 24/7!",
                reply_markup=menu_keyboard
            )
            context.user_data.clear()
            return ConversationHandler.END
        except Exception as e:
            print(f"ERROR: Не вдалося зберегти анкету в базу: {e}")
            await query.message.reply_text("⚠️ Вибач, сталася помилка при збереженні анкети.")
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

    return ConversationHandler.END


async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_registered(user_id):
        await update.message.reply_text("Ти ще не зареєстрований. Напиши /start.")
        return ConversationHandler.END

    print("DEBUG: Оновлення профілю")
    await update.message.reply_text(f"Привіт, {html.escape(name)}! Давай оновимо анкету.")
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
        answer = get_answer(text)

        # Отправляем ответ с клавиатурой
        await update.message.reply_text(
            text=answer,
            parse_mode=ParseMode.HTML,
            reply_markup=menu_keyboard  # ← сразу прикрепляем актуальное меню
        )

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
        answer = get_answer(recognized_text)

        # Финальный ответ с клавиатурой
        await update.message.reply_text(
            text=answer,
            parse_mode=ParseMode.HTML,
            reply_markup=menu_keyboard
        )

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




from telegram import BotCommand

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("support", "поскаржитися"),
        BotCommand("profile", "показати профіль"),
        BotCommand("update_profile", "редагувати профіль"),
    ])

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
        per_message=False
    )
    application.add_handler(conv_handler)

    # 3. Команди / функціональні хендлери
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("profile", show_profile))
    application.add_handler(CommandHandler("update_profile", update_profile))

    # 4. Хендлери на текстові кнопки
    application.add_handler(MessageHandler(filters.Regex('^📋 Профіль$'), show_profile))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 5. Callback-хендлери (для кнопок типу InlineKeyboard)
    application.add_handler(CallbackQueryHandler(handle_experience_selection, pattern="^exp:"))
    application.add_handler(CallbackQueryHandler(handle_specialty_selection, pattern="^spec:"))

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
