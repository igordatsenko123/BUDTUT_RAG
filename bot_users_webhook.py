import os
import json
import subprocess
import pandas as pd
from datetime import datetime
import asyncio

# --- Telegram ---
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes,
    CommandHandler, ConversationHandler, ApplicationBuilder, ExtBot
)
from telegram.constants import ParseMode

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

USER_FILE = "user_info.json"
LOG_FILE = "chat_history.csv"

NAME, SURNAME, PHONE, SPECIALTY = range(4)

menu_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("📋 Профіль")], [KeyboardButton("✏️ Оновити анкету")]],
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
def is_registered(user_id):
    print(f"DEBUG: Перевіряємо реєстрацію user_id={user_id}")
    if not os.path.exists(USER_FILE):
        return False
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str(user_id) in data
    except (FileNotFoundError, json.JSONDecodeError):
        return False



# === Анкета та Обробники (Ваш код без змін) ===
# Тут йдуть ваші функції: start, get_name, get_surname, get_phone,
# get_specialty, cancel, show_profile, update_profile, handle_message, handle_voice
# Важливо: Вони мають бути визначені ДО того, як вони додаються як хендлери в lifespan
# (Код функцій з вашого попереднього повідомлення сюди)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Команда /start от user_id={user_id}")
    if is_registered(user_id):
        try:
            with open(USER_FILE, "r", encoding="utf-8") as f:
                name = json.load(f)[str(user_id)]["name"]
            await update.message.reply_text(
                f"З поверненням, {name}!\nГотовий відповідати на твої запитання:",
                reply_markup=menu_keyboard
            )
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
             print(f"ERROR: Помилка читання профілю для {user_id}: {e}")
             # Якщо профіль не знайдено, можливо, файл пошкоджено, починаємо знову
             await update.message.reply_text("Вибачте, виникла помилка з вашим профілем. Давайте заповнимо анкету знову. Як тебе звати?")
             return NAME
        return ConversationHandler.END
    else:
        await update.message.reply_text("Привіт! Давай для початку познайомимося. Як тебе звати?")
        return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Получено имя: {update.message.text}")
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Призвіще?")
    return SURNAME

async def get_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Получена фамилия: {update.message.text}")
    context.user_data["surname"] = update.message.text
    await update.message.reply_text("Телефон?")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Получен телефон: {update.message.text}")
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Спеціальність?")
    return SPECIALTY

async def get_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: Завершення анкети")
    context.user_data["specialty"] = update.message.text
    user_id = str(update.effective_user.id)

    user_info = {
        "name": context.user_data["name"],
        "surname": context.user_data["surname"],
        "phone": context.user_data["phone"],
        "specialty": context.user_data["specialty"]
    }

    try:
        if os.path.exists(USER_FILE):
            with open(USER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}

        data[user_id] = user_info
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"DEBUG: Анкета збережена для user_id={user_id}")
        await update.message.reply_text("Дякую, тепер давай продовжимо спілкування 😊", reply_markup=menu_keyboard)
    except (IOError, json.JSONDecodeError) as e:
        print(f"ERROR: Не вдалося зберегти анкету для {user_id}: {e}")
        await update.message.reply_text("Вибачте, сталася помилка при збереженні анкети.")

    context.user_data.clear() # Очищуємо дані після збереження
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: Анкета відхилена користувачем")
    context.user_data.clear() # Очищуємо дані при відміні
    await update.message.reply_text("Анкета відхилена.", reply_markup=menu_keyboard) # Показуємо меню
    return ConversationHandler.END

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: Запит профілю")
    user_id = str(update.effective_user.id)
    if not is_registered(user_id):
        await update.message.reply_text("Ти ще не зареєстрований. Напиши /start.")
        return ConversationHandler.END # Повертаємо, щоб вийти з можливого діалогу

    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        user = data[user_id]
        profile_text = (
            f"👤 *Твоя анкета:*\n"
            f"Ім'я: {user.get('name', 'N/A')}\n"
            f"Призвіще: {user.get('surname', 'N/A')}\n"
            f"Телефон: {user.get('phone', 'N/A')}\n"
            f"Спеціальність: {user.get('specialty', 'N/A')}"
        )
        await update.message.reply_text(profile_text, parse_mode=ParseMode.MARKDOWN_V2) # Використовуємо константу
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR: Не вдалося завантажити профіль для {user_id}: {e}")
        await update.message.reply_text("Вибачте, не вдалося завантажити ваш профіль.")
    # Не повертаємо стан, бо це не частина діалогу заповнення анкети

async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_registered(user_id):
         await update.message.reply_text("Ти ще не зареєстрований. Напиши /start.")
         return ConversationHandler.END # Виходимо, якщо не зареєстрований

    print("DEBUG: Оновлення профілю")
    await update.message.reply_text("Оновимо анкету. Як тебе звати?")
    return NAME # Починаємо діалог оновлення

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Цей хендлер обробляє текст, який НЕ є командою І НЕ оброблений ConversationHandler або іншими MessageHandler (Regex)
    if not update.message or not update.message.text:
        return # Ігноруємо порожні повідомлення

    print("🚀 Отримано текстове повідомлення:", update.message.text)
    user_id = update.effective_user.id
    text = update.message.text

    # --- Перевірка кнопок меню (дублювання з реєстрації хендлерів, можна прибрати, якщо хендлери налаштовані коректно) ---
    # Цей блок може бути необов'язковим, якщо Regex хендлери працюють стабільно
    if text == "📋 Профіль":
        return await show_profile(update, context)
    # Обробка "✏️ Обновить анкету" ініціюється через ConversationHandler, тут не потрібна

    # --- Перевірка реєстрації ---
    if not is_registered(user_id):
        await update.message.reply_text("Спочатку треба заповнити анкету. Напиши /start.")
        return # Немає стану для повернення, бо це не ConversationHandler

    # --- Обробка повідомлення через QA Engine ---
    user = update.effective_user
    username = user.username or user.first_name # Використовуємо ім'я, якщо немає username
    log_message(user.id, username, update.message.message_id, "text", "question", text)

    try:
        # Припускаємо, що qa_engine існує і функція get_answer є
        from qa_engine import get_answer
        answer = get_answer(text) # Переконайтесь, що ця функція існує і працює
        print("💬 Відповідь бота:", answer)
        log_message(user.id, username, update.message.message_id, "text", "answer", answer)
        await update.message.reply_text(answer, parse_mode=ParseMode.HTML)
    except ImportError:
         print("ERROR: Модуль qa_engine не знайдено!")
         await update.message.reply_text("Вибачте, мій модуль відповідей зараз недоступний.")
    except Exception as e:
        print(f"ERROR: Помилка при отриманні відповіді від qa_engine: {e}")
        await update.message.reply_text("Вибачте, сталася помилка при обробці вашого запиту.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ваш код handle_voice без змін, але переконайтеся, що ffmpeg встановлено на Render
    user_id = update.effective_user.id
    print("DEBUG: Обробка голосового повідомлення")
    if not is_registered(user_id):
        await update.message.reply_text("Спочатку треба заповнити анкету. Напиши /start.")
        return

    voice = update.message.voice
    user = update.message.from_user
    username = user.username or user.first_name # Використовуємо ім'я, якщо немає username

    input_ogg = f"voice_{user_id}.ogg" # Додаємо user_id для унікальності
    output_wav = f"voice_{user_id}.wav"

    try:
        # Завантажуємо файл
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(input_ogg)
        print(f"DEBUG: Voice file downloaded to {input_ogg}")

        # Конвертуємо через ffmpeg
        print("DEBUG: Конвертація через ffmpeg")
        process = subprocess.run(
            ["ffmpeg", "-y", "-i", input_ogg, "-acodec", "pcm_s16le", "-ar", "16000", output_wav], # Додано параметри для кращої сумісності з Whisper
            capture_output=True, text=True, check=True
        )
        print("DEBUG: ffmpeg stdout:", process.stdout)
        print("DEBUG: ffmpeg stderr:", process.stderr)
        print(f"DEBUG: Converted file saved to {output_wav}")


        # Розпізнаємо через Whisper
        with open(output_wav, "rb") as f:
            print("DEBUG: Отправка в Whisper API")
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
        recognized_text = response.text
        print(f"DEBUG: Роспізнаний текст: {recognized_text}")

        log_message(user.id, username, update.message.message_id, "voice", "question", recognized_text)

        # Отримуємо відповідь
        from qa_engine import get_answer # Переконайтесь, що імпорт тут доречний або зробіть його глобальним
        answer = get_answer(recognized_text)
        log_message(user.id, username, update.message.message_id, "voice", "answer", answer)
        await update.message.reply_text(answer, parse_mode=ParseMode.HTML)

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
        # Гарантовано видаляємо тимчасові файли
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
            MessageHandler(filters.Regex('^✏️ Оновити анкету$'), update_profile), # Використовуємо 'update_profile' напряму
        ],
        states={
            # Аналогічно для всіх функцій-обробників стану
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            SPECIALTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_specialty)],
        },
        fallbacks=[CommandHandler("cancel", cancel)], # Використовуємо 'cancel' напряму
        per_message=False
    )
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex('^📋 Профіль$'), show_profile)) # Використовуємо 'show_profile' напряму
    application.add_handler(CommandHandler("profile", show_profile)) # Те саме
    application.add_handler(MessageHandler(filters.VOICE, handle_voice)) # Використовуємо 'handle_voice' напряму
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)) # Використовуємо 'handle_message' напряму

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
