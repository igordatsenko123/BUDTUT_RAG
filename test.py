import os
import json
import subprocess
import pandas as pd
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes,
    CommandHandler, ConversationHandler, ApplicationBuilder # Додано ApplicationBuilder
)
from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY
from qa_engine import get_answer
from openai import OpenAI
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio
# import threading # Прибираємо цей імпорт

client = OpenAI(api_key=OPENAI_API_KEY)

# === Файлы ===
USER_FILE = "user_info.json"
LOG_FILE = "chat_history.csv"

# === Состояния анкеты ===
NAME, SURNAME, PHONE, SPECIALTY = range(4)

# === Кнопки меню ===
menu_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("📋 Профиль")], [KeyboardButton("✏️ Обновить анкету")]],
    resize_keyboard=True
)


print("DEBUG: Импорты завершены")

# === Логирование ===
# ... (ваш код логування без змін) ...
def log_message(user_id, username, msg_id, msg_type, role, content):
    print(f"DEBUG: Логируем сообщение от {username} ({user_id}) - {role}: {content}")
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
        print(f"ERROR: Ошибка при логировании: {e}")


# === Проверка регистрации ===
# ... (ваш код перевірки реєстрації без змін) ...
def is_registered(user_id):
    print(f"DEBUG: Проверяем регистрацию user_id={user_id}")
    if not os.path.exists(USER_FILE):
        return False
    with open(USER_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return str(user_id) in data

# === Анкета ===
# ... (ваші обробники анкети start, get_name і т.д. без змін) ...
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"DEBUG: Команда /start от user_id={user_id}")
    if is_registered(user_id):
        name = json.load(open(USER_FILE, encoding="utf-8"))[str(user_id)]["name"]
        await update.message.reply_text(
            f"С возвращением, {name}!\nВыбери, что хочешь сделать:",
            reply_markup=menu_keyboard
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Привет! Давай сначала заполним анкету. Как тебя зовут?")
        return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Получено имя: {update.message.text}")
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Фамилия?")
    return SURNAME

async def get_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Получена фамилия: {update.message.text}")
    context.user_data["surname"] = update.message.text
    await update.message.reply_text("Телефон?")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Получен телефон: {update.message.text}")
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Специальность?")
    return SPECIALTY

async def get_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: Завершение анкеты")
    context.user_data["specialty"] = update.message.text
    user_id = str(update.effective_user.id)

    user_info = {
        "name": context.user_data["name"],
        "surname": context.user_data["surname"],
        "phone": context.user_data["phone"],
        "specialty": context.user_data["specialty"]
    }

    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    data[user_id] = user_info
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"DEBUG: Анкета сохранена для user_id={user_id}")
    await update.message.reply_text("Спасибо! Теперь давай продолжим общение 😊", reply_markup=menu_keyboard)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: Анкета отменена пользователем")
    await update.message.reply_text("Анкета отменена.")
    return ConversationHandler.END

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: Запрос профиля")
    user_id = str(update.effective_user.id)
    if not is_registered(user_id):
        await update.message.reply_text("Ты ещё не зарегистрирован. Напиши /start.")
        return
    with open(USER_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    user = data[user_id]
    profile_text = (
        f"👤 *Твоя анкета:*\n"
        f"Имя: {user['name']}\n"
        f"Фамилия: {user['surname']}\n"
        f"Телефон: {user['phone']}\n"
        f"Специальность: {user['specialty']}"
    )
    await update.message.reply_text(profile_text, parse_mode="Markdown")

async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: Обновление профиля")
    await update.message.reply_text("Обновим анкету. Как тебя зовут?")
    return NAME

# === Обработка сообщений ===
# ... (ваш код handle_message та handle_voice без змін) ...
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🚀 Сообщение получено:", update.message.text)  # Логируем текст сообщения
    user_id = update.effective_user.id
    text = update.message.text

    # Перевірка кнопок меню повинна йти ПЕРЕД перевіркою реєстрації,
    # якщо кнопки доступні незареєстрованим
    # Але у вашій логіці кнопки з'являються після /start для зареєстрованих,
    # отже поточний порядок має сенс.

    if text == "📋 Профиль":
         # Перевіряємо реєстрацію ТУТ, перед викликом show_profile
        if not is_registered(user_id):
            await update.message.reply_text("Ты ещё не зарегистрирован. Напиши /start.")
            return ConversationHandler.END # або просто return, якщо поза конверсейшеном
        return await show_profile(update, context) # Передаємо керування далі

    elif text == "✏️ Обновить анкету":
         # Перевіряємо реєстрацію ТУТ
        if not is_registered(user_id):
            await update.message.reply_text("Ты ещё не зарегистрирован. Напиши /start.")
            return ConversationHandler.END # або просто return
        # Повертаємо стан NAME для початку оновлення анкети
        await update.message.reply_text("Обновим анкету. Как тебя зовут?")
        return NAME # Має повернути стан для ConversationHandler


    # Якщо це не кнопка, перевіряємо реєстрацію для звичайних повідомлень
    if not is_registered(user_id):
        await update.message.reply_text("Сначала нужно заполнить анкету. Напиши /start.")
        # Важливо: якщо цей хендлер не є частиною ConversationHandler,
        # то просто return достатньо. Якщо є, треба повернути відповідний стан або END
        return ConversationHandler.END # Або просто return

    user = update.effective_user
    log_message(user.id, user.username, update.message.message_id, "text", "question", text)

    answer = get_answer(text)
    print("💬 Ответ бота:", answer)  # Логируем ответ бота

    log_message(user.id, user.username, update.message.message_id, "text", "answer", answer)
    await update.message.reply_text(answer)
    # Тут теж потрібно повернути стан, якщо цей хендлер є частиною ConversationHandler
    # Якщо ні - повертати нічого не треба. Судячи з коду, цей хендлер НЕ в ConversationHandler.


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print("DEBUG: Обработка голосового сообщения")
    if not is_registered(user_id):
        await update.message.reply_text("Сначала нужно заполнить анкету. Напиши /start.")
        return

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    user = update.message.from_user

    input_ogg = f"voice_{user_id}.ogg" # Додаємо user_id для унікальності
    output_wav = f"voice_{user_id}.wav"
    await file.download_to_drive(input_ogg)

    print("DEBUG: Конвертация через ffmpeg")
    try:
        # Додаємо перевірку виводу ffmpeg
        process = subprocess.run(
            ["ffmpeg", "-y", "-i", input_ogg, output_wav],
            capture_output=True, text=True, check=True
        )
        print("DEBUG: ffmpeg stdout:", process.stdout)
        print("DEBUG: ffmpeg stderr:", process.stderr)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: ffmpeg failed: {e}")
        print(f"ERROR: ffmpeg stdout: {e.stdout}")
        print(f"ERROR: ffmpeg stderr: {e.stderr}")
        await update.message.reply_text("Не вдалося обробити голосове повідомлення.")
        # Clean up even if ffmpeg fails
        if os.path.exists(input_ogg):
             os.remove(input_ogg)
        if os.path.exists(output_wav):
             os.remove(output_wav)
        return
    except FileNotFoundError:
        print("ERROR: ffmpeg не знайдено. Переконайтесь, що він встановлений та є в PATH.")
        await update.message.reply_text("Помилка обробки аудіо: ffmpeg не знайдено.")
         # Clean up
        if os.path.exists(input_ogg):
             os.remove(input_ogg)
        return


    try:
        with open(output_wav, "rb") as f:
            print("DEBUG: Отправка в Whisper API")
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
        recognized_text = response.text
        print(f"DEBUG: Распознанный текст: {recognized_text}")

        log_message(user.id, user.username, update.message.message_id, "voice", "question", recognized_text)

        answer = get_answer(recognized_text)

        log_message(user.id, user.username, update.message.message_id, "voice", "answer", answer)
        await update.message.reply_text(answer)

    except Exception as e:
        print(f"ERROR: Помилка під час розпізнавання або відповіді: {e}")
        await update.message.reply_text("Виникла помилка під час обробки вашого запиту.")
    finally:
        # Гарантовано видаляємо файли
        if os.path.exists(input_ogg):
            os.remove(input_ogg)
        if os.path.exists(output_wav):
            os.remove(output_wav)


# --- Оновлений Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🔁 Lifespan запускается: инициализация...")

    # Ініціалізуємо Telegram-додаток
    # Використовуємо ApplicationBuilder для кращої конфігурації
    telegram_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Реєструємо обробники
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            # Додаємо обробку кнопок як точки входу, якщо вони можуть почати оновлення
            MessageHandler(filters.Regex('^✏️ Обновить анкету$'), update_profile),
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            SPECIALTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_specialty)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
         # Дозволяємо іншим хендлерам працювати, коли діалог неактивний
        per_message=False # Або True, залежно від бажаної логіки, але False частіше підходить
    )

    telegram_app.add_handler(conv_handler)

    # Додаємо обробники для кнопок та команд ПОЗА діалогом
    # Обробка кнопки "Профіль"
    telegram_app.add_handler(MessageHandler(filters.Regex('^📋 Профиль$'), show_profile))
    # Обробка команди /profile (якщо потрібна)
    telegram_app.add_handler(CommandHandler("profile", show_profile))
    # Обробка голосових
    telegram_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    # Обробка інших текстових повідомлень (має бути ОСТАННІМ текстовим)
    # Важливо: цей хендлер спрацює, якщо текст не є командою, не підійшов до Regex фільтрів вище,
    # і ConversationHandler не активний або дозволяє пропуск (fallbacks/per_message)
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


    # Ініціалізуємо додаток PTB (готує все до запуску)
    await telegram_app.initialize()

    # Запускаємо обробку апдейтів (polling) у фоновому режимі
    # Це НЕ блокує FastAPI
    await telegram_app.start()
    await telegram_app.updater.start_polling() # Не забуваємо запустити саме отримання апдейтів

    print("✅ Telegram Bot запущен в режиме polling")

    yield # FastAPI/Uvicorn працюють тут

    # Коректна зупинка при завершенні роботи FastAPI
    print("❌ Lifespan завершается: останавливаем бота...")
    await telegram_app.updater.stop() # Зупиняємо polling
    await telegram_app.stop() # Зупиняємо обробку апдейтів
    await telegram_app.shutdown() # Вивільняємо ресурси
    print("🛑 Telegram Bot остановлен")

# === FastAPI приложение ===
# Передаємо оновлений lifespan
fastapi_app = FastAPI(lifespan=lifespan)

# Додаємо простий ендпоінт для перевірки роботи FastAPI
@fastapi_app.get("/")
async def root():
    return {"message": "FastAPI is running"}

if __name__ == "__main__":
    print("DEBUG: Запуск FastAPI через Uvicorn")
    # Переконайтесь, що uvicorn встановлено: pip install uvicorn[standard]
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)